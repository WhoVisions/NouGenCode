"""Append-only idempotent postflight outbox with hash-chained proof receipts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from nougencode.canonical import canonical_sha256, canonical_timestamp, normalize_timestamp


def _sha256(value: Any) -> str:
    return canonical_sha256(value)


def _resolve_timestamp(timestamp: Optional[str]) -> str:
    return normalize_timestamp(timestamp) if timestamp is not None else canonical_timestamp(datetime.now(timezone.utc))


GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class OutboxRecord:
    sequence: int
    dedup_key: str
    target_channel: str
    payload: Mapping[str, Any]
    created_at: str
    previous_hash: str
    record_hash: str
    status: str = "PENDING"  # PENDING, DELIVERED, FAILED

    def verify_integrity(self) -> bool:
        return _build_record(
            self.sequence, self.dedup_key, self.target_channel, self.payload, self.created_at, self.previous_hash
        ).record_hash == self.record_hash


def _build_record(
    sequence: int, dedup_key: str, target_channel: str, payload: Mapping[str, Any], created_at: str, previous_hash: str
) -> OutboxRecord:
    record_hash = _sha256({
        "sequence": sequence,
        "dedup_key": dedup_key,
        "target_channel": target_channel,
        "payload": payload,
        "created_at": created_at,
        "previous_hash": previous_hash,
    })
    return OutboxRecord(sequence, dedup_key, target_channel, payload, created_at, previous_hash, record_hash)


def _verify_chain(records: Iterable[OutboxRecord]) -> Tuple[bool, Optional[str]]:
    prev = GENESIS_HASH
    for idx, r in enumerate(records):
        if r.sequence != idx:
            return (False, f"Sequence mismatch at index {idx}: expected {idx}, got {r.sequence}")
        if r.previous_hash != prev:
            return (False, f"Chain broken at index {idx}: prev_hash mismatch")
        if not r.verify_integrity():
            return (False, f"Tampered record at index {idx}: hash verification failed")
        prev = r.record_hash
    return (True, None)


class OutboxBackend(Protocol):
    """Structural contract shared by volatile and durable outbox providers."""

    def append(
        self,
        dedup_key: str,
        target_channel: str,
        payload: Mapping[str, Any],
        timestamp: Optional[str] = None,
    ) -> Tuple[OutboxRecord, bool]: ...
    def mark_delivered(self, dedup_key: str) -> bool: ...
    def get_pending(self) -> Sequence[OutboxRecord]: ...
    def verify_chain(self) -> Tuple[bool, Optional[str]]: ...
    def count(self) -> int: ...


class PostflightOutbox:
    """Thread-safe append-only ledger guaranteeing idempotency and receipt hash chaining."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: List[OutboxRecord] = []
        self._dedup_index: Dict[str, OutboxRecord] = {}
        self._last_hash: str = GENESIS_HASH

    def append(
        self,
        dedup_key: str,
        target_channel: str,
        payload: Mapping[str, Any],
        timestamp: Optional[str] = None,
    ) -> Tuple[OutboxRecord, bool]:
        """Append record to outbox. If dedup_key exists, return existing record (is_new=False)."""
        with self._lock:
            if dedup_key in self._dedup_index:
                return (self._dedup_index[dedup_key], False)
            rec = _build_record(
                len(self._records), dedup_key, target_channel, payload, _resolve_timestamp(timestamp), self._last_hash
            )
            self._records.append(rec)
            self._dedup_index[dedup_key] = rec
            self._last_hash = rec.record_hash
            return (rec, True)

    def mark_delivered(self, dedup_key: str) -> bool:
        with self._lock:
            rec = self._dedup_index.get(dedup_key)
            if not rec:
                return False
            updated = replace(rec, status="DELIVERED")
            self._records[rec.sequence] = updated
            self._dedup_index[dedup_key] = updated
            return True

    def get_pending(self) -> Sequence[OutboxRecord]:
        with self._lock:
            return tuple(r for r in self._records if r.status == "PENDING")

    def verify_chain(self) -> Tuple[bool, Optional[str]]:
        """Verify the complete hash-chain integrity."""
        with self._lock:
            return _verify_chain(self._records)

    def count(self) -> int:
        with self._lock:
            return len(self._records)
