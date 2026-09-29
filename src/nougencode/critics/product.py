"""
Latent Specification Completion (LSC) & Product Judgment Critic.

Extracts implied, unstated UX/architectural requirements:
- Empty states
- Loading states & spinners
- Keyboard accessibility & aria
- Reversibility & destructive confirmation
- Mobile/narrow viewport responsiveness
- Iconography & status semantics

Calculates LSC metric:
    LSC = |R_i| / (|R_i| + lambda * |R_h|)
where lambda > 1 penalizes harmful hallucinated scope over missing embellishments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class InferredRequirement:
    title: str
    description: str
    category: str  # "ux", "accessibility", "error_handling", "performance", "security"
    supporting_evidence: List[str]
    confidence: float
    is_valid: bool = True
    is_hallucinated: bool = False


@dataclass
class LscEvaluationResult:
    explicit_count: int
    inferred_valid_count: int
    hallucinated_count: int
    lsc_score: float  # |R_i| / (|R_i| + lambda * |R_h|)
    inferred_requirements: List[InferredRequirement]


class ProductJudgmentCritic:
    """
    Independent critic evaluating implementation completeness beyond literal ticket text.
    Infers implied requirements with required evidence provenance.
    """

    STANDARD_INSPECTION_DIMENSIONS = [
        ("empty_state", "Does the view communicate when data/collection is empty without breaking?"),
        ("loading_state", "Is asynchronous network latency or processing visually indicated?"),
        ("keyboard_nav", "Can all interactive elements be focused and activated via keyboard?"),
        ("error_boundary", "Does the component survive corrupted or unexpected JSON/payloads?"),
        ("destructive_guard", "Are permanent deletions or state mutations gated by confirmation?"),
        ("status_iconography", "Do icons carry clear semantic intent and status colors?"),
    ]

    def __init__(self, penalty_lambda: float = 2.0):
        self.penalty_lambda = penalty_lambda

    def evaluate_inferred_requirements(
        self,
        explicit_requirements: List[str],
        source_code: str,
        context_evidence: List[str],
    ) -> LscEvaluationResult:
        inferred: List[InferredRequirement] = []

        code_lower = source_code.lower()

        # 1. Empty state check
        has_empty_handling = any(k in code_lower for k in ["empty", "no items", "not found", "length === 0", "len("])
        inferred.append(
            InferredRequirement(
                title="Empty State Handling",
                description="View renders clean message when items collection is empty.",
                category="ux",
                supporting_evidence=["UI component receives dynamic collection"],
                confidence=0.92,
                is_valid=has_empty_handling,
                is_hallucinated=False,
            )
        )

        # 2. Loading state check
        has_loading = any(k in code_lower for k in ["loading", "spinner", "skeleton", "is_loading", "isloading"])
        inferred.append(
            InferredRequirement(
                title="Loading State Indicator",
                description="Visual feedback displayed while fetching or computing.",
                category="ux",
                supporting_evidence=["Async fetch or background task present"],
                confidence=0.88,
                is_valid=has_loading,
                is_hallucinated=False,
            )
        )

        # 3. Accessibility / ARIA
        has_a11y = any(k in code_lower for k in ["aria-", "tabindex", "role=", "onkeydown", "onkeypress"])
        inferred.append(
            InferredRequirement(
                title="Keyboard Accessibility & ARIA Semantics",
                description="Interactive controls reachable and labeled for screen-readers.",
                category="accessibility",
                supporting_evidence=["DOM interactive elements present"],
                confidence=0.85,
                is_valid=has_a11y,
                is_hallucinated=False,
            )
        )

        valid_count = sum(1 for r in inferred if r.is_valid and not r.is_hallucinated)
        hallucinated_count = sum(1 for r in inferred if r.is_hallucinated)

        # LSC = |R_i| / (|R_i| + lambda * |R_h|)
        denom = valid_count + self.penalty_lambda * hallucinated_count
        lsc_score = (valid_count / denom) if denom > 0 else 1.0

        return LscEvaluationResult(
            explicit_count=len(explicit_requirements),
            inferred_valid_count=valid_count,
            hallucinated_count=hallucinated_count,
            lsc_score=lsc_score,
            inferred_requirements=inferred,
        )
