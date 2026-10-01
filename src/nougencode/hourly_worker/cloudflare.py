"""Cloudflare adapter stack for NouGenCode hourly worker control plane.

Includes:
- Queue ingress adapter with deduplication
- Per-tenant Durable Object coordinator with monotonic fencing
- Workflow durable execution engine
- Dead Letter Queue (DLQ) quarantine handler
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Any, Callable, Coroutine, Dict, List, Mapping, Optional, Sequence, Tuple

from nougencode.core.golden_slice import StaleFenceRejected, MutationRejected


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QueueMessage:
    id: str
    body: Mapping[str, Any]
    timestamp: str
    attempts: int = 1
    idempotency_key: Optional[str] = None


@dataclass(frozen=True)
class DLQRecord:
    message_id: str
    reason: str
    payload: Mapping[str, Any]
    attempts: int
    quarantined_at: str
    error_detail: Optional[str] = None


class DeadLetterQueue:
    """Quarantines failed or poison-pill events with full diagnostic context."""

    def __init__(self) -> None:
        self._records: List[DLQRecord] = []
        self._lock = threading.Lock()

    def quarantine(
        self,
        message: QueueMessage,
        reason: str,
        error_detail: Optional[str] = None,
    ) -> DLQRecord:
        record = DLQRecord(
            message_id=message.id,
            reason=reason,
            payload=message.body,
            attempts=message.attempts,
            quarantined_at=datetime.now(timezone.utc).isoformat(),
            error_detail=error_detail,
        )
        with self._lock:
            self._records.append(record)
        return record

    def list_records(self) -> List[DLQRecord]:
        with self._lock:
            return list(self._records)

    def count(self) -> int:
        with self._lock:
            return len(self._records)


class TenantDOCoordinator:
    """Per-tenant Durable Object coordinator enforcing strictly monotonic fencing.
    
    Invariants:
    1. Single-writer per tenant via monotonic fence tokens.
    2. Stale or regressive fences are strictly rejected (StaleFenceRejected).
    3. State mutations require explicit idempotency keys.
    """

    def __init__(self, tenant_id: str) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id cannot be empty")
        self.tenant_id = tenant_id
        self._lock = threading.Lock()
        self._last_fence_token = 0
        self._idempotency_cache: Dict[str, str] = {}
        self._state: Dict[str, Any] = {}

    @property
    def current_fence(self) -> int:
        with self._lock:
            return self._last_fence_token

    def acquire_fence(self, requested_fence: int) -> int:
        """Validates and adopts a monotonic fence token."""
        with self._lock:
            if requested_fence <= self._last_fence_token:
                raise StaleFenceRejected(
                    f"tenant {self.tenant_id}: requested fence {requested_fence} <= current {self._last_fence_token}"
                )
            self._last_fence_token = requested_fence
            return self._last_fence_token

    def mutate_state(
        self,
        *,
        fence_token: int,
        idempotency_key: str,
        mutation_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Applies a mutation guarded by fence token and idempotency key."""
        if not idempotency_key.strip():
            raise MutationRejected("idempotency_key is required for state mutation")
        if fence_token <= 0:
            raise MutationRejected("fence_token must be a positive integer")

        with self._lock:
            if fence_token < self._last_fence_token:
                raise StaleFenceRejected(
                    f"mutation fence {fence_token} is stale (active fence is {self._last_fence_token})"
                )

            # Check idempotency
            prior_hash = self._idempotency_cache.get(idempotency_key)
            if prior_hash is not None:
                # Already processed under this idempotency key
                return False, dict(self._state)

            self._last_fence_token = max(self._last_fence_token, fence_token)
            new_state = mutation_fn(dict(self._state))
            self._state = new_state
            self._idempotency_cache[idempotency_key] = _sha256(new_state)
            return True, dict(self._state)

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)


class QueueIngressAdapter:
    """Ingests batched messages from Cloudflare Queues with dedup and DLQ routing."""

    def __init__(self, dlq: Optional[DeadLetterQueue] = None, max_attempts: int = 3) -> None:
        self.dlq = dlq or DeadLetterQueue()
        self.max_attempts = max_attempts
        self._processed_msg_ids: Dict[str, str] = {}
        self._lock = threading.Lock()

    def process_batch(
        self,
        messages: Sequence[QueueMessage],
        handler: Callable[[QueueMessage], bool],
    ) -> Tuple[List[str], List[str]]:
        """Processes a queue batch, routing failed messages past max_attempts to DLQ."""
        successful_ids = []
        failed_ids = []

        for msg in messages:
            with self._lock:
                if msg.id in self._processed_msg_ids:
                    # Idempotent skip for already acked message
                    successful_ids.append(msg.id)
                    continue

            try:
                success = handler(msg)
                if success:
                    with self._lock:
                        self._processed_msg_ids[msg.id] = _sha256(msg.body)
                    successful_ids.append(msg.id)
                else:
                    if msg.attempts >= self.max_attempts:
                        self.dlq.quarantine(msg, "handler_returned_false_max_attempts_exceeded")
                    failed_ids.append(msg.id)
            except Exception as exc:
                if msg.attempts >= self.max_attempts:
                    self.dlq.quarantine(msg, "handler_exception_max_attempts_exceeded", str(exc))
                failed_ids.append(msg.id)

        return successful_ids, failed_ids


@dataclass
class WorkflowStep:
    name: str
    action: Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]
    retries: int = 2


class WorkflowDurableExecutor:
    """Durable execution engine with step-level memoization and state recovery."""

    def __init__(self) -> None:
        self._memoized_steps: Dict[str, Any] = {}

    async def run_step(
        self,
        workflow_id: str,
        step: WorkflowStep,
        context: Dict[str, Any],
    ) -> Any:
        step_key = f"{workflow_id}:{step.name}"
        if step_key in self._memoized_steps:
            return self._memoized_steps[step_key]

        last_exc = None
        for attempt in range(step.retries + 1):
            try:
                result = await step.action(context)
                self._memoized_steps[step_key] = result
                return result
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(0.01 * (attempt + 1))

        raise RuntimeError(f"Step {step.name} failed after {step.retries + 1} attempts: {last_exc}") from last_exc
