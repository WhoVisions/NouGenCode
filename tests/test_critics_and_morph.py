"""
Tests for Latent Specification Completion (ProductJudgmentCritic) and NouGenMorphEngine.
"""

from __future__ import annotations

import pytest

from nougencode.critics.product import ProductJudgmentCritic
from nougencode.morph.engine import (
    AdoptionState,
    MorphCandidate,
    MorphEvidence,
    MorphKind,
    NouGenMorphEngine,
)


def test_product_judgment_critic_lsc_score():
    critic = ProductJudgmentCritic(penalty_lambda=2.0)

    # Complete code implementing empty, loading, and a11y states
    complete_code = """
    function UserList({ users, isLoading }) {
        if (isLoading) return <div role="status">Loading users...</div>;
        if (!users || users.length === 0) return <div>No items found in directory.</div>;
        return (
            <ul aria-label="User Directory">
                {users.map(u => <li key={u.id} tabIndex={0}>{u.name}</li>)}
            </ul>
        );
    }
    """
    res = critic.evaluate_inferred_requirements(
        explicit_requirements=["Render user list"],
        source_code=complete_code,
        context_evidence=["React component"],
    )

    assert res.inferred_valid_count == 3
    assert res.hallucinated_count == 0
    assert res.lsc_score == 1.0


def test_nougenmorph_scoring_and_adoption_lifecycle():
    engine = NouGenMorphEngine(acceptance_threshold=0.50)

    # High-value donor: Latent Specification Completion from XDA experiment
    high_value_cand = MorphCandidate(
        name="latent_specification_completion",
        kind=MorphKind.BEHAVIOR,
        donor_behavior="Claude Code added useful UX details not explicitly required in ticket.",
        generalized_behavior="Perform evidence-constrained review for implied requirements.",
        nougen_target="NouGenCode.critics.product.ProductJudgmentCritic",
        evidence=[MorphEvidence(source_uri="xda_comparison_2026", claim="Improves human UX evaluation", confidence=0.95)],
        usefulness=0.96,
        generalizability=0.98,
        verifiability=0.85,
        compatibility=0.95,
        reversibility=0.98,
        integration_cost=0.05,
    )

    # MorphScore = 0.96 * 0.98 * 0.85 * 0.95 * 0.98 - 0.05 = ~0.70 (> 0.50)
    accepted = engine.register_candidate(high_value_cand)
    assert accepted is True
    assert high_value_cand.state == AdoptionState.CANDIDATE

    promoted = engine.promote_to_adopted("latent_specification_completion", "pytest 100% green")
    assert promoted is True
    assert high_value_cand.state == AdoptionState.ADOPTED

    # Low-value donor (Vendor lock-in: "Hardcode Claude everywhere")
    low_value_cand = MorphCandidate(
        name="hardcode_vendor_claude",
        kind=MorphKind.ANTI_PATTERN,
        donor_behavior="Route 100% of tasks exclusively to Claude brand.",
        generalized_behavior="Vendor lock-in",
        nougen_target="none",
        usefulness=0.20,
        generalizability=0.01,
        verifiability=0.50,
        compatibility=0.10,
        reversibility=0.10,
        integration_cost=0.90,
    )
    # MorphScore negative -> Quarantined
    accepted_low = engine.register_candidate(low_value_cand)
    assert accepted_low is False
    assert low_value_cand.state == AdoptionState.QUARANTINED
