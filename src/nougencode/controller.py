"""Main controller for the provider-neutral NouGenCode mission lifecycle."""

import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .arbitration.arbiter import Claim, EvidenceArbiter, EvidenceReceipt, ProofObject
from .context_gate import ContextGate
from .core.checkpoint import (
    MissionCheckpoint,
    NullPostflightCapture,
    NullTrackerFeedback,
    PostflightCapture,
    TrackerFeedback,
    load_configured_adapters,
)
from .core.fanout import FanoutGovernor
from .core.mission import (
    CodeMission,
    Intent,
    MissionState,
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
from .validation.test_ladder import TestLadder


class NouGenCodeController:
    """Universal, dynamic, deterministic software engineering control plane."""

    def __init__(
        self,
        repo_root: str,
        switchboard: Switchboard,
        arbiter: Optional[EvidenceArbiter] = None,
        *,
        context_gate: Optional[ContextGate] = None,
        fanout_governor: Optional[FanoutGovernor] = None,
        tracker_feedback: Optional[TrackerFeedback] = None,
        postflight_capture: Optional[PostflightCapture] = None,
        provider_timeout_s: float = 120.0,
    ) -> None:
        if provider_timeout_s <= 0:
            raise ValueError("provider_timeout_s must be positive")
        self.repo_root = repo_root
        self.switchboard = switchboard
        self.arbiter = arbiter or EvidenceArbiter()
        self.cartographer = RepoCartographer(repo_root)
        self.test_ladder = TestLadder(repo_root)
        self.context_gate = context_gate or ContextGate()
        self.fanout_governor = fanout_governor or FanoutGovernor()
        configured_tracker, configured_postflight = load_configured_adapters(
            load_tracker=tracker_feedback is None,
            load_postflight=postflight_capture is None,
        )
        self.tracker_feedback = (
            tracker_feedback if tracker_feedback is not None
            else configured_tracker if configured_tracker is not None
            else NullTrackerFeedback()
        )
        self.postflight_capture = (
            postflight_capture if postflight_capture is not None
            else configured_postflight if configured_postflight is not None
            else NullPostflightCapture()
        )
        self._tracker_configured = tracker_feedback is not None or configured_tracker is not None
        self._postflight_configured = postflight_capture is not None or configured_postflight is not None
        self.provider_timeout_s = provider_timeout_s

    @staticmethod
    def _mission_id(identity: RuntimeIdentity, intent: Intent) -> str:
        identity_fields = {
            key: value for key, value in asdict(identity).items()
            if key in {"tenant_id", "workspace_id", "machine_id", "repo_id", "session_id", "branch"}
        }
        digest = hashlib.sha256(
            json.dumps({"identity": identity_fields, "goal": intent.goal}, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        return f"mission_{digest}"

    async def _execute_provider(
        self, provider: CodeProvider, task: TaskNode, context: Dict[str, Any]
    ) -> ProviderResult:
        try:
            return await asyncio.wait_for(
                provider.execute(task, context), timeout=self.provider_timeout_s
            )
        except asyncio.TimeoutError:
            return ProviderResult(
                status=ExecutionStatus.TIMEOUT,
                output="Provider exceeded its execution budget; result is unknown within budget.",
                metadata={"timeout_s": self.provider_timeout_s},
            )
        except Exception as exc:
            return ProviderResult(
                status=ExecutionStatus.INFRA_ERROR,
                output="Provider execution raised an exception.",
                metadata={"exception_type": type(exc).__name__},
            )

    @staticmethod
    def _mutation_counts(mutations: Sequence[Dict[str, Any]]) -> Tuple[int, Optional[int], Optional[int]]:
        paths = {
            str(mutation.get("path") or mutation.get("file"))
            for mutation in mutations
            if mutation.get("path") or mutation.get("file")
        }
        file_count = len(paths) if paths else len(mutations)
        added = 0
        deleted = 0
        for mutation in mutations:
            try:
                if "lines_added" in mutation and "lines_deleted" in mutation:
                    added += max(0, int(mutation["lines_added"]))
                    deleted += max(0, int(mutation["lines_deleted"]))
                elif isinstance(mutation.get("content"), str):
                    added += len(mutation["content"].splitlines())
                    deleted += max(0, int(mutation.get("lines_deleted", 0)))
                else:
                    return file_count, None, None
            except (TypeError, ValueError):
                return file_count, None, None
        return file_count, added, deleted

    def _mutation_scope_violations(self, task: TaskNode, mutations: Sequence[Dict[str, Any]]) -> int:
        """Reject writes outside the checkout or declared mutation roots."""
        root = Path(self.repo_root).resolve()
        allowed = [Path(value).as_posix().strip("/") for value in (task.mutation_budget.allowed_roots if task.mutation_budget else [])]
        forbidden = [Path(value).as_posix().strip("/") for value in (task.mutation_budget.forbidden_roots if task.mutation_budget else [])]
        violations = 0
        for mutation in mutations:
            raw_path = mutation.get("path") or mutation.get("file")
            if not raw_path:
                continue
            path = Path(str(raw_path))
            resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError:
                violations += 1
                continue
            if allowed and not any(relative == item or relative.startswith(item + "/") for item in allowed):
                violations += 1
            if any(relative == item or relative.startswith(item + "/") for item in forbidden):
                violations += 1
        return violations

    async def execute_mission(
        self,
        identity: RuntimeIdentity,
        intent: Intent,
        baseline_commit: str = "HEAD",
        tasks: Optional[List[TaskNode]] = None,
    ) -> ProofObject:
        """Run a bounded task graph and return an evidence-addressed proof."""
        mission_id = self._mission_id(identity, intent)
        mission = CodeMission(
            mission_id=mission_id,
            identity=identity,
            intent=intent,
            baseline_commit=baseline_commit,
            state=MissionState.RECEIVED,
            task_graph=list(tasks or []),
        )
        validation_results: Dict[str, ExecutionStatus] = {}
        claims: List[Claim] = []
        receipts: List[EvidenceReceipt] = []
        provider_ids: set[str] = set()
        latency_ms = 0
        tokens_used = 0

        # Context Gate preflight runs before repository inspection or provider work.
        mission.state = MissionState.HYDRATING
        try:
            intent_digest = hashlib.sha256(intent.goal.encode("utf-8")).hexdigest()
            event_id = self.context_gate.log_event(
                "mission_preflight",
                "NouGenCode mission preflight",
                {"mission_id": mission_id, "intent_sha256": intent_digest},
            )
            phrase = '"' + intent.goal.replace('"', '""') + '"'
            related = self.context_gate.search_context(phrase, limit=5)
            receipts.append(EvidenceReceipt.from_payload(
                "preflight",
                "context_gate",
                {"event_id": event_id, "related_event_ids": [row.get("id") for row in related]},
            ))
        except Exception as exc:
            validation_results["context_gate"] = ExecutionStatus.INFRA_ERROR
            claims.append(Claim(
                id="c_context_gate",
                statement="Context Gate preflight could not be verified.",
                severity=1.0,
                confidence=1.0,
                evidence=[type(exc).__name__],
            ))

        mission.state = MissionState.MAPPED
        try:
            repomap = self.cartographer.inspect_level_0()
            receipts.append(EvidenceReceipt.from_payload(
                "cartography",
                "repo_cartographer",
                {
                    "root": repomap.root_path,
                    "languages": sorted(repomap.languages),
                    "frameworks": sorted(repomap.frameworks),
                    "tests": sorted(repomap.tests),
                    "entrypoints": sorted(repomap.entrypoints),
                },
            ))
        except Exception as exc:
            validation_results["cartography"] = ExecutionStatus.INFRA_ERROR
            claims.append(Claim(
                id="c_cartography",
                statement="Repository cartography could not be verified.",
                severity=1.0,
                confidence=1.0,
                evidence=[type(exc).__name__],
            ))
            repomap = None

        graph_errors = mission.task_graph_errors()
        if not mission.task_graph:
            graph_errors.append("task graph is empty")
        receipts.append(EvidenceReceipt.from_payload(
            "planning",
            "task_graph",
            [{
                "id": task.id,
                "dependencies": sorted(task.dependencies),
                "capability": task.capability.value,
            } for task in mission.task_graph],
        ))
        if graph_errors:
            validation_results["task_graph"] = ExecutionStatus.FAIL
            claims.append(Claim(
                id="c_task_graph",
                statement="Task graph is invalid: " + "; ".join(graph_errors),
                severity=1.0,
                confidence=1.0,
                evidence=["task_graph_validation"],
            ))

        if repomap is not None and not graph_errors and "context_gate" not in validation_results:
            mission.state = MissionState.PLANNED
            while True:
                ready = mission.ready_nodes()
                if not ready:
                    break
                wave = self.fanout_governor.select_wave(ready)
                prepared: List[Tuple[TaskNode, CodeProvider]] = []
                for task in wave:
                    provider = self.switchboard.resolve(task.capability, task)
                    if provider is None:
                        task.attempted = True
                        task.execution_status = ExecutionStatus.FAIL.value
                        validation_results[f"{task.id}_execution"] = ExecutionStatus.FAIL
                        claims.append(Claim(
                            id=f"c_no_provider_{task.id}",
                            statement=f"No provider supports capability {task.capability.value}.",
                            severity=1.0,
                            confidence=1.0,
                            evidence=["switchboard_resolution"],
                        ))
                    else:
                        prepared.append((task, provider))

                mission.state = MissionState.EXECUTING
                execution_context = {
                    "repo": repomap.root_path,
                    "intent": intent,
                    "runtime_identity": identity,
                }
                results = await asyncio.gather(*(
                    self._execute_provider(provider, task, execution_context)
                    for task, provider in prepared
                ))

                for (task, provider), result in zip(prepared, results):
                    task.attempted = True
                    task.completed = result.status == ExecutionStatus.PASS
                    task.execution_status = result.status.value
                    task.evidence.append({
                        "provider_id": provider.provider_id,
                        "status": result.status.value,
                        "latency_ms": result.latency_ms,
                    })
                    provider_ids.add(provider.provider_id)
                    latency_ms += result.latency_ms
                    tokens_used += result.tokens_used
                    validation_results[f"{task.id}_execution"] = result.status
                    self.switchboard.record_competence(
                        provider.provider_id, task.capability, task.completed
                    )
                    mission.mutations.extend(result.mutations)
                    receipts.append(EvidenceReceipt.from_payload(
                        "execution",
                        "replaceable_provider",
                        {
                            "task_id": task.id,
                            "provider_id": provider.provider_id,
                            "status": result.status.value,
                            "mutation_count": len(result.mutations),
                            "latency_ms": result.latency_ms,
                            "tokens_used": result.tokens_used,
                        },
                    ))

                    if result.status != ExecutionStatus.PASS:
                        claims.append(Claim(
                            id=f"c_execution_{task.id}",
                            statement=f"Task {task.id} execution ended with {result.status.value}.",
                            severity=0.8,
                            confidence=1.0,
                            evidence=["provider_execution_receipt"],
                        ))

                    scope_violations = self._mutation_scope_violations(task, result.mutations)
                    validation_results[f"{task.id}_mutation_scope"] = (
                        ExecutionStatus.FAIL if scope_violations else ExecutionStatus.PASS
                    )
                    receipts.append(EvidenceReceipt.from_payload(
                        "mutation_scope",
                        "repo_boundary_check",
                        {"task_id": task.id, "violations": scope_violations},
                    ))
                    if scope_violations:
                        claims.append(Claim(
                            id=f"c_mutation_scope_{task.id}",
                            statement=f"Task {task.id} reported writes outside its allowed workspace scope.",
                            severity=1.0,
                            confidence=1.0,
                            evidence=["repo_boundary_check"],
                        ))

                    if task.mutation_budget:
                        file_count, added, deleted = self._mutation_counts(result.mutations)
                        if added is None or deleted is None:
                            validation_results[f"{task.id}_mutation_budget"] = ExecutionStatus.UNKNOWN
                            claims.append(Claim(
                                id=f"c_mutation_evidence_{task.id}",
                                statement=f"Task {task.id} mutation line counts were not reported.",
                                severity=0.8,
                                confidence=1.0,
                                evidence=["mutation_budget_requires_line_counts"],
                            ))
                        else:
                            drift = task.mutation_budget.evaluate_drift(file_count, added, deleted)
                            status = ExecutionStatus.PASS if drift <= 1.0 else ExecutionStatus.FAIL
                            validation_results[f"{task.id}_mutation_budget"] = status
                            if status == ExecutionStatus.FAIL:
                                claims.append(Claim(
                                    id=f"c_mutation_drift_{task.id}",
                                    statement=f"Task {task.id} mutation drift {drift:.2f} exceeded its budget.",
                                    severity=0.8,
                                    confidence=1.0,
                                    evidence=["mutation_budget_check"],
                                ))
                        receipts.append(EvidenceReceipt.from_payload(
                            "mutation_budget",
                            "reported_mutation_counts",
                            {"task_id": task.id, "mutation_count": len(result.mutations)},
                        ))

                    mission.state = MissionState.VALIDATING
                    syntax_result = await self.test_ladder.run_syntax_check(task.files_expected)
                    validation_results[f"{task.id}_syntax"] = syntax_result.status
                    receipts.append(EvidenceReceipt.from_payload(
                        "validation",
                        "syntax_test_ladder",
                        {"task_id": task.id, "status": syntax_result.status.value},
                    ))
                    if syntax_result.status != ExecutionStatus.PASS:
                        claims.append(Claim(
                            id=f"c_syntax_{task.id}",
                            statement=f"Syntax validation for task {task.id} did not pass.",
                            severity=0.8,
                            confidence=1.0,
                            evidence=["syntax_test_ladder"],
                        ))

                    for test_file in task.validation:
                        test_result = await self.test_ladder.run_targeted_test(test_file)
                        validation_results[f"{task.id}_test_{test_file}"] = test_result.status
                        receipts.append(EvidenceReceipt.from_payload(
                            "validation",
                            "targeted_test_ladder",
                            {"task_id": task.id, "test": test_file, "status": test_result.status.value},
                        ))
                        if test_result.status != ExecutionStatus.PASS:
                            claims.append(Claim(
                                id=f"c_test_{task.id}_{len(receipts)}",
                                statement=f"Targeted validation for task {task.id} did not pass.",
                                severity=0.8,
                                confidence=1.0,
                                evidence=["targeted_test_ladder"],
                            ))

                    mission.state = MissionState.REVIEWING
                    from .critics.product import ProductJudgmentCritic
                    from .security.invariants import ConcentricSecurityGate

                    for mutation in result.mutations:
                        code = mutation.get("content") or ""
                        for violation in ConcentricSecurityGate.audit_code(code):
                            claims.append(Claim(
                                id=f"sec_{task.id}_{violation.violation_type}",
                                statement=violation.message,
                                severity=1.0,
                                confidence=1.0,
                                evidence=[violation.violation_type, violation.matched_snippet],
                            ))

                    critic = ProductJudgmentCritic(penalty_lambda=2.0)
                    critic_result = critic.evaluate_inferred_requirements(
                        explicit_requirements=[task.objective],
                        source_code="\n".join(
                            mutation.get("content") or "" for mutation in result.mutations
                        ),
                        context_evidence=["controller_task_execution"],
                    )
                    if critic_result.hallucinated_count:
                        claims.append(Claim(
                            id=f"lsc_{task.id}",
                            statement=f"Product review found {critic_result.hallucinated_count} unsupported additions.",
                            severity=0.75,
                            confidence=0.85,
                            evidence=["product_judgment_critic"],
                        ))

                receipts.append(EvidenceReceipt.from_payload(
                    "independent_review",
                    "security_and_product_critics",
                    {"reviewed_tasks": [task.id for task, _ in prepared], "claim_count": len(claims)},
                ))

        remaining = [task.id for task in mission.task_graph if not task.completed]
        if remaining:
            validation_results["task_graph_completion"] = ExecutionStatus.UNKNOWN
            claims.append(Claim(
                id="c_unfinished_tasks",
                statement="Tasks remain unverified or blocked by an unsuccessful dependency: " + ", ".join(sorted(remaining)),
                severity=0.8,
                confidence=1.0,
                evidence=["task_graph_state"],
            ))

        receipts.append(EvidenceReceipt.from_payload(
            "postflight",
            "control_plane",
            {
                "mission_id": mission_id,
                "result_inputs": {name: status.value for name, status in validation_results.items()},
                "claim_ids": [claim.id for claim in claims],
                "providers": sorted(provider_ids),
            },
        ))
        mission.state = MissionState.ARBITRATING
        proof = self.arbiter.compile_proof(
            task_id=mission_id,
            baseline_commit=baseline_commit,
            mutations=mission.mutations,
            validation_results=validation_results,
            claims=claims,
            evidence_receipts=tuple(receipts),
        )
        mission.state = MissionState.VERIFIED if proof.result == "verified" else MissionState.BLOCKED

        checkpoint = MissionCheckpoint(
            mission_id=mission_id,
            result=proof.result,
            observed_at=proof.evidence_receipts[-1].observed_at,
            provider_ids=tuple(sorted(provider_ids)),
            evidence_receipts=proof.evidence_receipts,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
        )
        try:
            self.tracker_feedback.record_checkpoint(checkpoint)
            proof.reviews["tracker_feedback"] = "recorded" if self._tracker_configured else "not_configured"
        except Exception as exc:
            proof.reviews["tracker_feedback"] = f"unknown:{type(exc).__name__}"
        try:
            self.postflight_capture.capture_checkpoint(checkpoint)
            proof.reviews["shards_relay_postflight"] = "captured" if self._postflight_configured else "not_configured"
        except Exception as exc:
            proof.reviews["shards_relay_postflight"] = f"unknown:{type(exc).__name__}"
        return proof
