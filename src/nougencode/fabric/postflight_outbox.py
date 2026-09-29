"""Append-only idempotent postflight outbox with hash-chained proof receipts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from nougencode.canonical import canonical_sha256, normalize_timestamp


def _sha256(value: Any) -> str:
    return canonical_sha256(value)


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
        content = {
            "sequence": self.sequence,
            "dedup_key": self.dedup_key,
            "target_channel": self.target_channel,
            "payload": self.payload,
            "created_at": self.created_at,
            "previous_hash": self.previous_hash,
        }
        return _sha256(content) == self.record_hash


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

            now_str = normalize_timestamp(timestamp) if timestamp is not None else datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            seq = len(self._records)
            prev = self._last_hash

            content = {
                "sequence": seq,
                "dedup_key": dedup_key,
                "target_channel": target_channel,
                "payload": payload,
                "created_at": now_str,
                "previous_hash": prev,
            }
            rec_hash = _sha256(content)

            rec = OutboxRecord(
                sequence=seq,
                dedup_key=dedup_key,
                target_channel=target_channel,
                payload=payload,
                created_at=now_str,
                previous_hash=prev,
                record_hash=rec_hash,
                status="PENDING",
            )

            self._records.append(rec)
            self._dedup_index[dedup_key] = rec
            self._last_hash = rec_hash
            return (rec, True)

    def mark_delivered(self, dedup_key: str) -> bool:
        with self._lock:
            rec = self._dedup_index.get(dedup_key)
            if not rec:
                return False
            # Immutable update in list
            updated = OutboxRecord(
                sequence=rec.sequence,
                dedup_key=rec.dedup_key,
                target_channel=rec.target_channel,
                payload=rec.payload,
                created_at=rec.created_at,
                previous_hash=rec.previous_hash,
                record_hash=rec.record_hash,
                status="DELIVERED",
            )
            self._records[rec.sequence] = updated
            self._dedup_index[dedup_key] = updated
            return True

    def get_pending(self) -> Sequence[OutboxRecord]:
        with self._lock:
            return tuple(r for r in self._records if r.status == "PENDING")

    def verify_chain(self) -> Tuple[bool, Optional[str]]:
        """Verify the complete hash-chain integrity."""
        with self._lock:
            prev = GENESIS_HASH
            for idx, r in enumerate(self._records):
                if r.sequence != idx:
                    return (False, f"Sequence mismatch at index {idx}: expected {idx}, got {r.sequence}")
                if r.previous_hash != prev:
                    return (False, f"Chain broken at index {idx}: prev_hash mismatch")
                if not r.verify_integrity():
                    return (False, f"Tampered record at index {idx}: hash verification failed")
                prev = r.record_hash
            return (True, None)

    def count(self) -> int:
        with self._lock:
            return len(self._records)
