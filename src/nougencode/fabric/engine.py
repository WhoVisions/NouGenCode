"""Unified ChangeFabric engine orchestrating trustworthy software changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from nougencode.arbitration.arbiter import EvidenceArbiter, EvidenceReceipt
from nougencode.core.golden_slice import run_golden_slice, GoldenSliceResult
from nougencode.fabric.change_contract import ChangeContract
from nougencode.fabric.context_broker import ContextBroker, ContextItem, CoherenceReport
from nougencode.fabric.hook_abi import HookABIAdapter, HookPhase
from nougencode.fabric.postflight_outbox import OutboxBackend, PostflightOutbox, OutboxRecord
from nougencode.fabric.provider_ucb import ContextualProviderUCB, RouteDecision
from nougencode.fabric.shadow_policy import ShadowPolicyReplayer, ReplayReport
from nougencode.fabric.telemetry import OTelTelemetryTracer
from nougencode.fabric.selector import InformationGainTestSelector, SelectedTest, TestMetadata


@dataclass(frozen=True)
class ChangeFabricExecutionResult:
    session_id: str
    contract_id: str
    coherence_report: CoherenceReport
    route_decision: RouteDecision
    selected_tests: Sequence[SelectedTest]
    mutation_valid: bool
    mutation_violations: Sequence[str]
    outbox_record: OutboxRecord
    receipt_hash: str
    status: str  # ACCEPTED, REJECTED, GATED


class ChangeFabricEngine:
    """Orchestrates end-to-end change validation, retrieval coherence, and proof emission."""

    def __init__(
        self,
        context_broker: Optional[ContextBroker] = None,
        test_selector: Optional[InformationGainTestSelector] = None,
        hook_abi: Optional[HookABIAdapter] = None,
        outbox: Optional[OutboxBackend] = None,
        provider_ucb: Optional[ContextualProviderUCB] = None,
        telemetry: Optional[OTelTelemetryTracer] = None,
        shadow_replayer: Optional[ShadowPolicyReplayer] = None,
    ) -> None:
        self.context_broker = context_broker or ContextBroker()
        self.test_selector = test_selector or InformationGainTestSelector()
        self.hook_abi = hook_abi or HookABIAdapter()
        self.outbox = outbox or PostflightOutbox()
        self.provider_ucb = provider_ucb or ContextualProviderUCB()
        self.telemetry = telemetry or OTelTelemetryTracer()
        self.shadow_replayer = shadow_replayer or ShadowPolicyReplayer()

    def execute_change_cycle(
        self,
        session_id: str,
        contract: ChangeContract,
        modified_files: Sequence[str],
        lines_changed: int,
        diff_text: str = "",
        test_candidates: Optional[Sequence[TestMetadata]] = None,
        query: str = "",
    ) -> ChangeFabricExecutionResult:
        """Execute complete trustworthy change fabric lifecycle."""
        # 1. Telemetry start
        t_id, s_id, start_perf = self.telemetry.start_mission_span(
            mission_id=contract.contract_id,
            task_name="change_cycle",
        )

        # 2. Preflight hooks
        preflight_payload = {
            "contract_id": contract.contract_id,
            "modified_files": list(modified_files),
            "lines_changed": lines_changed,
        }
        _, hook_results = self.hook_abi.dispatch(
            phase=HookPhase.PREFLIGHT,
            session_id=session_id,
            task_id=contract.contract_id,
            payload=preflight_payload,
        )

        # 3. Context Broker retrieval & coherence evaluation
        raw_context = self.context_broker.retrieve_ensemble(query=query or contract.title)
        coherence = self.context_broker.evaluate_coherence(raw_context)

        # 4. Mutation validation
        mut_valid, violations = contract.validate_mutation(
            files_touched=modified_files,
            lines_changed=lines_changed,
            diff_text=diff_text,
        )

        # 5. Route selection
        # Register a default local arm if none exists
        if not self.provider_ucb._arms:
            self.provider_ucb.register_arm("local_ollama", "solai:latest", is_local=True)
            self.provider_ucb.register_arm("openrouter", "deepseek-coder", is_local=False)

        route = self.provider_ucb.select_route(task_complexity="medium")

        # 6. Test selection
        selected_tests: Sequence[SelectedTest] = ()
        if test_candidates:
            selected_tests = self.test_selector.select_tests(
                candidates=test_candidates,
                modified_files=modified_files,
            )

        # 7. Outbox append (Idempotent postflight)
        dedup_key = f"{session_id}:{contract.fingerprint}"
        outbox_payload = {
            "session_id": session_id,
            "contract_id": contract.contract_id,
            "fingerprint": contract.fingerprint,
            "coherence_debt": coherence.coherence_debt_score,
            "is_admitted": coherence.is_admitted,
            "mutation_valid": mut_valid,
            "route_provider": route.selected_provider_id,
            "route_model": route.selected_model_id,
            "selected_tests": [t.test_id for t in selected_tests],
        }

        rec, _ = self.outbox.append(
            dedup_key=dedup_key,
            target_channel="nougen-change-fabric-receipts",
            payload=outbox_payload,
        )

        # 8. Telemetry recording
        self.telemetry.record_mission_span(
            trace_id=t_id,
            span_id=s_id,
            mission_id=contract.contract_id,
            task_name="change_cycle",
            start_perf=start_perf,
            success=mut_valid and coherence.is_admitted,
            attributes={"receipt_hash": rec.record_hash},
        )

        # 9. Postflight hooks
        self.hook_abi.dispatch(
            phase=HookPhase.POSTFLIGHT,
            session_id=session_id,
            task_id=contract.contract_id,
            payload={"receipt_hash": rec.record_hash, "outbox_status": rec.status},
        )

        status = "ACCEPTED" if (mut_valid and coherence.is_admitted) else ("GATED" if not coherence.is_admitted else "REJECTED")

        return ChangeFabricExecutionResult(
            session_id=session_id,
            contract_id=contract.contract_id,
            coherence_report=coherence,
            route_decision=route,
            selected_tests=selected_tests,
            mutation_valid=mut_valid,
            mutation_violations=violations,
            outbox_record=rec,
            receipt_hash=rec.record_hash,
            status=status,
        )
