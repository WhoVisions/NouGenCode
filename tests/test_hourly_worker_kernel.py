"""Unit tests for the elevated NouGenCode Hourly Worker Control-Plane Kernel."""

import asyncio
from datetime import datetime, timezone
import pytest

from nougencode.core.golden_slice import (
    CoverageEnvelope,
    EvidenceObservation,
    MutationBudget,
    StaleFenceRejected,
    TaskNode,
    TruthStatus,
)
from nougencode.core.mission import Capability
from nougencode.hourly_worker import (
    A2APeerMessage,
    CadenceScheduler,
    DeadLetterQueue,
    DeltaEngine,
    GenAIAdapterSpec,
    HourlyWorkerKernel,
    MCPGatewayAdapter,
    MCPRequest,
    OTelContext,
    QueueIngressAdapter,
    QueueMessage,
    RobustCadenceTTL,
    TenantDOCoordinator,
    VerificationEngine,
    WorkflowDurableExecutor,
    WorkflowStep,
)

AS_OF = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)
OBSERVED_AT = "2026-09-29T15:59:30Z"


def make_evidence(
    source_id: str,
    observation_id: str,
    value: bool = True,
    *,
    status: str = "OBSERVED",
    observed_at: str = OBSERVED_AT,
    ttl: float = 3600.0,
    elapsed: float = None,
    budget: float = None,
) -> EvidenceObservation:
    fields = dict(
        observation_id=observation_id,
        source_id=source_id,
        provenance=f"runtime:{source_id}",
        value=value if status == "OBSERVED" else None,
        status=status,
        observed_at=observed_at,
        freshness_ttl_seconds=ttl,
    )
    if elapsed is not None:
        fields["elapsed_seconds"] = elapsed
    if budget is not None:
        fields["budget_seconds"] = budget
    return EvidenceObservation(**fields)


def make_task() -> TaskNode:
    return TaskNode(
        id="hourly-kernel-task",
        objective="run elevated hourly worker loop",
        capability=Capability.IMPLEMENTATION,
        files_expected=["src/module.py"],
        mutation_budget=MutationBudget(max_files=1, max_added_lines=10, max_deleted_lines=10),
    )


# --- 1. Cadence & Robust TTL Tests ---

def test_robust_cadence_ttl_evaluates_freshness_and_expiry():
    ttl = RobustCadenceTTL(base_ttl_seconds=120.0, grace_period_seconds=30.0)
    fresh_obs = make_evidence("s1", "o1", observed_at="2026-09-29T15:59:00Z", ttl=120.0)
    is_fresh, reason = ttl.evaluate_observation(fresh_obs, AS_OF)
    assert is_fresh is True
    assert reason == "fresh"

    stale_obs = make_evidence("s1", "o2", observed_at="2026-09-29T15:57:30Z", ttl=120.0)
    is_fresh, reason = ttl.evaluate_observation(stale_obs, AS_OF)
    assert is_fresh is False
    assert reason == "stale_in_grace_period"

    expired_obs = make_evidence("s1", "o3", observed_at="2026-09-29T15:50:00Z", ttl=120.0)
    is_fresh, reason = ttl.evaluate_observation(expired_obs, AS_OF)
    assert is_fresh is False
    assert reason == "expired"


def test_robust_cadence_ttl_protects_against_clock_skew():
    ttl = RobustCadenceTTL(max_clock_skew_seconds=60.0)
    # 5 minutes into the future -> beyond allowed clock skew
    future_obs = make_evidence("s1", "o4", observed_at="2026-09-29T16:05:00Z")
    is_fresh, reason = ttl.evaluate_observation(future_obs, AS_OF)
    assert is_fresh is False
    assert reason == "future_dated_beyond_skew"


def test_robust_cadence_ttl_timeout_within_budget():
    ttl = RobustCadenceTTL()
    timeout_ok = make_evidence("s1", "o5", status="TIMED_OUT", elapsed=2.0, budget=5.0)
    is_valid, reason = ttl.evaluate_observation(timeout_ok, AS_OF)
    assert is_valid is True
    assert reason == "timed_out_within_budget"

    timeout_exceeded = make_evidence("s1", "o6", status="TIMED_OUT", elapsed=10.0, budget=5.0)
    is_valid, reason = ttl.evaluate_observation(timeout_exceeded, AS_OF)
    assert is_valid is False
    assert reason == "timed_out_exceeded_budget"


