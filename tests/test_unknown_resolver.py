"""
Tests for Universal Epistemic Unknown Resolver & Constraint Closure Gate in NouGenCode.
Verifies:
  - Epistemic resolution hierarchy: Lookup > Derive > Observe > Search > Bounded Judgment > Ask Human > Abstain
  - Unknown computational representation and canonical hashing
  - ConstraintClosureGate:
      - Closes when all required unknowns are resolved
      - Blocks execution when required unknowns remain unresolved
      - Dispatches high VOI unknowns to Ask Human
  - Controller integration: rejects execution and emits blocking claim when required unknowns are unresolved
"""

import pytest
from nougencode.arbitration.unknown_resolver import (
    ConstraintClosureGate,
    EpistemicMethod,
    EpistemicRouter,
    Resolution,
    Unknown,
    UnknownState,
)
from nougencode.core.mission import Capability, CodeMission, Intent, RuntimeIdentity, TaskNode
from nougencode.routing.switchboard import CodeProvider, ExecutionStatus, ProviderResult, Switchboard


class DummyProvider(CodeProvider):
    def __init__(self, name: str = "dummy"):
        super().__init__(name, "dummy-model")
        self.name = name

    def declares_capability(self, capability: Capability) -> bool:
        return True

    async def execute(self, task: TaskNode, context: dict) -> ProviderResult:
        return ProviderResult(
            status=ExecutionStatus.PASS,
            output="Done",
            mutations=[{"path": "dummy.py", "lines_added": 1, "lines_deleted": 0}],
        )


def test_unknown_canonical_hash_determinism():
    u1 = Unknown(key="db_port", question="What is the database port?", required=True)
    u2 = Unknown(key="db_port", question="What is the database port?", required=True)
    assert u1.canonical_hash() == u2.canonical_hash()
    assert len(u1.canonical_hash()) == 64


def test_epistemic_router_lookup_resolution():
    router = EpistemicRouter()
    u = Unknown(key="package_manager", question="Which package manager is used?", required=True)
    context = {"package_manager": "bun"}
    res = router.resolve(u, context)
    assert res.state == UnknownState.RESOLVED
    assert res.resolver == EpistemicMethod.LOOKUP
    assert res.value == "bun"
    assert res.exact is True
    assert res.confidence == 1.0


def test_epistemic_router_custom_derive_handler():
    # Mathematical derivation: W = ceil(lambda * S / C)
    def derive_workers(unknown: Unknown, ctx: dict) -> Resolution:
        if unknown.key == "worker_count":
            import math
            lam = ctx.get("requests_per_sec", 100)
            service_time = ctx.get("avg_service_time", 0.05)
            target_util = ctx.get("target_utilization", 0.8)
            workers = math.ceil((lam * service_time) / target_util)
            return Resolution(
                key=unknown.key,
                resolver=EpistemicMethod.DERIVE,
                value=workers,
                state=UnknownState.RESOLVED,
                exact=True,
                confidence=1.0,
                evidence=(f"Formula: ceil({lam} * {service_time} / {target_util}) = {workers}",),
            )
        return None

    router = EpistemicRouter(custom_handlers={EpistemicMethod.DERIVE: derive_workers})
    u = Unknown(
        key="worker_count",
        question="How many workers to allocate?",
        required=True,
        preferred_resolvers=(EpistemicMethod.DERIVE, EpistemicMethod.ASK_HUMAN),
    )
    context = {"requests_per_sec": 200, "avg_service_time": 0.04, "target_utilization": 0.8}
    res = router.resolve(u, context)
    assert res.state == UnknownState.RESOLVED
    assert res.resolver == EpistemicMethod.DERIVE
    assert res.value == 10


def test_constraint_closure_gate_blocks_unresolved():
    gate = ConstraintClosureGate()
    unknowns = [
        Unknown(key="auth_strategy", question="What auth strategy to use?", required=True, criticality=0.9),
    ]
    result = gate.evaluate(unknowns, context={})
    assert not result.closed
    assert len(result.blockers) == 1
    assert result.blockers[0].key == "auth_strategy"
    assert result.resolutions["auth_strategy"].resolver == EpistemicMethod.ASK_HUMAN


def test_constraint_closure_gate_passes_when_all_resolved():
    gate = ConstraintClosureGate()
    unknowns = [
        Unknown(key="target_env", question="What is target environment?", required=True),
        Unknown(key="optional_color", question="Button color?", required=False, criticality=0.1),
    ]
    context = {"target_env": "production"}
    result = gate.evaluate(unknowns, context=context)
    assert result.closed
    assert len(result.blockers) == 0
    assert result.resolutions["target_env"].state == UnknownState.RESOLVED


def test_controller_constraint_closure_gate_blocks_execution(tmp_path):
    async def _run():
        import sys
        from nougencode.controller import NouGenCodeController

        repo_dir = str(tmp_path)
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        (src_dir / "main.py").write_text("print('hello')", encoding="utf-8")

        switchboard = Switchboard()
        switchboard.register_provider(DummyProvider("dummy"))

        controller = NouGenCodeController(repo_root=repo_dir, switchboard=switchboard)
        identity = RuntimeIdentity(
            tenant_id="t1", workspace_id="w1", machine_id="m1", repo_id="r1", session_id="s1"
        )
        # Intent with unresolved required unknown
        intent = Intent(
            goal="Add user authentication",
            acceptance=["auth works"],
            unknowns=[Unknown(key="jwt_secret_source", question="Where does secret come from?", required=True, criticality=0.9)],
        )
        task = TaskNode(id="t1", objective="Implement auth", capability=Capability.IMPLEMENTATION)

        proof = await controller.execute_mission(identity=identity, intent=intent, tasks=[task])

        # Must be rejected because constraint closure gate caught unresolved critical unknown
        assert proof.result == "rejected"
        assert "constraint_closure" in proof.validation
        assert "c_constraint_closure" in proof.unresolved_claims

    import asyncio
    asyncio.run(_run())
