"""Main controller executing the 12-phase NouGenCode control plane protocol."""

import asyncio
from dataclasses import dataclass
import hashlib
import time
from typing import Any, Dict, List, Optional

from .arbitration.arbiter import Claim, EvidenceArbiter, ProofObject
from .core.mission import (
    Capability,
    CodeMission,
    Intent,
    MissionState,
    MutationBudget,
    RuntimeIdentity,
    TaskNode,
)
from .repo.cartographer import RepoCartographer
from .routing.switchboard import (
    CodeProvider,
    ExecutionStatus,
    ProviderResult,
    Switchboard,
)
from .validation.test_ladder import TestLadder, TestLevel


class NouGenCodeController:
    """Universal, Dynamic, Deterministic Software Engineering Control Plane."""

    def __init__(
        self,
        repo_root: str,
        switchboard: Switchboard,
        arbiter: Optional[EvidenceArbiter] = None,
    ) -> None:
        self.repo_root = repo_root
        self.switchboard = switchboard
        self.arbiter = arbiter or EvidenceArbiter()
        self.cartographer = RepoCartographer(repo_root)
        self.test_ladder = TestLadder(repo_root)

    async def execute_mission(
        self,
        identity: RuntimeIdentity,
        intent: Intent,
        baseline_commit: str = "HEAD",
        tasks: Optional[List[TaskNode]] = None,
    ) -> ProofObject:
        """Transforms Intent -> VerifiedRepositoryState."""
        mission_id = f"mission_{hashlib.sha256(intent.goal.encode()).hexdigest()[:12]}"
        mission = CodeMission(
            mission_id=mission_id,
            identity=identity,
            intent=intent,
            baseline_commit=baseline_commit,
            state=MissionState.RECEIVED,
            task_graph=tasks or [],
        )

        # Phase 1: Context Gate & Phase 2: Cartography
        mission.state = MissionState.MAPPED
        repomap = self.cartographer.inspect_level_0()

        # Phase 3 & 4: Task Planning
        mission.state = MissionState.PLANNED
        validation_results: Dict[str, ExecutionStatus] = {}
        all_claims: List[Claim] = []

        # Execute DAG nodes
        for task in mission.ready_nodes():
            mission.state = MissionState.EXECUTING

            # Phase 7: Switchboard resolution (Role != Provider)
            provider = self.switchboard.resolve(task.capability, task)
            if not provider:
                mission.state = MissionState.BLOCKED
                return self.arbiter.compile_proof(
                    task_id=task.id,
                    baseline_commit=baseline_commit,
                    mutations=[],
                    validation_results={"execution": ExecutionStatus.FAIL},
                    claims=[Claim(id="c_no_provider", statement=f"No provider found for {task.capability}", severity=1.0, confidence=1.0, evidence=["switchboard"])],
                )

            # Bounded execution under Context & Leases
            exec_res = await provider.execute(task, {"repo": repomap.root_path})
            task.completed = (exec_res.status == ExecutionStatus.PASS)

            # Record empirical competency
            self.switchboard.record_competence(
                provider.provider_id, task.capability, task.completed
            )

            # Check mutation budget drift
            if task.mutation_budget:
                files_mutated = len(exec_res.mutations)
                drift = task.mutation_budget.evaluate_drift(files_mutated, 0)
                if drift > 1.0:
                    mission.state = MissionState.NEEDS_REPLAN
                    all_claims.append(
                        Claim(
                            id="c_mutation_drift",
                            statement=f"Mutation drift {drift:.2f} exceeded budget",
                            severity=0.8,
                            confidence=0.95,
                            evidence=["mutation_budget_check"],
                        )
                    )

            # Phase 8: Surgical Test Ladder (L0 Syntax -> L1 Targeted)
            mission.state = MissionState.VALIDATING
            syntax_res = await self.test_ladder.run_syntax_check(task.files_expected)
            validation_results[f"{task.id}_syntax"] = syntax_res.status

            for v_test in task.validation:
                test_res = await self.test_ladder.run_targeted_test(v_test)
                validation_results[f"{task.id}_test_{v_test}"] = test_res.status

        # Phase 9: Arbitration & Proof Object
        mission.state = MissionState.ARBITRATING
        proof = self.arbiter.compile_proof(
            task_id=mission.mission_id,
            baseline_commit=baseline_commit,
            mutations=mission.mutations,
            validation_results=validation_results,
            claims=all_claims,
        )

        mission.state = MissionState.VERIFIED if proof.result == "verified" else MissionState.BLOCKED
        return proof
