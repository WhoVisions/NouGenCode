"""Orphan file and obsolete root script scanner."""

from pathlib import Path
from typing import List

from ..models import CodeIssue, IssueType
from .dep_scanner import collect_imported_modules


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

        # Gather references across all python files using shared collector
        all_referenced_names = collect_imported_modules(self.root_dir, lowercase=False)

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
