"""Lightweight repo cartographer mapping files, tests, and boundaries progressively."""

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class RepoMap:
    root_path: str
    languages: Set[str] = field(default_factory=set)
    frameworks: Set[str] = field(default_factory=set)
    entrypoints: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    protected_paths: List[str] = field(default_factory=list)
    generated_paths: List[str] = field(default_factory=list)
    ownership_boundaries: Dict[str, str] = field(default_factory=dict)


class RepoCartographer:
    """Builds progressive depth cartography of repository surfaces."""

    def __init__(self, root_path: str) -> None:
        self.root = Path(root_path).resolve()

    def inspect_level_0(self) -> RepoMap:
        """Level 0: fast file structure and framework detection."""
        languages: Set[str] = set()
        frameworks: Set[str] = set()
        tests: List[str] = []
        entrypoints: List[str] = []
        protected: List[str] = [".git", ".env"]
        generated: List[str] = ["dist", "build", "__pycache__", ".pytest_cache", "node_modules"]

        if not self.root.exists():
            return RepoMap(root_path=str(self.root))

        for entry in os.scandir(self.root):
            name = entry.name
            if name.endswith(".py") or name in ("pyproject.toml", "setup.py", "requirements.txt"):
                languages.add("python")
            elif name in ("package.json", "bun.lockb", "tsconfig.json"):
                languages.add("typescript")
                frameworks.add("node/bun")

            if name == "tests" and entry.is_dir():
                for t_entry in os.scandir(entry.path):
                    if t_entry.name.startswith("test_") and t_entry.name.endswith(".py"):
                        tests.append(os.path.relpath(t_entry.path, self.root))

            if name in ("pyproject.toml", "setup.cfg"):
                frameworks.add("pytest")

        return RepoMap(
            root_path=str(self.root),
            languages=languages,
            frameworks=frameworks,
            entrypoints=entrypoints,
            tests=tests,
            protected_paths=protected,
            generated_paths=generated,
        )

    def locate_targeted_test(self, file_path: str) -> Optional[str]:
        """Locates the closest exact test corresponding to an affected file."""
        target_name = Path(file_path).stem
        # e.g., src/router.py -> tests/test_router.py
        candidate = self.root / "tests" / f"test_{target_name}.py"
        if candidate.exists():
            return str(candidate.relative_to(self.root))
        return None