def test_cadence_scheduler_backoff_and_tick_generation():
    scheduler = CadenceScheduler(interval_seconds=3600.0, min_backoff_seconds=10.0, max_backoff_seconds=100.0)
    tick = scheduler.create_tick(AS_OF)
    assert tick.cycle_number == 0
    assert tick.is_within_drift_budget(AS_OF)

    # Success maintains full interval
    assert scheduler.next_interval(success=True) == 3600.0

    # Failures back off exponentially
    b1 = scheduler.next_interval(success=False)
    b2 = scheduler.next_interval(success=False)
    b3 = scheduler.next_interval(success=False)
    assert b1 == 10.0
    assert b2 == 20.0
    assert b3 == 40.0


# --- 2. Material DeltaEngine Tests ---

def test_delta_engine_distinguishes_material_and_noop_changes():
    prev = {"truth_status": "PASS", "decision_action": "ROUTE", "count": 10}
    same = {"truth_status": "PASS", "decision_action": "ROUTE", "count": 10}
    noop_delta = DeltaEngine.compute_state_delta(prev, same)
    assert noop_delta.is_material is False

    modified = {"truth_status": "FAIL", "decision_action": "AVOID", "count": 12}
    mat_delta = DeltaEngine.compute_state_delta(prev, modified)
    assert mat_delta.is_material is True
    assert mat_delta.truth_transition == ("PASS", "FAIL")
    assert "count" in mat_delta.modified_keys


def test_delta_engine_handles_evidence_deltas():
    cov1 = CoverageEnvelope(("s1",), (make_evidence("s1", "e1", True),))
    cov2 = CoverageEnvelope(("s1", "s2"), (make_evidence("s1", "e1", True), make_evidence("s2", "e2", True)))
    delta = DeltaEngine.compute_evidence_delta(cov1, cov2)
    assert delta.is_material is True
    assert "e2" in delta.added_keys


# --- 3. Cloudflare Adapter Stack Tests ---

def test_tenant_do_coordinator_monotonic_fencing_and_idempotency():
    coordinator = TenantDOCoordinator(tenant_id="tenant_x")
    assert coordinator.current_fence == 0

    # Acquire fence 10
    f1 = coordinator.acquire_fence(10)
    assert f1 == 10
    assert coordinator.current_fence == 10

    # Regressive fence is rejected
    with pytest.raises(StaleFenceRejected):
        coordinator.acquire_fence(5)

    # Monotonic mutation
    applied, state = coordinator.mutate_state(
        fence_token=10,
        idempotency_key="mutation_1",
        mutation_fn=lambda s: {**s, "active": True},
    )
    assert applied is True
    assert state["active"] is True

    # Same idempotency key returns False (idempotent no-op)
    applied_again, state_again = coordinator.mutate_state(
        fence_token=10,
        idempotency_key="mutation_1",
        mutation_fn=lambda s: {**s, "active": False},
    )
    assert applied_again is False
    assert state_again["active"] is True


def test_queue_ingress_and_dlq_quarantine():
    dlq = DeadLetterQueue()
    ingress = QueueIngressAdapter(dlq=dlq, max_attempts=2)

    msg_ok = QueueMessage(id="msg_1", body={"action": "tick"}, timestamp="2026-09-29T16:00:00Z", attempts=1)
    msg_fail = QueueMessage(id="msg_2", body={"action": "poison"}, timestamp="2026-09-29T16:00:00Z", attempts=2)

    def handler(msg: QueueMessage) -> bool:
        if msg.id == "msg_1":
            return True
        return False

    success, failed = ingress.process_batch([msg_ok, msg_fail], handler)
    assert "msg_1" in success
    assert "msg_2" in failed
    assert dlq.count() == 1
    assert dlq.list_records()[0].message_id == "msg_2"


