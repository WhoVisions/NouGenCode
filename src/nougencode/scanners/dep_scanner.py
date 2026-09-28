"""Dependency bloat scanner."""

import re
from pathlib import Path
from typing import List, Set

from ..models import CodeIssue, IssueType


class DependencyScanner:
    """Scans requirements.txt and code imports to detect unreferenced or bloated packages."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def scan_dependencies(self) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        req_file = self.root_dir / "requirements.txt"
        if not req_file.exists():
            return issues

        try:
            req_lines = req_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return issues

        declared_packages: Set[str] = set()
        for line in req_lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = re.split(r"[><=~;]", line)[0].strip().lower().replace("-", "_")
            if pkg:
                declared_packages.add(pkg)

        # Collect all imported module names across python files
        imported_modules: Set[str] = set()
        for f in self.root_dir.rglob("*.py"):
            if ".venv" in f.parts or "node_modules" in f.parts or ".git" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)", text, re.MULTILINE):
                    imported_modules.add(match.group(1).lower().replace("-", "_"))
            except Exception:
                pass

        # Identify packages declared but never imported
        # Common package-to-import mapping overrides can be added as needed
        for pkg in declared_packages:
            if pkg not in imported_modules:
                issues.append(
                    CodeIssue(
                        issue_type=IssueType.UNUSED_DEPENDENCY,
                        file_path=str(req_file),
                        line_number=1,
                        symbol_name=pkg,
                        message=f"Package '{pkg}' is in requirements.txt but no import was detected",
                        severity="info",
                        suggested_action="Verify if package is runtime/CLI only or remove from requirements",
                    )
                )

        return issues
