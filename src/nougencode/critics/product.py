"""Evidence-constrained latent specification review.

This module validates proposals and independent implementation checks. It does
not generate product requirements from keyword presence or donor-model claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Mapping, Sequence


class EvidenceKind(str, Enum):
    ARCHITECTURE = "architecture"
    EXISTING_PATTERN = "existing_pattern"
    TEST = "test"
    BUSINESS_RULE = "business_rule"
    SECURITY_POLICY = "security_policy"
    PRODUCT_INVARIANT = "product_invariant"
    USER_REQUIREMENT = "user_requirement"
    DONOR_CLAIM = "donor_claim"


class ImplementationStatus(str, Enum):
    IMPLEMENTED = "implemented"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProductEvidence:
    evidence_id: str
    kind: EvidenceKind
    reference: str


@dataclass(frozen=True)
class RequirementProposal:
    requirement_id: str
    title: str
    description: str
    category: str
    proposer_id: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ImplementationCheck:
    requirement_id: str
    verifier_id: str
    status: ImplementationStatus
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequirementFinding:
    proposal: RequirementProposal
    supported: bool
    hallucinated: bool
    support_issue: str | None
    implementation_status: ImplementationStatus
    verification_issue: str | None


@dataclass(frozen=True)
class LscEvaluationResult:
    explicit_count: int
    inferred_valid_count: int
    hallucinated_count: int
    lsc_score: float
    implemented_count: int
    missing_count: int
    unknown_count: int
    findings: tuple[RequirementFinding, ...]

    @property
    def implementation_coverage(self) -> float | None:
        assessed = self.implemented_count + self.missing_count
        return self.implemented_count / assessed if assessed else None

    @property
    def assessment_coverage(self) -> float:
        total = self.inferred_valid_count
        return ((self.implemented_count + self.missing_count) / total) if total else 0.0


class ProductJudgmentCritic:
    """Assess inferred requirements against repository and user evidence.

    Evidence IDs are stable references into an upstream context bundle. Donor
    articles can motivate proposals but cannot by themselves validate a
    NouGen-specific requirement. Implemented/missing status must come from an
    independent verifier with cited evidence.
    """

    STANDARD_INSPECTION_DIMENSIONS = (
        ("empty_state", "Does the view communicate an empty collection?"),
        ("loading_state", "Is asynchronous work visibly represented?"),
        ("keyboard_nav", "Can interactive controls be used by keyboard?"),
        ("error_boundary", "Are malformed or unexpected payloads handled?"),
        ("destructive_guard", "Are destructive actions protected?"),
        ("status_iconography", "Are status symbols semantically clear?"),
        ("freshness", "Is stale or uncertain data distinguished from current data?"),
        ("responsive_layout", "Does the layout work at supported viewport sizes?"),
        ("privacy", "Does the UI avoid exposing data outside the task scope?"),
    )

    def __init__(self, penalty_lambda: float = 2.0):
        if not isfinite(penalty_lambda) or penalty_lambda <= 1:
            raise ValueError("penalty_lambda must be finite and greater than 1")
        self.penalty_lambda = penalty_lambda

    def evaluate_inferred_requirements(
        self,
        *,
        explicit_requirements: Sequence[str],
        proposals: Sequence[RequirementProposal],
        evidence: Sequence[ProductEvidence],
        implementation_checks: Sequence[ImplementationCheck],
    ) -> LscEvaluationResult:
        """Score evidence-supported proposals and report independently checked gaps."""
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise ValueError("evidence IDs must be unique")
        proposal_ids = [item.requirement_id for item in proposals]
        if len(set(proposal_ids)) != len(proposal_ids):
            raise ValueError("requirement proposal IDs must be unique")
        checks: dict[str, ImplementationCheck] = {}
        for check in implementation_checks:
            if check.requirement_id in checks:
                raise ValueError("each proposal may have at most one independent implementation check")
            checks[check.requirement_id] = check
        if set(checks) - set(proposal_ids):
            raise ValueError("implementation check references an unknown requirement proposal")

        findings: list[RequirementFinding] = []
        for proposal in proposals:
            if not all((proposal.requirement_id.strip(), proposal.title.strip(),
                        proposal.description.strip(), proposal.category.strip(),
                        proposal.proposer_id.strip())):
                raise ValueError("requirement proposal fields must be non-empty")
            cited = [evidence_by_id.get(ref) for ref in proposal.evidence_ids]
            if not proposal.evidence_ids:
                support_issue = "proposal has no evidence references"
            elif any(item is None for item in cited):
                support_issue = "proposal cites evidence absent from the context bundle"
            elif not any(item.kind is not EvidenceKind.DONOR_CLAIM for item in cited if item is not None):
                support_issue = "donor claims cannot alone establish a NouGen requirement"
            else:
                support_issue = None
            supported = support_issue is None
            check = checks.get(proposal.requirement_id)
            status = ImplementationStatus.UNKNOWN
            verification_issue = None
            if check is not None:
                if check.verifier_id == proposal.proposer_id:
                    verification_issue = "implementation check is not independent"
                elif check.status is not ImplementationStatus.UNKNOWN and not check.evidence_ids:
                    verification_issue = "implemented/missing status has no evidence references"
                elif any(ref not in evidence_by_id for ref in check.evidence_ids):
                    verification_issue = "implementation check cites evidence absent from the context bundle"
                else:
                    status = check.status
            findings.append(RequirementFinding(
                proposal, supported, not supported, support_issue,
                status, verification_issue,
            ))

        valid_count = sum(item.supported for item in findings)
        hallucinated_count = sum(item.hallucinated for item in findings)
        denominator = valid_count + self.penalty_lambda * hallucinated_count
        lsc = valid_count / denominator if denominator else 1.0
        implemented = sum(item.supported and item.implementation_status is ImplementationStatus.IMPLEMENTED
                          for item in findings)
        missing = sum(item.supported and item.implementation_status is ImplementationStatus.MISSING
                      for item in findings)
        unknown = len(findings) - implemented - missing
        return LscEvaluationResult(
            len(explicit_requirements), valid_count, hallucinated_count, lsc,
            implemented, missing, unknown, tuple(findings),
        )
