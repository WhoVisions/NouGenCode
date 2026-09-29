"""Unit tests for the NouGenCode Universal Control Plane MVP."""

import asyncio
from typing import Any, Dict
import pytest

from nougencode.arbitration.arbiter import Claim, EvidenceArbiter
from nougencode.controller import NouGenCodeController
from nougencode.core.mission import (
    Capability,
    Intent,
    MutationBudget,
    RuntimeIdentity,
    TaskNode,
)
from nougencode.routing.switchboard import (
    CodeProvider,
    ExecutionStatus,
    ProviderResult,
    Switchboard,
)
from nougencode.validation.test_ladder import TestLadder, TestLevel


class MockCodeProvider(CodeProvider):
    """Deterministic mock provider for testing role routing and calibration."""

    def __init__(self, provider_id: str, supported_caps: list[Capability], default_status: ExecutionStatus = ExecutionStatus.PASS) -> None:
        super().__init__(provider_id=provider_id, model_id="mock-v1")
        self.supported_caps = supported_caps
        self.default_status = default_status

    def declares_capability(self, capability: Capability) -> bool:
        return capability in self.supported_caps

    async def execute(self, task: TaskNode, context: Dict[str, Any]) -> ProviderResult:
        return ProviderResult(
            status=self.default_status,
            output="Executed mock successfully",
            mutations=[{"file": f, "status": "modified"} for f in task.files_expected],
            latency_ms=12,
            tokens_used=42,
        )


def test_runtime_identity_neutrality():
    """Verify runtime identity is tenant neutral and dynamically resolved."""
    identity = RuntimeIdentity(
        tenant_id="tenant_alpha",
        workspace_id="ws_01",
        machine_id="node_blade",
        repo_id="repo_nougencode",
        session_id="sess_xyz",
    )
    assert identity.tenant_id == "tenant_alpha"
    assert identity.repo_id == "repo_nougencode"


def test_switchboard_role_decoupling_and_competence():
    """Verify Role != Provider and competency alpha/beta updates."""
    sb = Switchboard()
    p1 = MockCodeProvider("provider_a", [Capability.DEBUGGING])
    p2 = MockCodeProvider("provider_b", [Capability.DEBUGGING])
    sb.register_provider(p1)
    sb.register_provider(p2)

    task = TaskNode(id="t1", objective="fix bug", capability=Capability.DEBUGGING)

    # Initial equal competence
    chosen = sb.resolve(Capability.DEBUGGING, task)
    assert chosen is not None

    # Bias p2 with successes
    sb.record_competence("provider_b", Capability.DEBUGGING, True)
    sb.record_competence("provider_b", Capability.DEBUGGING, True)
    assert sb.get_competence("provider_b", Capability.DEBUGGING) > sb.get_competence("provider_a", Capability.DEBUGGING)

    best = sb.resolve(Capability.DEBUGGING, task)
    assert best.provider_id == "provider_b"


def test_mutation_drift_budget():
    """Verify mutation drift formula bounds blast radius."""
    budget = MutationBudget(max_files=2, max_added_lines=50)
    # 1 file, 20 lines -> drift = max(0.5, 0.4) = 0.5 (within budget)
    assert budget.evaluate_drift(1, 20) == 0.5
    # 4 files, 10 lines -> drift = max(2.0, 0.2) = 2.0 (exceeded budget)
    assert budget.evaluate_drift(4, 10) == 2.0


def test_evidence_arbiter_blocking_claims():
    """Verify senior engineering is non-democratic: critical claim blocks shipping."""
    arbiter = EvidenceArbiter()
    critical_claim = Claim(
        id="c1",
        statement="Auth token exposed in logs",
        severity=0.9,
        confidence=0.95,
        evidence=["runtime_reproduction"],
        resolved=False,
    )
    benign_claim = Claim(
        id="c2",
        statement="Missing docstring",
        severity=0.2,
        confidence=0.99,
        evidence=[],
        resolved=False,
    )

    assert not arbiter.evaluate_claims([critical_claim, benign_claim])
    assert arbiter.evaluate_claims([benign_claim])


def test_timeout_is_not_failure():
    """Verify epistemic law: Timeout != Failure (Result = UnknownWithinBudget)."""
    async def _run():
        ladder = TestLadder(repo_root=".", base_timeout_s=0.01)
        res = await ladder.run_targeted_test("tests/test_flow_craft.py", timeout_s=0.0001)
        assert res.timed_out is True
        assert res.status == ExecutionStatus.TIMEOUT
        assert "UnknownWithinBudget" in res.output

    asyncio.run(_run())


def test_full_controller_mission_lifecycle(tmp_path):
    """End-to-end verification of NouGenCode control plane execution."""
    async def _run():
        sb = Switchboard()
        provider = MockCodeProvider("lantern_local", [Capability.IMPLEMENTATION])
        sb.register_provider(provider)

        controller = NouGenCodeController(repo_root=str(tmp_path), switchboard=sb)
        identity = RuntimeIdentity(
            tenant_id="tenant_42",
            workspace_id="ws_main",
            machine_id="node_min",
            repo_id="repo_demo",
            session_id="sess_1",
        )
        intent = Intent(
            goal="Fix argument parsing regression",
            acceptance=["All targeted tests pass"],
            constraints=["Do not modify unrelated modules"],
        )
        task = TaskNode(
            id="task_fix",
            objective="Patch CLI parser",
            capability=Capability.IMPLEMENTATION,
            files_expected=["src/parser.py"],
            mutation_budget=MutationBudget(max_files=1, max_added_lines=20),
        )

        proof = await controller.execute_mission(
            identity=identity,
            intent=intent,
            baseline_commit="commit_abc123",
            tasks=[task],
        )

        assert proof.task_id.startswith("mission_")
        assert proof.result == "verified"
        assert proof.schema == "nougen.code.proof.v1"

    asyncio.run(_run())
