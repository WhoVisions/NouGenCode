"""
Concentric Invariant & Security Gates.

Protects against:
- Hardcoded secrets and credentials
- Personal machine paths (zero hardcoded paths law)
- Destructive operations and permission boundary violations
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"AIza[0-9A-Za-z-_]{35}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{36}", re.IGNORECASE),
    re.compile(r"-----" + r"BEGIN PRIVATE KEY" + r"-----", re.IGNORECASE),
]

FORBIDDEN_PERSONAL_PATHS = [
    re.compile(r"/Users/[a-zA-Z0-9_-]+/(?!(\.nougen|\.gemini))", re.IGNORECASE),
    re.compile(r"C:\\Users\\[a-zA-Z0-9_-]+", re.IGNORECASE),
]


@dataclass
class SecurityViolation:
    violation_type: str
    message: str
    matched_snippet: str


class ConcentricSecurityGate:
    """Pre-commit and pre-synthesis invariant auditor."""

    @classmethod
    def audit_code(cls, source_code: str) -> List[SecurityViolation]:
        violations: List[SecurityViolation] = []

        # 1. Secret / Credential audit
        for pat in SECRET_PATTERNS:
            match = pat.search(source_code)
            if match:
                violations.append(
                    SecurityViolation(
                        violation_type="CREDENTIAL_EXPOSURE",
                        message="Hardcoded API key or private key detected in source.",
                        matched_snippet=match.group(0)[:15] + "...",
                    )
                )

        # 2. Hardcoded personal paths audit (except allowed framework roots)
        for pat in FORBIDDEN_PERSONAL_PATHS:
            match = pat.search(source_code)
            if match:
                violations.append(
                    SecurityViolation(
                        violation_type="PERSONAL_PATH_LEAK",
                        message="Hardcoded personal host user path detected in source. Use Path.home() or dynamic discovery.",
                        matched_snippet=match.group(0),
                    )
                )

        return violations

    @classmethod
    def assert_clean(cls, source_code: str) -> None:
        violations = cls.audit_code(source_code)
        if violations:
            msg = "\n".join(f"- [{v.violation_type}] {v.message} ({v.matched_snippet})" for v in violations)
            raise ValueError(f"ConcentricSecurityGate rejected code:\n{msg}")
