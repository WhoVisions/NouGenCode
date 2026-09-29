"""Unit tests for TenantCoordinator, Monotonic Fencing, DLQ, and Authority Arbitration."""

import time
from datetime import datetime, timezone
import pytest
from nougencode.core.coordinator import (
    AuthorityArbitrationResult,
    AuthorityArbitrator,
    MonotonicFenceToken,
    QueueItem,
    ResolutionState,
    TenantCoordinator,
    WorkflowPhase,
)
from nougencode.core.evidence_kernel import (
    CoverageEnvelope,
    EventEnvelope,
    EvidenceState,
    Provenance,
)


def test_monotonic_fencing_rejects_zombie_mutations():
    coord = TenantCoordinator(tenant_id="tenant_alpha")
    token1 = coord.advance_fence(node_id="worker_01")
    assert token1.fence_counter == 1

    # Valid under current fence
    ok, err = coord.validate_fence(token1)
    assert ok
    assert err is None

    # Another worker advances fence
    token2 = coord.advance_fence(node_id="worker_02")
    assert token2.fence_counter == 2

    # Old worker (token1) is now a zombie and must be rejected
    ok, err = coord.validate_fence(token1)
    assert not ok
    assert "Zombie fence violation" in err

    # New worker (token2) is valid
    ok, err = coord.validate_fence(token2)
    assert ok


def test_queue_ingress_and_dlq_on_repeated_failure():
    coord = TenantCoordinator(tenant_id="tenant_beta")
    token = coord.advance_fence("worker_01")
    item = coord.enqueue({"task": "hourly_harvest"}, idempotency_key="key_123")

    def failing_executor(q_item):
        return False

    # Attempt 1 -> failure, retried (attempt count 2)
    ok, retried_item, msg = coord.process_queue_step(token, failing_executor)
    assert not ok
    assert retried_item.attempt_count == 2
    assert len(coord.dlq) == 0

    # Attempt 2 -> failure, retried (attempt count 3)
    ok, retried_item, msg = coord.process_queue_step(token, failing_executor)
    assert not ok
    assert retried_item.attempt_count == 3
    assert len(coord.dlq) == 0

    # Attempt 3 -> failure, exhausted -> routed to DLQ
    ok, dead_item, msg = coord.process_queue_step(token, failing_executor)
    assert not ok
    assert "routed to DLQ" in msg
    assert len(coord.dlq) == 1
    assert coord.current_phase == WorkflowPhase.DLQ


def test_authority_arbitration_high_authority_outweighs_unauthenticated_probes():
    now_iso = datetime.now(timezone.utc).isoformat()
    # 1 authenticated end-to-end probe with authority 100
    strong_obs = EventEnvelope(
        schema_version="1.0",
        event_type="heartbeat",
        subject="hourly_worker",
        state=EvidenceState.VERIFIED,
        payload={"metrics": "ok"},
        provenance=Provenance("agent_probe", "phoebus", authority=100, observed_at=now_iso),
        correlation_id="corr_01",
    )
    # 3 unauthenticated weak observers reporting CONFLICT with authority 0
    weak_obs = [
        EventEnvelope(
            schema_version="1.0",
            event_type="heartbeat",
            subject="hourly_worker",
            state=EvidenceState.CONFLICT,
            payload={},
            provenance=Provenance("unauth_ping", f"peer_{i}", authority=0, observed_at=now_iso),
            correlation_id=f"corr_{i}",
        )
        for i in range(3)
    ]

    coverage = CoverageEnvelope(
        expected_sources=frozenset(["phoebus", "peer_0", "peer_1", "peer_2"]),
        queried_sources=frozenset(["phoebus", "peer_0", "peer_1", "peer_2"]),
        successful_sources=frozenset(["phoebus", "peer_0", "peer_1", "peer_2"]),
        failed_sources=frozenset(),
        timed_out_sources=frozenset(),
    )

    result = AuthorityArbitrator.arbitrate([strong_obs, *weak_obs], coverage)
    # The authenticated probe weight is ~101, weak ones ~1 each (total ~104) -> consensus ~97%
    assert result.winning_state == ResolutionState.VERIFIED
    assert result.consensus_ratio > 0.90
    assert "Authority consensus achieved" in result.reasons[0]


def test_unknown_within_budget_when_coverage_incomplete():
    coverage = CoverageEnvelope(
        expected_sources=frozenset(["node1", "node2"]),
        queried_sources=frozenset(["node1", "node2"]),
        successful_sources=frozenset(["node1"]),
        failed_sources=frozenset(["node2"]),
        timed_out_sources=frozenset(),
    )
    result = AuthorityArbitrator.arbitrate([], coverage)
    assert result.winning_state == ResolutionState.UNKNOWN_WITHIN_BUDGET
    assert "absence cannot be inferred" in result.reasons[0]
