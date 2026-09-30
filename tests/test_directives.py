"""Unit tests for NouGen Directives OS Kernel."""

from dataclasses import replace

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
        assert {item.name for item in plan.constraints} >= {
            "dispatch_is_not_completion",
            "completion_requires_verification",
        }


def test_plan_hash_is_invariant_and_deterministic():
    text = "shard the architectural decision immediately"
    ctx = {"session_id": "session_phoebus_01", "lane": "phoebus"}
    plan1 = DirectiveCompiler.parse(text, ctx)
    plan2 = DirectiveCompiler.parse(text, ctx)

    assert plan1.compute_plan_hash() == plan2.compute_plan_hash()
    assert plan1.idempotency_key == plan2.idempotency_key


def test_plan_hash_is_stable_across_nested_parameter_mapping_order():
    plan = DirectiveCompiler.parse("shard memory 42")
    first = replace(plan, parameters={**plan.parameters, "metadata": {"db": 1, "shard": 42}})
    second = replace(plan, parameters={**plan.parameters, "metadata": {"shard": 42, "db": 1}})

    assert first.compute_plan_hash() == second.compute_plan_hash()


def test_unconfigured_orchestrator_does_not_claim_dispatch_or_completion():
    plan = DirectiveCompiler.parse("relay task to peer node")
    orchestrator = DirectiveOrchestrator()

    receipt = orchestrator.execute(plan)
    assert not receipt.success
    assert receipt.directive_type == DirectiveType.RELAY
    assert receipt.runtime_evidence["dispatched"] is False
    assert receipt.runtime_evidence["execution_attempted"] is False
    assert receipt.runtime_evidence["status"] == "not_configured"
    assert receipt.runtime_evidence["completion_state"] == "unconfigured"
    assert "no work was performed" in receipt.runtime_evidence["remaining_work"]
    assert len(receipt.output_hash) == 64


def test_handler_return_without_verification_remains_provisional():
    plan = DirectiveCompiler.parse("shard memory 42")
    orchestrator = DirectiveOrchestrator()

    def mock_shard_handler(p: DirectivePlan):
        return {"sharded_id": 42, "status": "persisted", "bytes": 1024}

    orchestrator.register_handler(DirectiveType.SHARD, mock_shard_handler)
    receipt = orchestrator.execute(plan)

    assert not receipt.success
    assert receipt.runtime_evidence["sharded_id"] == 42
    assert receipt.runtime_evidence["status"] == "persisted"
    assert receipt.runtime_evidence["completion_state"] == "unverified"
    assert "verification_method" in receipt.runtime_evidence["remaining_work"]


def test_handler_with_explicit_verification_evidence_can_complete():
    plan = DirectiveCompiler.parse("shard memory 42")
    orchestrator = DirectiveOrchestrator()

    def verified_handler(p: DirectivePlan):
        return {
            "sharded_id": 42,
            "status": "persisted",
            "completed": True,
            "verification_passed": True,
            "verification_method": "read-after-write",
            "evidence_refs": ["shard:db1:42"],
        }

    orchestrator.register_handler(DirectiveType.SHARD, verified_handler)
    receipt = orchestrator.execute(plan)

    assert receipt.success
    assert receipt.runtime_evidence["completion_state"] == "verified"
    assert receipt.runtime_evidence["evidence_refs"] == ["shard:db1:42"]


def test_receipt_hash_is_stable_across_nested_evidence_mapping_order():
    plan = DirectiveCompiler.parse("shard memory 42")
    first = DirectiveOrchestrator(
        {
            DirectiveType.SHARD: lambda _: {
                "completed": True,
                "verification_passed": True,
                "verification_method": "read-after-write",
                "evidence_refs": ["shard:db1:42"],
                "metadata": {"db": 1, "shard": 42},
            }
        }
    ).execute(plan)
    second = DirectiveOrchestrator(
        {
            DirectiveType.SHARD: lambda _: {
                "completed": True,
                "verification_passed": True,
                "verification_method": "read-after-write",
                "evidence_refs": ["shard:db1:42"],
                "metadata": {"shard": 42, "db": 1},
            }
        }
    ).execute(plan)

    assert first.success and second.success
    assert first.output_hash == second.output_hash


