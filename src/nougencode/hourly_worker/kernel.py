"""Unified Hourly Worker Control-Plane Kernel for NouGenCode.

Coordinates:
- EventEnvelope, CoverageEnvelope, TruthResolver
- RobustCadenceTTL and CadenceScheduler
- Material DeltaEngine
- Cloudflare Adapter Stack (Queue, Durable Objects with monotonic fencing, Workflows, DLQ)
- MCP Gateway (2026-07-28 stateless core, Tasks/MRTR, OTel 1.44, versioned GenAI adapters, Horizontal A2A)
- Independent Verification Receipts
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from nougencode.core.golden_slice import (
    CoverageEnvelope,
    EventEnvelope,
    EvidenceObservation,
    GoldenSliceResult,
    MutationBudget,
    MutationLedger,
    MutationRejected,
    PolicyPlanner,
    StaleFenceRejected,
    TaskNode,
    TruthResolver,
    TruthResult,
    TruthStatus,
    canonical_decision_hash,
    run_golden_slice,
)
from nougencode.core.mission import Capability
from .cadence import CadenceScheduler, CadenceTick, RobustCadenceTTL
from .cloudflare import (
    DeadLetterQueue,
    QueueIngressAdapter,
    QueueMessage,
    TenantDOCoordinator,
    WorkflowDurableExecutor,
    WorkflowStep,
)
from .delta import DeltaEngine, MaterialDelta
from .mcp_gateway import (
    A2APeerMessage,
    GenAIAdapterSpec,
    MCPGatewayAdapter,
    MCPRequest,
    OTelContext,
)
from .receipt import VerificationEngine, VerificationReceipt


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HourlyCycleResult:
    cycle_id: str
    tenant_id: str
    fence_token: int
    tick: CadenceTick
    truth: TruthResult
    decision_action: str
    delta: MaterialDelta
    verification_receipt: VerificationReceipt
    emitted_events: Tuple[EventEnvelope, ...]
    quarantined_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "tenant_id": self.tenant_id,
            "fence_token": self.fence_token,
            "tick": {
                "tick_id": self.tick.tick_id,
                "cycle_number": self.tick.cycle_number,
                "scheduled_at": self.tick.scheduled_at,
                "triggered_at": self.tick.triggered_at,
            },
            "truth": self.truth.to_dict(),
            "decision_action": self.decision_action,
            "delta": self.delta.to_dict(),
            "verification_receipt": self.verification_receipt.to_dict(),
            "emitted_events": [ev.to_dict() for ev in self.emitted_events],
            "quarantined_count": self.quarantined_count,
        }


class HourlyWorkerKernel:
    """Elevated Hourly Worker Kernel with durable event-driven control plane."""

    def __init__(
        self,
        tenant_id: str,
        *,
        interval_seconds: float = 3600.0,
        ttl_engine: Optional[RobustCadenceTTL] = None,
        dlq: Optional[DeadLetterQueue] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.scheduler = CadenceScheduler(interval_seconds=interval_seconds)
        self.ttl_engine = ttl_engine or RobustCadenceTTL(base_ttl_seconds=interval_seconds)
        self.dlq = dlq or DeadLetterQueue()
        self.queue_ingress = QueueIngressAdapter(dlq=self.dlq)
        self.coordinator = TenantDOCoordinator(tenant_id=tenant_id)
        self.workflow_executor = WorkflowDurableExecutor()
        self.mcp_gateway = MCPGatewayAdapter()
        self.mutation_ledger = MutationLedger()
        self._last_state_snapshot: Optional[Dict[str, Any]] = None

    async def execute_cycle(
        self,
        task: TaskNode,
        coverage: CoverageEnvelope,
        *,
        fence_token: int,
        idempotency_key: str,
        as_of: datetime,
        queued_messages: Optional[Sequence[QueueMessage]] = None,
    ) -> HourlyCycleResult:
        """Executes a single elevated hourly cycle under monotonic fence guarantees."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must include timezone")

        # 1. Acquire & validate monotonic fence
        active_fence = self.coordinator.acquire_fence(fence_token)
        tick = self.scheduler.create_tick(as_of)

        # 2. Process any incoming queue batch
        if queued_messages:
            self.queue_ingress.process_batch(
                queued_messages,
                lambda msg: True,  # Process handler
            )

        # 3. Run Golden Slice (Assess -> Plan -> Arbitrate)
        golden_result = run_golden_slice(task, coverage, as_of)
        truth = golden_result.truth
        decision_action = golden_result.decision.action

        # 4. Compute Material Delta
        current_snapshot = {
            "truth_status": truth.status.value,
            "decision_action": decision_action,
            "decision_hash": golden_result.decision_hash,
            "observations": [obs.to_dict() for obs in coverage.observations],
        }
        delta = DeltaEngine.compute_state_delta(self._last_state_snapshot, current_snapshot)

        # 5. Apply Idempotent State Mutation via Durable Object Coordinator
        if delta.is_material:
            self.coordinator.mutate_state(
                fence_token=active_fence,
                idempotency_key=idempotency_key,
                mutation_fn=lambda state: {**state, **current_snapshot},
            )
            self._last_state_snapshot = current_snapshot

        # 6. Construct Event Envelope for cycle execution
        event = EventEnvelope(
            mission_id=task.id,
            sequence=tick.cycle_number,
            event_type="hourly_cycle_executed",
            observed_at=as_of.astimezone(timezone.utc).isoformat(),
            source_id="hourly_worker_kernel",
            payload={
                "tenant_id": self.tenant_id,
                "fence_token": active_fence,
                "truth_status": truth.status.value,
                "decision_action": decision_action,
                "is_material_delta": delta.is_material,
                "delta_hash": delta.delta_hash,
            },
        )

        # 7. Generate Independent Verification Receipt
        receipt = VerificationEngine.generate_receipt(
            stage="hourly_worker_kernel_cycle",
            source_id="hourly_worker_kernel",
            tenant_id=self.tenant_id,
            mission_id=task.id,
            truth=truth,
            decision_action=decision_action,
            decision_hash=golden_result.decision_hash,
            fence_token=active_fence,
            raw_payload=event.to_dict(),
            as_of=as_of,
        )

        cycle_id = f"cycle_{receipt.receipt_id[5:]}"

        return HourlyCycleResult(
            cycle_id=cycle_id,
            tenant_id=self.tenant_id,
            fence_token=active_fence,
            tick=tick,
            truth=truth,
            decision_action=decision_action,
            delta=delta,
            verification_receipt=receipt,
            emitted_events=(event,),
            quarantined_count=self.dlq.count(),
        )
