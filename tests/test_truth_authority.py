from nougencode.core.evidence_kernel import (
    CoverageEnvelope, EventEnvelope, EvidenceState, Provenance, TruthResolver,
)


def obs(state, authority, i):
    return EventEnvelope(
        schema_version="v1", event_type="probe", subject="shards", state=state,
        payload={"i": i}, provenance=Provenance("probe", f"src{i}", authority=authority),
        correlation_id="c",
    )


def cov(n):
    s = frozenset(f"src{i}" for i in range(n))
    return CoverageEnvelope(s, s, s, frozenset(), frozenset())


def test_one_authoritative_probe_beats_ten_weak_observers():
    weak = [obs(EvidenceState.UNKNOWN, 10, i) for i in range(10)]
    strong = obs(EvidenceState.VERIFIED, 100, 10)
    d = TruthResolver().resolve(weak + [strong], cov(11))
    assert d.state is EvidenceState.VERIFIED
    assert any("outranked" in r for r in d.reasons)


def test_equal_authority_disagreement_is_still_conflict():
    d = TruthResolver().resolve(
        [obs(EvidenceState.VERIFIED, 50, 0), obs(EvidenceState.UNKNOWN, 50, 1)], cov(2))
    assert d.state is EvidenceState.CONFLICT


def test_default_authority_keeps_old_behaviour():
    d = TruthResolver().resolve(
        [obs(EvidenceState.VERIFIED, 0, 0), obs(EvidenceState.UNKNOWN, 0, 1)], cov(2))
    assert d.state is EvidenceState.CONFLICT


def test_stale_authoritative_source_does_not_outrank():
    d = TruthResolver().resolve(
        [obs(EvidenceState.STALE, 100, 0), obs(EvidenceState.VERIFIED, 10, 1)], cov(2))
    assert d.state is EvidenceState.VERIFIED
