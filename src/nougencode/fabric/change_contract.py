"""ChangeContract cleanly separating functional requirements from review constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FunctionalRequirement:
    req_id: str
    description: str
    target_artifacts: Sequence[str]
    invariants: Sequence[str]
    acceptance_tests: Sequence[str]
    expected_outcomes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewConstraint:
    constraint_id: str
    max_mutation_files: int
    max_mutation_lines: int
    required_reviewers: Sequence[str]
    forbidden_patterns: Sequence[str]
    allow_destructive: bool = False
    shadow_policy_rules: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChangeContract:
    contract_id: str
    title: str
    functional_requirements: Sequence[FunctionalRequirement]
    review_constraints: ReviewConstraint
    version: str = "1.0.0"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("contract_id must not be empty")
        if not self.functional_requirements:
            raise ValueError("ChangeContract must have at least one functional requirement")

    @property
    def fingerprint(self) -> str:
        payload = {
            "contract_id": self.contract_id,
            "version": self.version,
            "functional_requirements": [
                {
                    "req_id": r.req_id,
                    "target_artifacts": list(r.target_artifacts),
                    "invariants": list(r.invariants),
                    "acceptance_tests": list(r.acceptance_tests),
                }
                for r in self.functional_requirements
            ],
            "review_constraints": {
                "constraint_id": self.review_constraints.constraint_id,
                "max_mutation_files": self.review_constraints.max_mutation_files,
                "max_mutation_lines": self.review_constraints.max_mutation_lines,
                "forbidden_patterns": list(self.review_constraints.forbidden_patterns),
            },
        }
        return _canonical_hash(payload)

    def validate_mutation(
        self,
        files_touched: Sequence[str],
        lines_changed: int,
        diff_text: str = "",
    ) -> Tuple[bool, Sequence[str]]:
        """Verify proposed patch against review constraints."""
        violations: List[str] = []
        if len(files_touched) > self.review_constraints.max_mutation_files:
            violations.append(
                f"File mutation limit exceeded: {len(files_touched)} > {self.review_constraints.max_mutation_files}"
            )
        if lines_changed > self.review_constraints.max_mutation_lines:
            violations.append(
                f"Line mutation limit exceeded: {lines_changed} > {self.review_constraints.max_mutation_lines}"
            )
        for pat in self.review_constraints.forbidden_patterns:
            if pat in diff_text:
                violations.append(f"Forbidden pattern detected in patch: '{pat}'")

        return (len(violations) == 0, tuple(violations))
