"""Tests for Top .001% Evidence Kernel (EventEnvelope, Coverage, TruthResolver, CadenceLease)."""
import pytest
from nougencode.core.evidence_kernel import (
    EventEnvelope,
    EvidenceState,
    Provenance,
    CoverageEnvelope,
    TruthResolver,
    CadenceLease,
    ProofReceipt,
)

def test_event_envelope_deterministic_canonical_hash():
    p1 = Provenance(source_type="cli", source_id="test", node_id="phoebus", observed_at="2026-09-29T00:00:00Z")
    p2 = Provenance(source_type="cli", source_id="test", node_id="phoebus", observed_at="2026-09-29T00:00:00Z")
    
    e1 = EventEnvelope("v1", "test_event", "subject_a", EvidenceState.VERIFIED, {"k": "v"}, p1, "corr_1")
    e2 = EventEnvelope("v1", "test_event", "subject_a", EvidenceState.VERIFIED, {"k": "v"}, p2, "corr_1")
    assert e1.canonical_hash() == e2.canonical_hash()

def test_coverage_envelope_absence_is_provable():
    full = CoverageEnvelope(
        expected_sources=frozenset(["blade", "phoebus", "whoart"]),
        queried_sources=frozenset(["blade", "phoebus", "whoart"]),
        successful_sources=frozenset(["blade", "phoebus", "whoart"]),
        failed_sources=frozenset(),
        timed_out_sources=frozenset()
    )
    assert full.absence_is_provable is True

    partial = CoverageEnvelope(
        expected_sources=frozenset(["blade", "phoebus", "whoart"]),
        queried_sources=frozenset(["blade", "phoebus", "whoart"]),
        successful_sources=frozenset(["phoebus", "whoart"]),
        failed_sources=frozenset(),
        timed_out_sources=frozenset(["blade"])
    )
    assert partial.absence_is_provable is False

def test_truth_resolver_returns_unknown_on_incomplete_coverage():
    resolver = TruthResolver()
    partial = CoverageEnvelope(
        expected_sources=frozenset(["node_a", "node_b"]),
        queried_sources=frozenset(["node_a", "node_b"]),
        successful_sources=frozenset(["node_a"]),
        failed_sources=frozenset(["node_b"]),
        timed_out_sources=frozenset()
    )
    decision = resolver.resolve([], partial)
    assert decision.state == EvidenceState.UNKNOWN
    assert decision.confidence == 0.0

def test_cadence_lease_monotonic_fencing():
    lease = CadenceLease()
    ok, f1 = lease.acquire("node_a", ttl_seconds=10)
    assert ok is True
    assert f1 == 1

    ok2, f2 = lease.acquire("node_b", ttl_seconds=10)
    assert ok2 is False
    assert f2 == 1

    # Monotonic mutation validation
    assert lease.validate_mutation(1) is True
    assert lease.validate_mutation(0) is False  # Stale zombie write rejected

def test_proof_receipt_cryptographic_chain():
    r1 = ProofReceipt("m_1019", "in_h", "patch_h", "env_h", "test_h", "dec_h")
    h1 = r1.compute_hash()
    assert len(h1) == 64

    r2 = ProofReceipt("m_1019", "in_h2", "patch_h2", "env_h", "test_h", "dec_h", parent_receipt_hash=h1)
    h2 = r2.compute_hash()
    assert h1 != h2
