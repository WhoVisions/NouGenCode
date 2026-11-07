"""Dependency bloat and unreferenced package scanner."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set

try:
    import tomllib
except ImportError:
    tomllib = None  # type: ignore

from ..models import CodeIssue, IssueType

PACKAGE_IMPORT_MAPPING: Dict[str, str] = {
    "pyyaml": "yaml",
    "python_dotenv": "dotenv",
    "pydantic_settings": "pydantic_settings",
    "pytest_asyncio": "pytest_asyncio",
    "scikit_learn": "sklearn",
    "pillow": "pil",
    "google_genai": "google",
    "prompt_toolkit": "prompt_toolkit",
    "opencv_python": "cv2",
    "beautifulsoup4": "bs4",
    "apache_beam": "apache_beam",
}


class DependencyScanner:
    """Scans requirements.txt and pyproject.toml against code imports to detect unreferenced or bloated packages."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def _extract_requirements_txt(self, req_path: Path) -> Set[str]:
        packages: Set[str] = set()
        try:
            for line in req_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                pkg = re.split(r"[><=~;\[]", line)[0].strip().lower().replace("-", "_")
                if pkg:
                    packages.add(pkg)
        except Exception:
            pass
        return packages

    def _extract_pyproject_toml(self, toml_path: Path) -> Set[str]:
        packages: Set[str] = set()
        try:
            content = toml_path.read_text(encoding="utf-8", errors="ignore")
            if tomllib is not None:
                data = tomllib.loads(content)
                # PEP 621 project dependencies
                deps = data.get("project", {}).get("dependencies", [])
                for d in deps:
                    pkg = re.split(r"[><=~;\[]", d)[0].strip().lower().replace("-", "_")
                    if pkg:
                        packages.add(pkg)
                # Poetry dependencies
                poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
                for p in poetry_deps.keys():
                    if p.lower() != "python":
                        packages.add(p.strip().lower().replace("-", "_"))
            else:
                in_deps = False
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("dependencies = ["):
                        in_deps = True
                        continue
                    if in_deps:
                        if line.startswith("]"):
                            in_deps = False
                            continue
                        m = re.search(r"[\"']([a-zA-Z0-9_\-]+)", line)
                        if m:
                            packages.add(m.group(1).lower().replace("-", "_"))
        except Exception:
            pass
        return packages

    def _is_package_used(self, pkg: str, imported_modules: Set[str]) -> bool:
        if pkg in imported_modules:
            return True
        mapped = PACKAGE_IMPORT_MAPPING.get(pkg)
        if mapped and mapped in imported_modules:
            return True
        return False

    def scan_dependencies(self) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        declared_files: Dict[str, Path] = {}

        # 1. Inspect requirements.txt
        req_file = self.root_dir / "requirements.txt"
        if req_file.exists():
            for pkg in self._extract_requirements_txt(req_file):
                declared_files[pkg] = req_file

        # 2. Inspect pyproject.toml
        pyproject_file = self.root_dir / "pyproject.toml"
        if pyproject_file.exists():
            for pkg in self._extract_pyproject_toml(pyproject_file):
                if pkg not in declared_files:
                    declared_files[pkg] = pyproject_file

        if not declared_files:
            return issues

        # 3. Collect imported modules across repository
        imported_modules: Set[str] = set()
        for f in self.root_dir.rglob("*.py"):
            if any(p in f.parts for p in (".venv", "node_modules", ".git", "__pycache__")):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)", text, re.MULTILINE):
                    imported_modules.add(match.group(1).lower().replace("-", "_"))
            except Exception:
                pass

        # 4. Identify packages declared but never imported
        for pkg, source_file in sorted(declared_files.items()):
            if not self._is_package_used(pkg, imported_modules):
                issues.append(
                    CodeIssue(
                        issue_type=IssueType.UNUSED_DEPENDENCY,
                        file_path=str(source_file.relative_to(self.root_dir) if source_file.is_relative_to(self.root_dir) else source_file),
                        line_number=1,
                        symbol_name=pkg,
                        message=f"Package '{pkg}' is declared in {source_file.name} but no import was detected",
                        severity="info",
                        suggested_action=f"Verify if '{pkg}' is runtime/CLI only or remove from dependencies",
                    )
                )

        return issues
