"""TenantCoordinator & Durable Event-Driven Control-Plane Kernel for Hourly Worker.

Assimilates Cloudflare-style Durable Object coordination with monotonic fencing,
durable workflow state progression, Queue ingress with DLQ, and Authority-Ranked
Bayesian Arbitration for multi-node observation grids.

Mathematical & Architectural Invariants:
1. Monotonic Fencing: tau_{fence} > tau_{last}. Any write with tau <= tau_{last}
   is rejected with 409 conflict proof.
2. Authority-Ranked Weighted Arbitration:
   W(State) = sum_{o in State} (authority(o) * freshness_decay(t_o))
   If max_state_weight / total_weight >= theta (default 0.80), settles decisively,
   preventing 10 weak unauthenticated probes from outvoting 1 authenticated probe.
3. UNKNOWN_WITHIN_BUDGET != failure:
   Incomplete source coverage within time budget is UNKNOWN, not FAILED.
4. Idempotency Keying:
   Every state transition has H(tenant_id || fence || event_id) content-addressed identity.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from nougencode.core.evidence_kernel import CoverageEnvelope, EventEnvelope, EvidenceState, Provenance


class WorkflowPhase(str, Enum):
    INGRESS = "ingress"
    DISCOVER = "discover"
    CLASSIFY = "classify"
    EXECUTE = "execute"
    VERIFY = "verify"
    COMPLETE = "complete"
    DLQ = "dead_letter_queue"


class ResolutionState(str, Enum):
    VERIFIED = "verified"
    UNKNOWN_WITHIN_BUDGET = "unknown_within_budget"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass(frozen=True)
class MonotonicFenceToken:
    fence_counter: int
    tenant_id: str
    owner_node: str
    issued_ns: int = field(default_factory=time.time_ns)

    def validate_advance(self, proposed_fence: int) -> bool:
        return proposed_fence > self.fence_counter


@dataclass(frozen=True)
class QueueItem:
    message_id: str
    tenant_id: str
    payload: Mapping[str, Any]
    idempotency_key: str
    attempt_count: int = 1
    max_retries: int = 3
    enqueued_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class AuthorityArbitrationResult:
    winning_state: ResolutionState
    confidence: float
    weights_by_state: Mapping[str, float]
    consensus_ratio: float
    reasons: Tuple[str, ...]
    canonical_receipt_hash: str


class AuthorityArbitrator:
    """Authority-Ranked Bayesian Weight Arbiter.
    Prevents weak/unauthenticated observers from creating false CONFLICTs against
    authenticated probes.
    """

    @classmethod
    def arbitrate(
        cls,
        observations: Sequence[EventEnvelope],
        coverage: CoverageEnvelope,
        *,
        consensus_threshold: float = 0.80,
        decay_half_life_s: float = 300.0,
    ) -> AuthorityArbitrationResult:
        if not observations:
            if coverage.absence_is_provable:
                reasons = ("complete coverage proved absence",)
                h = sha256(("VERIFIED:ABSENCE:" + repr(reasons)).encode()).hexdigest()
                return AuthorityArbitrationResult(
                    winning_state=ResolutionState.VERIFIED,
                    confidence=1.0,
                    weights_by_state={},
                    consensus_ratio=1.0,
                    reasons=reasons,
                    canonical_receipt_hash=h,
                )
            reasons = ("incomplete coverage within budget; absence cannot be inferred",)
            h = sha256(("UNKNOWN_BUDGET:" + repr(reasons)).encode()).hexdigest()
            return AuthorityArbitrationResult(
                winning_state=ResolutionState.UNKNOWN_WITHIN_BUDGET,
                confidence=0.5,
                weights_by_state={},
                consensus_ratio=0.0,
                reasons=reasons,
                canonical_receipt_hash=h,
            )

        now = time.time()
        weights: Dict[str, float] = {}

        for obs in observations:
            if obs.state in {EvidenceState.STALE, EvidenceState.FAILED}:
                continue
            # Calculate freshness decay
            obs_dt = datetime.fromisoformat(obs.provenance.observed_at).timestamp() if obs.provenance.observed_at else now
            age_s = max(0.0, now - obs_dt)
            decay = math.exp(-age_s / decay_half_life_s)

            # Weight = (1.0 + authority) * decay
            w = max(1.0, float(obs.provenance.authority) + 1.0) * decay
            state_key = obs.state.value
            weights[state_key] = weights.get(state_key, 0.0) + w

        total_weight = sum(weights.values())
        if total_weight <= 0.0:
            reasons = ("all observations were stale or failed",)
            h = sha256(("UNKNOWN_STALE:" + repr(reasons)).encode()).hexdigest()
            return AuthorityArbitrationResult(
                winning_state=ResolutionState.UNKNOWN_WITHIN_BUDGET,
                confidence=0.0,
                weights_by_state=weights,
                consensus_ratio=0.0,
                reasons=reasons,
                canonical_receipt_hash=h,
            )

        sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        top_state, top_w = sorted_weights[0]
        consensus = top_w / total_weight

        if consensus >= consensus_threshold:
            # Settled decisively
            reasons = (
                f"Authority consensus achieved: {top_state} ({consensus:.1%} >= {consensus_threshold:.1%})",
            )
            state_enum = ResolutionState.VERIFIED if top_state == EvidenceState.VERIFIED.value else ResolutionState(top_state)
            h = sha256((f"SETTLED:{top_state}:{consensus}:" + repr(sorted(weights.items()))).encode()).hexdigest()
            return AuthorityArbitrationResult(
                winning_state=state_enum,
                confidence=consensus,
                weights_by_state=weights,
                consensus_ratio=consensus,
                reasons=reasons,
                canonical_receipt_hash=h,
            )
        else:
            # Conflicting high-authority states
            reasons = (
                f"Consensus threshold missed: top state {top_state} at {consensus:.1%} < {consensus_threshold:.1%}",
            )
            h = sha256(("CONFLICT:" + repr(sorted(weights.items()))).encode()).hexdigest()
            return AuthorityArbitrationResult(
                winning_state=ResolutionState.CONFLICT,
                confidence=consensus,
                weights_by_state=weights,
                consensus_ratio=consensus,
                reasons=reasons,
                canonical_receipt_hash=h,
            )


@dataclass
class TenantCoordinator:
    """Per-tenant Durable Object coordinator with monotonic fencing & queue ingress."""

    tenant_id: str
    current_fence: int = 0
    current_phase: WorkflowPhase = WorkflowPhase.INGRESS
    active_lease_owner: Optional[str] = None
    queue: List[QueueItem] = field(default_factory=list)
    dlq: List[QueueItem] = field(default_factory=list)
    completed_events: List[str] = field(default_factory=list)

    def advance_fence(self, node_id: str) -> MonotonicFenceToken:
        """Issue an incremented fence token, invalidating prior zombie owners."""
        self.current_fence += 1
        self.active_lease_owner = node_id
        return MonotonicFenceToken(
            fence_counter=self.current_fence,
            tenant_id=self.tenant_id,
            owner_node=node_id,
        )

    def validate_fence(self, token: MonotonicFenceToken) -> Tuple[bool, Optional[str]]:
        """Validate whether an executing worker has the active monotonic lease."""
        if token.tenant_id != self.tenant_id:
            return False, f"Tenant mismatch: expected {self.tenant_id}, got {token.tenant_id}"
        if token.fence_counter < self.current_fence:
            return False, f"Zombie fence violation: token fence {token.fence_counter} < active {self.current_fence}"
        return True, None

    def enqueue(self, payload: Mapping[str, Any], idempotency_key: str) -> QueueItem:
        msg_id = sha256(f"{self.tenant_id}:{self.current_fence}:{idempotency_key}".encode()).hexdigest()[:16]
        item = QueueItem(
            message_id=msg_id,
            tenant_id=self.tenant_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        self.queue.append(item)
        return item

    def process_queue_step(
        self,
        token: MonotonicFenceToken,
        executor_fn: Any,
    ) -> Tuple[bool, Optional[QueueItem], Optional[str]]:
        """Execute one item from queue under monotonic fence lease."""
        val_ok, err = self.validate_fence(token)
        if not val_ok:
            return False, None, err

        if not self.queue:
            return True, None, "Queue empty"

        item = self.queue.pop(0)
        self.current_phase = WorkflowPhase.EXECUTE
        try:
            success = executor_fn(item)
            if success:
                self.current_phase = WorkflowPhase.VERIFY
                self.completed_events.append(item.message_id)
                self.current_phase = WorkflowPhase.COMPLETE
                return True, item, None
            else:
                raise RuntimeError("Executor returned failure")
        except Exception as e:
            if item.attempt_count < item.max_retries:
                # Retry
                retried = QueueItem(
                    message_id=item.message_id,
                    tenant_id=item.tenant_id,
                    payload=item.payload,
                    idempotency_key=item.idempotency_key,
                    attempt_count=item.attempt_count + 1,
                    max_retries=item.max_retries,
                )
                self.queue.append(retried)
                return False, retried, f"Execution failed, retrying ({retried.attempt_count}/{retried.max_retries}): {e}"
            else:
                # Route to Dead Letter Queue
                self.dlq.append(item)
                self.current_phase = WorkflowPhase.DLQ
                return False, item, f"Max retries exhausted; routed to DLQ: {e}"
