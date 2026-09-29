"""Unit tests for NouGen Directives OS Kernel."""

import pytest
from nougencode.core.directives import (
    DirectiveCompiler,
    DirectiveConstraint,
    DirectiveOrchestrator,
    DirectivePlan,
    DirectiveReceipt,
    DirectiveType,
)


def test_compiler_recognizes_core_vocabulary():
    samples = [
        ("shard this execution result into the cluster", DirectiveType.SHARD, "nougenshards"),
        ("relay handoff to blade1tb with current baton", DirectiveType.RELAY, "nougen_relay"),
        ("deep grep the repository for auth tokens", DirectiveType.DEEP_GREP, "code_navigator"),
        ("activate flash kick resilience plane", DirectiveType.FLASH_KICK, "resilience_engine"),
        ("acquire cadence fence lease to prevent zombie mutation", DirectiveType.CADENCE_FENCE, "lease_coordinator"),
        ("generate proof of execution receipt chain", DirectiveType.PROOF_OF_EXECUTION, "evidence_kernel"),
        ("run validation slice against golden slice", DirectiveType.VALIDATION_SLICE, "test_selector"),
        ("syntax heal the incoming python patch", DirectiveType.SYNTAX_HEAL, "syntax_guard"),
        ("dynamic route request using provider ucb bandit", DirectiveType.DYNAMIC_ROUTE, "provider_ucb"),
        ("write a poem about stars", DirectiveType.GENERIC_EXECUTION, "core_executor"),
    ]

    for text, expected_type, expected_subsystem in samples:
        plan = DirectiveCompiler.parse(text)
        assert plan.directive_type == expected_type, f"Failed on '{text}'"
        assert plan.target_subsystem == expected_subsystem
        assert plan.idempotency_key is not None
        assert len(plan.constraints) == 3


def test_plan_hash_is_invariant_and_deterministic():
    text = "shard the architectural decision immediately"
    ctx = {"session_id": "session_phoebus_01", "lane": "phoebus"}
    plan1 = DirectiveCompiler.parse(text, ctx)
    plan2 = DirectiveCompiler.parse(text, ctx)

    assert plan1.compute_plan_hash() == plan2.compute_plan_hash()
    assert plan1.idempotency_key == plan2.idempotency_key


def test_orchestrator_execution_and_receipt():
    plan = DirectiveCompiler.parse("relay task to peer node")
    orchestrator = DirectiveOrchestrator()

    receipt = orchestrator.execute(plan)
    assert receipt.success
    assert receipt.directive_type == DirectiveType.RELAY
    assert receipt.runtime_evidence["dispatched"] is True
    assert len(receipt.output_hash) == 64


def test_orchestrator_custom_handler():
    plan = DirectiveCompiler.parse("shard memory 42")
    orchestrator = DirectiveOrchestrator()

    def mock_shard_handler(p: DirectivePlan):
        return {"sharded_id": 42, "status": "persisted", "bytes": 1024}

    orchestrator.register_handler(DirectiveType.SHARD, mock_shard_handler)
    receipt = orchestrator.execute(plan)

    assert receipt.success
    assert receipt.runtime_evidence["sharded_id"] == 42
    assert receipt.runtime_evidence["status"] == "persisted"
