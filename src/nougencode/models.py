"""Data models for code analysis, deadcode detection, and bloat reports."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class IssueType(str, Enum):
    UNUSED_IMPORT = "UNUSED_IMPORT"
    UNUSED_FUNCTION = "UNUSED_FUNCTION"
    UNUSED_CLASS = "UNUSED_CLASS"
    UNUSED_VARIABLE = "UNUSED_VARIABLE"
    ORPHAN_FILE = "ORPHAN_FILE"
    DUPLICATE_HELPER = "DUPLICATE_HELPER"
    UNUSED_DEPENDENCY = "UNUSED_DEPENDENCY"
    STALE_PROTOTYPE = "STALE_PROTOTYPE"


@dataclass
class CodeIssue:
    issue_type: IssueType
    file_path: str
    line_number: int
    symbol_name: str
    message: str
    severity: str = "warning"  # info, warning, error
    snippet: Optional[str] = None
    suggested_action: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.issue_type.value,
            "file": self.file_path,
            "line": self.line_number,
            "symbol": self.symbol_name,
            "message": self.message,
            "severity": self.severity,
            "snippet": self.snippet,
            "action": self.suggested_action,
        }


@dataclass
class ScanSummary:
    target_root: str
    files_scanned: int = 0
    total_lines: int = 0
    issues: List[CodeIssue] = field(default_factory=list)
    timestamp: str = ""

    def add_issue(self, issue: CodeIssue) -> None:
        self.issues.append(issue)

    @property
    def issues_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for issue in self.issues:
            counts[issue.issue_type.value] = counts.get(issue.issue_type.value, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_root": self.target_root,
            "files_scanned": self.files_scanned,
            "total_lines": self.total_lines,
            "total_issues": len(self.issues),
            "counts": self.issues_by_type,
            "timestamp": self.timestamp,
            "issues": [i.to_dict() for i in self.issues],
        }