def test_workflow_durable_executor_memoization():
    executor = WorkflowDurableExecutor()
    call_counts = {"step_1": 0}

    async def step_action(ctx):
        call_counts["step_1"] += 1
        return "result_ok"

    step = WorkflowStep(name="step_1", action=step_action)

    async def _run():
        res1 = await executor.run_step("wf_123", step, {})
        res2 = await executor.run_step("wf_123", step, {})
        assert res1 == res2 == "result_ok"
        # Should be called only once due to memoization
        assert call_counts["step_1"] == 1

    asyncio.run(_run())


# --- 4. MCP Gateway (2026-07-28 & OTel 1.44) Tests ---

def test_mcp_gateway_otel_propagation_and_mrtr():
    gw = MCPGatewayAdapter()
    req = MCPRequest(
        method="tools/call",
        params={"name": "inspect_code", "arguments": {"path": "src/module.py"}},
        headers={
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "x-nougen-tenant": "tenant_prod",
            "x-nougen-route": "worker_lane",
        },
    )
    assert req.tenant_id == "tenant_prod"
    assert req.otel.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"

    routed = gw.route_mcp_request(req)
    assert routed["status"] == "routed"
    assert routed["tenant"] == "tenant_prod"
    assert routed["tool"] == "inspect_code"


def test_mcp_gateway_horizontal_a2a_preservation():
    gw = MCPGatewayAdapter()
    peer_msg = A2APeerMessage(
        sender_agent_id="agent_alpha",
        recipient_agent_id="agent_beta",
        peer_tier="horizontal_worker",
        payload={"query": "evidence_check"},
        is_horizontal=True,
    )
    assert gw.send_horizontal_a2a(peer_msg) is True

    with pytest.raises(ValueError, match="horizontal peer agents"):
        A2APeerMessage(
            sender_agent_id="agent_alpha",
            recipient_agent_id="agent_beta",
            peer_tier="hierarchical_master",
            payload={"cmd": "reboot"},
            is_horizontal=False,
        )


def test_versioned_genai_adapters():
    spec_v1 = GenAIAdapterSpec(
        adapter_id="ollama-v1",
        version="1.2.0",
        model_family="gemma4",
        capabilities=("code", "review"),
    )
    assert spec_v1.is_compatible("1.0.0") is True
    assert spec_v1.is_compatible("2.0.0") is False


# --- 5. End-to-End Hourly Worker Kernel Tests ---

def test_hourly_worker_kernel_full_cycle_and_verification_receipt():
    kernel = HourlyWorkerKernel(tenant_id="tenant_hourly_alpha")
    task = make_task()
    coverage = CoverageEnvelope(("provider-a@node-one",), (make_evidence("provider-a@node-one", "ev-1"),))

    async def _run():
        result = await kernel.execute_cycle(
            task=task,
            coverage=coverage,
            fence_token=1,
            idempotency_key="cycle_1_idemp",
            as_of=AS_OF,
        )

        assert result.tenant_id == "tenant_hourly_alpha"
        assert result.fence_token == 1
        assert result.truth.status == TruthStatus.PASS
        assert result.decision_action == "ROUTE"
        assert result.delta.is_material is True
        assert len(result.emitted_events) == 1

        # Check Verification Receipt
        rcpt = result.verification_receipt
        assert rcpt.is_verified is True
        assert rcpt.tenant_id == "tenant_hourly_alpha"
        assert len(rcpt.payload_sha256) == 64

        # Verify receipt payload sha256 independently
        assert VerificationEngine.verify_receipt(rcpt, result.emitted_events[0].to_dict()) is True

        # Second cycle with regressive fence fails
        with pytest.raises(StaleFenceRejected):
            await kernel.execute_cycle(
                task=task,
                coverage=coverage,
                fence_token=1,  # Not strictly monotonic (> 1 required)
                idempotency_key="cycle_2_idemp",
                as_of=AS_OF,
            )

        # Second cycle with monotonic fence succeeds
        result_2 = await kernel.execute_cycle(
            task=task,
            coverage=coverage,
            fence_token=2,
            idempotency_key="cycle_2_idemp",
            as_of=AS_OF,
        )
        assert result_2.fence_token == 2
        # State didn't change materially so is_material should be False
        assert result_2.delta.is_material is False

    asyncio.run(_run())