def test_receipt_hash_is_bound_to_its_directive_plan():
    orchestrator = DirectiveOrchestrator(
        {
            DirectiveType.SHARD: lambda _: {
                "completed": True,
                "verification_passed": True,
                "verification_method": "read-after-write",
                "evidence_refs": ["shard:db1:42"],
            }
        }
    )
    first = orchestrator.execute(DirectiveCompiler.parse("shard memory 42"))
    second = orchestrator.execute(DirectiveCompiler.parse("shard memory 43"))

    assert first.success and second.success
    assert first.plan_hash != second.plan_hash
    assert first.output_hash != second.output_hash


def test_non_json_handler_evidence_fails_closed_without_serialization_details():
    plan = DirectiveCompiler.parse("shard memory 42")
    orchestrator = DirectiveOrchestrator(
        {
            DirectiveType.SHARD: lambda _: {
                "completed": True,
                "verification_passed": True,
                "verification_method": "read-after-write",
                "evidence_refs": ["shard:db1:42"],
                "metadata": object(),
            }
        }
    )

    receipt = orchestrator.execute(plan)

    assert not receipt.success
    assert receipt.runtime_evidence["status"] == "failed"
    assert receipt.runtime_evidence["error_type"] == "TypeError"
    assert "not JSON serializable" not in repr(receipt)


@pytest.mark.parametrize(
    "overrides",
    [
        {"completed": True},
        {"completed": True, "verification_passed": True},
        {"completed": True, "verification_passed": True, "verification_method": "read-after-write"},
        {
            "completed": True,
            "verification_passed": 1,
            "verification_method": "read-after-write",
            "evidence_refs": ["shard:db1:42"],
        },
        {
            "completed": True,
            "verification_passed": True,
            "verification_method": "read-after-write",
            "evidence_refs": [" "],
        },
    ],
)
def test_incomplete_or_malformed_proof_never_marks_success(overrides):
    plan = DirectiveCompiler.parse("shard memory 42")
    orchestrator = DirectiveOrchestrator()
    orchestrator.register_handler(DirectiveType.SHARD, lambda _: overrides)

    receipt = orchestrator.execute(plan)

    assert not receipt.success
    assert receipt.runtime_evidence["completion_state"] == "unverified"


def test_handler_exception_does_not_copy_raw_diagnostic_into_receipt():
    private_marker = "private provider response: synthetic-secret-marker"
    plan = DirectiveCompiler.parse("relay task to peer node")
    orchestrator = DirectiveOrchestrator()

    def failing_handler(_):
        raise RuntimeError(private_marker)

    orchestrator.register_handler(DirectiveType.RELAY, failing_handler)
    receipt = orchestrator.execute(plan)

    assert not receipt.success
    assert receipt.runtime_evidence["status"] == "failed"
    assert receipt.runtime_evidence["completion_state"] == "failed"
    assert receipt.runtime_evidence["error_type"] == "RuntimeError"
    assert "protected diagnostics" in receipt.runtime_evidence["remaining_work"]
    assert private_marker not in repr(receipt)


@pytest.mark.parametrize(
    "sensitive_key",
    ["error_message", "access_token", "api_key", "private_key"],
)
def test_handler_receipt_redacts_nested_diagnostic_and_credential_fields(sensitive_key):
    private_marker = "synthetic-secret-marker"
    plan = DirectiveCompiler.parse("relay task to peer node")
    orchestrator = DirectiveOrchestrator()
    proof = {
        "completed": True,
        "verification_passed": True,
        "verification_method": "read-after-write",
        "evidence_refs": ["relay:leg:42"],
        "metadata": {sensitive_key: private_marker},
    }
    orchestrator.register_handler(DirectiveType.RELAY, lambda _: proof)

    receipt = orchestrator.execute(plan)

    assert not receipt.success
    assert receipt.runtime_evidence["diagnostic_fields_redacted"] is True
    assert private_marker not in repr(receipt)
    assert sensitive_key not in repr(receipt.runtime_evidence)


@pytest.mark.parametrize(
    "status",
    ["failed", "accepted", "acknowledged", "dispatched", "pending", "queued", "running", "in progress"],
)
def test_non_complete_handler_status_cannot_be_overridden_by_completion_flags(status):
    plan = DirectiveCompiler.parse("relay task to peer node")
    orchestrator = DirectiveOrchestrator()
    orchestrator.register_handler(
        DirectiveType.RELAY,
        lambda _: {
            "status": status,
            "completed": True,
            "verification_passed": True,
            "verification_method": "read-after-write",
            "evidence_refs": ["relay:leg:42"],
        },
    )

    receipt = orchestrator.execute(plan)

    assert not receipt.success
    assert receipt.runtime_evidence["completion_state"] == "unverified"
