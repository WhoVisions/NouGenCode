"""
Tests for Latent Specification Completion (ProductJudgmentCritic) and NouGenMorphEngine.
"""

from __future__ import annotations

import pytest

from nougencode.critics.product import (
    EvidenceKind, ImplementationCheck, ImplementationStatus,
    ProductEvidence, ProductJudgmentCritic, RequirementProposal,
)
from nougencode.morph.engine import (
    AdoptionState,
    MorphCandidate,
    MorphEvidence,
    MorphKind,
    MorphTestResult,
    MorphVerificationProof,
    NouGenMorphEngine,
)


def test_product_judgment_critic_lsc_score():
    critic = ProductJudgmentCritic(penalty_lambda=2.0)
    proposals = [
        RequirementProposal("empty-state", "Empty state", "Show when no items exist",
                            "ux", "reasoner", ("invariant:collections", "donor:xda")),
        RequirementProposal("dark-mode", "Dark mode", "Add an unrequested theme",
                            "visual", "reasoner", ("missing:theme-evidence",)),
    ]
    res = critic.evaluate_inferred_requirements(
        explicit_requirements=("Render user list",), proposals=proposals,
        evidence=(
            ProductEvidence("invariant:collections", EvidenceKind.PRODUCT_INVARIANT,
                            "The user-facing collection must explain empty state."),
            ProductEvidence("donor:xda", EvidenceKind.DONOR_CLAIM,
                            "A donor article recommended richer UX."),
            ProductEvidence("test:empty-state", EvidenceKind.TEST,
                            "Independent UI test verifies empty-state behavior."),
        ),
        implementation_checks=(ImplementationCheck(
            "empty-state", "independent-ui-check", ImplementationStatus.IMPLEMENTED,
            ("test:empty-state",)),),
    )
    assert res.inferred_valid_count == 1
    assert res.hallucinated_count == 1
    assert res.lsc_score == pytest.approx(1 / 3)
    assert res.implemented_count == 1
    assert res.implementation_coverage == 1.0
    assert res.findings[1].support_issue == "proposal cites evidence absent from the context bundle"


def test_product_judgment_rejects_self_review_and_donor_only_evidence():
    critic = ProductJudgmentCritic()
    proposal = RequirementProposal("loading", "Loading", "Show busy state", "ux",
                                   "same-agent", ("donor:article",))
    result = critic.evaluate_inferred_requirements(
        explicit_requirements=(), proposals=(proposal,),
        evidence=(ProductEvidence("donor:article", EvidenceKind.DONOR_CLAIM,
                                  "An article mentioned loading states."),),
        implementation_checks=(ImplementationCheck(
            "loading", "same-agent", ImplementationStatus.IMPLEMENTED,
            ("donor:article",)),),
    )
    finding = result.findings[0]
    assert finding.hallucinated
    assert finding.implementation_status is ImplementationStatus.UNKNOWN
    assert finding.verification_issue == "implementation check is not independent"


def test_nougenmorph_scoring_and_adoption_lifecycle():
    engine = NouGenMorphEngine(acceptance_threshold=0.50)

    # High-value donor: Latent Specification Completion from XDA experiment
    high_value_cand = MorphCandidate(
        name="latent_specification_completion",
        kind=MorphKind.BEHAVIOR,
        donor_behavior="Claude Code added useful UX details not explicitly required in ticket.",
        generalized_behavior="Perform evidence-constrained review for implied requirements.",
        nougen_target="NouGenCode.critics.product.ProductJudgmentCritic",
        evidence=[MorphEvidence(source_uri="https://www.xda-developers.com/claude-code-codex-cursor-same-web-app-build-one-worked-senior-developer/", claim="The comparison reports different strengths across execution, visual coherence, and product judgment.", confidence=0.95, provenance="attachment:2bf30ca7-8186-4a11-8609-5195c88c1fc6")],
        usefulness=0.96,
        generalizability=0.98,
        verifiability=0.85,
        compatibility=0.95,
        reversibility=0.98,
        integration_cost=0.05,
        proposer_id="source-reviewer",
    )

    # MorphScore = 0.96 * 0.98 * 0.85 * 0.95 * 0.98 - 0.05 = ~0.70 (> 0.50)
    accepted = engine.register_candidate(high_value_cand)
    assert accepted is True
    assert high_value_cand.state == AdoptionState.CANDIDATE

    assert not engine.promote_to_adopted("latent_specification_completion", "pytest 100% green")
    assert engine.record_test_result(
        "latent_specification_completion",
        MorphTestResult("fixture:lsc-evidence", True, "artifact:result-sha256"),
    )
    proof = MorphVerificationProof(
        candidate_digest=high_value_cand.digest(),
        verifier_id="independent-reviewer",
        test_ids=("fixture:lsc-evidence",),
        evidence_refs=("artifact:result-sha256", "source:article"),
        proof_ref="proof:sha256:verified",
        passed=True,
    )
    assert engine.verify_candidate("latent_specification_completion", proof)
    promoted = engine.promote_to_adopted("latent_specification_completion", proof)
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


def test_morph_adoption_requires_source_provenance_independent_test_and_verifier():
    engine = NouGenMorphEngine(acceptance_threshold=.5)
    candidate = MorphCandidate(
        name="evidence_bound_product_review", kind=MorphKind.ALGORITHM,
        donor_behavior="A donor behavior", generalized_behavior="A vendor-neutral behavior",
        nougen_target="NouGenCode.critics.product", proposer_id="builder",
        evidence=[MorphEvidence("doc:1", "A claim", .9)],
        usefulness=.9, generalizability=.9, verifiability=.9,
        compatibility=.9, reversibility=.9, integration_cost=.01,
    )
    assert not engine.register_candidate(candidate)
    assert candidate.state is AdoptionState.QUARANTINED

    candidate.evidence[0] = MorphEvidence("doc:1", "A claim", .9, "fixture:source")
    assert engine.register_candidate(candidate)
    assert engine.record_test_result("evidence_bound_product_review",
                                     MorphTestResult("fixture:1", True, "test:sha256"))
    common = dict(candidate_digest=candidate.digest(), test_ids=("fixture:1",),
                  evidence_refs=("test:sha256",), proof_ref="proof:1", passed=True)
    same_author = MorphVerificationProof(verifier_id="builder", **common)
    assert not engine.verify_candidate("evidence_bound_product_review", same_author)
    wrong_candidate = MorphVerificationProof(verifier_id="reviewer",
                                              **{**common, "candidate_digest": "wrong"})
    assert not engine.verify_candidate("evidence_bound_product_review", wrong_candidate)
    verified = MorphVerificationProof(verifier_id="reviewer", **common)
    assert engine.verify_candidate("evidence_bound_product_review", verified)
    assert engine.promote_to_adopted("evidence_bound_product_review", verified)


def test_failed_morph_test_quarantines_candidate():
    engine = NouGenMorphEngine(acceptance_threshold=.5)
    candidate = MorphCandidate(
        name="candidate", kind=MorphKind.PATTERN, donor_behavior="donor",
        generalized_behavior="generic", nougen_target="NouGenCode",
        evidence=[MorphEvidence("source", "claim", .8, "run:1")],
        usefulness=.9, generalizability=.9, verifiability=.9,
        compatibility=.9, reversibility=.9, integration_cost=.01,
        proposer_id="extractor",
    )
    assert engine.register_candidate(candidate)
    assert not engine.record_test_result("candidate", MorphTestResult("fixture:broken", False, "log:1"))
    assert candidate.state is AdoptionState.QUARANTINED
