"""Comprehensive test suite for NouGenCode Change Fabric components."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest

from nougencode.fabric import (
    ChangeContract,
    FunctionalRequirement,
    ReviewConstraint,
    ContextBroker,
    ContextItem,
    CoherenceReport,
    ChangeFabricEngine,
    ChangeFabricExecutionResult,
    HookABIAdapter,
    HookPhase,
    HookContext,
    HookExecutionResult,
    PostflightOutbox,
    OutboxRecord,
    ContextualProviderUCB,
    ProviderArm,
    RouteDecision,
    ShadowPolicyReplayer,
    PolicyRule,
    ExecutionTrace,
    ReplayReport,
    OTelTelemetryTracer,
    TelemetrySpan,
    OTEL_GENERAL_SEMCONV_VERSION,
    OTEL_GENAI_SEMCONV_VERSION,
    InformationGainTestSelector,
    TestMetadata,
    SelectedTest,
)


# ==============================================================================
# 1. ContextBroker & Coherence Debt Gating Tests
# ==============================================================================

def test_context_broker_retrieval_and_coherence_debt():
    broker = ContextBroker(debt_threshold=0.30, default_ttl_seconds=100.0)
    now = datetime.now(timezone.utc)

    # Register mock adapters
    broker.register_adapter("vault", lambda q: [
        ContextItem(
            item_id="v1",
            source="vault",
            content="Architecture spec v2",
            confidence=0.95,
            observed_at=now.isoformat(),
            freshness_ttl_seconds=120.0,
            claims=("USE_ASYNC", "PORT_8765"),
            references=("v2",),
            status="OBSERVED",
        ),
        ContextItem(
            item_id="v2",
            source="vault",
            content="Dependency lock",
            confidence=0.90,
            observed_at=now.isoformat(),
            freshness_ttl_seconds=120.0,
            claims=(),
            references=(),
            status="OBSERVED",
        )
    ])

    items = broker.retrieve_ensemble("architecture")
    assert len(items) == 2

    # Fresh, consistent context -> admitted
    report = broker.evaluate_coherence(items, as_of=now)
    assert report.is_admitted is True
    assert report.coherence_debt_score == 0.0
    assert len(report.admitted_items) == 2


def test_context_broker_contradiction_and_staleness_gating():
    broker = ContextBroker(debt_threshold=0.25, default_ttl_seconds=100.0)
    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(seconds=500)).isoformat()

    items = [
        ContextItem(
            item_id="item_fresh",
            source="shards",
            content="Enable feature X",
            confidence=0.9,
            observed_at=now.isoformat(),
            freshness_ttl_seconds=60.0,
            claims=("ENABLE_FEATURE_X",),
            status="OBSERVED",
        ),
        ContextItem(
            item_id="item_contradict",
            source="local_config",
            content="Disable feature X",
            confidence=0.8,
            observed_at=now.isoformat(),
            freshness_ttl_seconds=60.0,
            claims=("NOT ENABLE_FEATURE_X",),
            status="OBSERVED",
        ),
        ContextItem(
            item_id="item_stale",
            source="cache",
            content="Old setting",
            confidence=0.5,
            observed_at=stale_time,
            freshness_ttl_seconds=60.0,
            status="OBSERVED",
        ),
    ]

    report = broker.evaluate_coherence(items, as_of=now)
    assert report.is_admitted is False
    assert report.coherence_debt_score > broker.debt_threshold
    assert len(report.contradictions) == 1
    assert len(report.stale_items) == 1
    assert len(report.rejection_reasons) > 0


def test_context_broker_unknown_semantics_and_invalidation():
    broker = ContextBroker()
    
    def failing_adapter(q: str):
        raise RuntimeError("Remote peer unreachable")

    broker.register_adapter("failing_node", failing_adapter)
    items = broker.retrieve_ensemble("test_query")
    assert len(items) == 1
    assert items[0].status == "UNKNOWN"
    assert items[0].confidence == 0.0

    # Invalidation
    broker.invalidate()
    assert len(broker._cache) == 0


# ==============================================================================
# 2. ChangeContract Tests
# ==============================================================================

def test_change_contract_functional_review_separation():
    func_req = FunctionalRequirement(
        req_id="FR-001",
        description="Implement ContextBroker",
        target_artifacts=("src/nougencode/fabric/context_broker.py",),
        invariants=("PRESERVE_UNKNOWN_SEMANTICS",),
        acceptance_tests=("tests/test_change_fabric.py",),
    )
    rev_const = ReviewConstraint(
        constraint_id="RC-001",
        max_mutation_files=5,
        max_mutation_lines=500,
        required_reviewers=("Apollo", "Dave"),
        forbidden_patterns=("os.system(", "eval("),
    )

    contract = ChangeContract(
        contract_id="CC-FABRIC-001",
        title="Deploy Change Fabric",
        functional_requirements=(func_req,),
        review_constraints=rev_const,
    )

    assert contract.fingerprint is not None
    assert len(contract.fingerprint) == 64

    # Valid mutation
    valid, violations = contract.validate_mutation(
        files_touched=["src/a.py", "src/b.py"],
        lines_changed=150,
        diff_text="+ safe_code()",
    )
    assert valid is True
    assert len(violations) == 0

    # Invalid mutation (exceeds file count & contains forbidden pattern)
    invalid, violations = contract.validate_mutation(
        files_touched=["1.py", "2.py", "3.py", "4.py", "5.py", "6.py"],
        lines_changed=600,
        diff_text="+ eval('dangerous')",
    )
    assert invalid is False
    assert len(violations) == 3


# ==============================================================================
# 3. InformationGainTestSelector Tests
# ==============================================================================

def test_information_gain_test_selector():
    selector = InformationGainTestSelector()

    candidates = [
        TestMetadata(
            test_id="test_unit_quick",
            target_files=("src/module_a.py",),
            historical_failure_rate=0.40,
            average_duration_ms=50.0,
            flakiness_score=0.0,
        ),
        TestMetadata(
            test_id="test_slow_e2e",
            target_files=("src/module_b.py",),
            historical_failure_rate=0.05,
            average_duration_ms=10000.0,
            flakiness_score=0.1,
        ),
        TestMetadata(
            test_id="test_flaky",
            target_files=("src/module_a.py",),
            historical_failure_rate=0.50,
            average_duration_ms=100.0,
            flakiness_score=0.9,
        ),
    ]

    # Target modified file module_a
    selected = selector.select_tests(candidates, modified_files=["src/module_a.py"])
    assert len(selected) == 3
    # First ranked test should be test_unit_quick due to file overlap, high failure rate, low duration, zero flakiness
    assert selected[0].test_id == "test_unit_quick"
    assert selected[0].rank == 1
    assert selected[0].information_gain > selected[1].information_gain


# ==============================================================================
# 4. Universal Hook ABI Tests
# ==============================================================================

def test_hook_abi_adapter():
    abi = HookABIAdapter()
    audit_log = []

    def log_preflight(ctx: HookContext):
        audit_log.append(f"PREFLIGHT:{ctx.task_id}")
        return (True, {"enriched": True}, None, False)

    def log_postflight(ctx: HookContext):
        audit_log.append(f"POSTFLIGHT:{ctx.task_id}")
        return (True, None, None, False)

    abi.register(HookPhase.PREFLIGHT, "preflight_logger", log_preflight)
    abi.register(HookPhase.POSTFLIGHT, "postflight_logger", log_postflight)

    payload, results = abi.dispatch(
        phase=HookPhase.PREFLIGHT,
        session_id="sess-001",
        task_id="task-001",
        payload={"base": 1},
    )

    assert payload["enriched"] is True
    assert len(results) == 1
    assert results[0].success is True
    assert audit_log == ["PREFLIGHT:task-001"]


# ==============================================================================
# 5. PostflightOutbox & Hash-Chained Proof Receipts Tests
# ==============================================================================

def test_postflight_outbox_hash_chain_and_idempotency():
    outbox = PostflightOutbox()

    rec1, is_new1 = outbox.append(
        dedup_key="key-001",
        target_channel="relay",
        payload={"task": "deploy", "status": "ok"},
    )
    assert is_new1 is True
    assert rec1.sequence == 0
    assert rec1.previous_hash == "0" * 64

    # Idempotent re-append with same key
    rec1_dup, is_new1_dup = outbox.append(
        dedup_key="key-001",
        target_channel="relay",
        payload={"task": "deploy", "status": "ok"},
    )
    assert is_new1_dup is False
    assert rec1_dup.record_hash == rec1.record_hash

    # Second distinct record -> hash chaining
    rec2, is_new2 = outbox.append(
        dedup_key="key-002",
        target_channel="relay",
        payload={"task": "verify", "status": "pass"},
    )
    assert is_new2 is True
    assert rec2.sequence == 1
    assert rec2.previous_hash == rec1.record_hash

    # Verify entire chain integrity
    valid_chain, err = outbox.verify_chain()
    assert valid_chain is True
    assert err is None

    # Mark delivered
    assert outbox.mark_delivered("key-001") is True
    assert len(outbox.get_pending()) == 1


# ==============================================================================
# 6. Contextual Provider UCB with Safety Lower Bounds Tests
# ==============================================================================

def test_contextual_provider_ucb_with_safety_bounds():
    router = ContextualProviderUCB(safety_floor=0.40, safety_beta=2.0)

    # Local safe arm
    router.register_arm("local_ollama", "solai:latest", is_local=True)
    # Remote risky arm
    router.register_arm("cloud_provider", "frontier-v1", is_local=False)

    # Give cloud provider a few failures to pull down SLB below safety_floor
    router.update("cloud_provider", "frontier-v1", reward=0.1, latency_ms=500.0, success=False)
    router.update("cloud_provider", "frontier-v1", reward=0.1, latency_ms=500.0, success=False)

    # Give local arm high rewards
    router.update("local_ollama", "solai:latest", reward=0.95, latency_ms=80.0, success=True)
    router.update("local_ollama", "solai:latest", reward=0.95, latency_ms=80.0, success=True)

    decision = router.select_route(task_complexity="critical", enforce_safety=True)
    assert decision.selected_provider_id == "local_ollama"
    assert decision.selected_model_id == "solai:latest"
    assert decision.ucb_score > 0.0


# ==============================================================================
# 7. OpenTelemetry SemConv Pinning Tests (General 1.44.0 vs GenAI 1.42.0-dev)
# ==============================================================================

def test_opentelemetry_separate_semconv_pinning():
    tracer = OTelTelemetryTracer(service_name="nougencode-test")

    t_id, s_id, start_perf = tracer.start_mission_span("mission-01", "change_deployment")
    m_span = tracer.record_mission_span(t_id, s_id, "mission-01", "change_deployment", start_perf, success=True)
    assert m_span.semconv_version == OTEL_GENERAL_SEMCONV_VERSION
    assert m_span.attributes["service.name"] == "nougencode-test"

    # Tool span (General 1.44.0)
    t_span = tracer.record_tool_span(t_id, s_id, "ctx_execute", duration_ms=25.0, success=True)
    assert t_span.semconv_version == OTEL_GENERAL_SEMCONV_VERSION
    assert t_span.attributes["tool.name"] == "ctx_execute"

    # GenAI span (GenAI 1.42.0-dev)
    g_span = tracer.record_genai_span(
        trace_id=t_id,
        parent_span_id=s_id,
        system_name="ollama",
        model_name="solai:latest",
        input_tokens=120,
        output_tokens=45,
        duration_ms=180.0,
    )
    assert g_span.semconv_version == OTEL_GENAI_SEMCONV_VERSION
    assert g_span.attributes["gen_ai.system"] == "ollama"
    assert g_span.attributes["gen_ai.request.model"] == "solai:latest"
    assert g_span.attributes["gen_ai.usage.input_tokens"] == 120
    assert g_span.attributes["gen_ai.usage.output_tokens"] == 45


# ==============================================================================
# 8. Shadow Policy Replayer & Rule TTL Tests
# ==============================================================================

def test_shadow_policy_replayer_and_ttl():
    replayer = ShadowPolicyReplayer(max_allowed_divergence=0.10)
    now = datetime.now(timezone.utc)

    # Active valid rule
    replayer.register_shadow_rule(
        PolicyRule(
            rule_id="RULE-MAX-MUTATION",
            version="1.1.0",
            description="Max mutation lines must be <= 300",
            predicate=lambda p: p.get("lines_changed", 0) <= 300,
            created_at=now.isoformat(),
            ttl_seconds=3600.0,
        )
    )

    # Expired rule
    replayer.register_shadow_rule(
        PolicyRule(
            rule_id="RULE-OLD-LEGACY",
            version="0.9.0",
            description="Legacy check",
            predicate=lambda p: True,
            created_at=(now - timedelta(hours=5)).isoformat(),
            ttl_seconds=300.0,
        )
    )

    traces = [
        ExecutionTrace(
            trace_id="tr-1",
            session_id="s1",
            action_name="patch",
            payload={"lines_changed": 100},
            active_policy_verdict=True,
            timestamp=now.isoformat(),
        ),
        ExecutionTrace(
            trace_id="tr-2",
            session_id="s1",
            action_name="patch",
            payload={"lines_changed": 500},
            active_policy_verdict=True,  # Live was True, but shadow will block (divergence)
            timestamp=now.isoformat(),
        ),
    ]

    report = replayer.replay_dataset(traces, as_of=now)
    assert report.total_traces == 2
    assert report.divergent_traces == 1
    assert "RULE-OLD-LEGACY:0.9.0" in report.evaluations[0].expired_rules


# ==============================================================================
# 9. Unified ChangeFabricEngine Integration Test
# ==============================================================================

def test_change_fabric_engine_integration():
    engine = ChangeFabricEngine()

    contract = ChangeContract(
        contract_id="CC-INTEGRATION-001",
        title="Full Change Cycle Integration",
        functional_requirements=(
            FunctionalRequirement(
                req_id="FR-01",
                description="Change Fabric orchestration",
                target_artifacts=("src/nougencode/fabric/engine.py",),
                invariants=("DETERMINISTIC_PROOF",),
                acceptance_tests=("tests/test_change_fabric.py",),
            ),
        ),
        review_constraints=ReviewConstraint(
            constraint_id="RC-01",
            max_mutation_files=10,
            max_mutation_lines=1000,
            required_reviewers=("Apollo",),
            forbidden_patterns=("rm -rf /",),
        ),
    )

    test_candidates = [
        TestMetadata(
            test_id="tests/test_change_fabric.py",
            target_files=("src/nougencode/fabric/engine.py",),
            historical_failure_rate=0.20,
            average_duration_ms=250.0,
        )
    ]

    result = engine.execute_change_cycle(
        session_id="sess-integration-999",
        contract=contract,
        modified_files=["src/nougencode/fabric/engine.py"],
        lines_changed=120,
        diff_text="+ # clean change",
        test_candidates=test_candidates,
    )

    assert result.status == "ACCEPTED"
    assert result.mutation_valid is True
    assert len(result.mutation_violations) == 0
    assert result.coherence_report.is_admitted is True
    assert result.outbox_record.verify_integrity() is True
    assert result.receipt_hash == result.outbox_record.record_hash
    assert len(result.selected_tests) == 1
    assert result.selected_tests[0].test_id == "tests/test_change_fabric.py"
