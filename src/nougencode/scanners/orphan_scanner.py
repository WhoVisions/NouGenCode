"""Orphan file and obsolete root script scanner."""

import re
from pathlib import Path
from typing import Dict, List, Set

from ..models import CodeIssue, IssueType


class OrphanFileScanner:
    """Scans for standalone scripts, orphan prototypes, and test files that are never imported or called."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def scan_orphans(self) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        py_files = list(self.root_dir.glob("*.py"))  # Focus on root scripts first
        if not py_files:
            return issues

        # Map stems and full filenames
        file_stems = {f.stem: f for f in py_files}

        # Gather references across all python files
        all_referenced_names: Set[str] = set()
        for f in self.root_dir.rglob("*.py"):
            if ".venv" in f.parts or "node_modules" in f.parts or ".git" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                # Look for imports like `import foo` or `from foo import ...`
                for match in re.finditer(r"\b(?:import|from)\s+([a-zA-Z0-9_]+)", text):
                    all_referenced_names.add(match.group(1))
            except Exception:
                pass

        # Check root files
        for stem, path in file_stems.items():
            # If not imported and looks like a temp/adhoc test script (e.g., test_*, temp_*, debug_*)
            if stem not in all_referenced_names and (
                stem.startswith("test_")
                or stem.startswith("temp_")
                or stem.startswith("tmp_")
                or stem.startswith("debug_")
                or stem.endswith("_test")
                or stem.endswith("_temp")
            ):
                issues.append(
                    CodeIssue(
                        issue_type=IssueType.ORPHAN_FILE,
                        file_path=str(path),
                        line_number=1,
                        symbol_name=path.name,
                        message=f"Root scratch/test script '{path.name}' is unreferenced in codebase",
                        severity="info",
                        suggested_action="Archive to scratch directory or consolidate into formal test suite",
                    )
                )

        return issues
