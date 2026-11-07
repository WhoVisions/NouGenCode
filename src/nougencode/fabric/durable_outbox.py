"""SQLite-backed durable implementation of the postflight outbox contract."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator, Mapping, Optional, Sequence, Tuple

from nougencode.canonical import canonical_json
from nougencode.fabric.postflight_outbox import (
    GENESIS_HASH,
    OutboxRecord,
    _build_record,
    _resolve_timestamp,
    _verify_chain,
)

_SELECT_RECORD = (
    "SELECT sequence, dedup_key, target_channel, payload_json, "
    "created_at, previous_hash, record_hash, status FROM postflight_outbox"
)


class SQLitePostflightOutbox:
    """Persist idempotent postflight records and their hash chain in SQLite.

    The caller supplies the database path. The containing directory must
    already exist, so constructing this adapter never creates an unexpected
    directory tree.
    """

    def __init__(self, db_path: str | Path, timeout_seconds: float = 5.0) -> None:
        path = Path(db_path).expanduser()
        if str(path) == ":memory:":
            raise ValueError("SQLitePostflightOutbox requires a persistent database path")
        self._db_path = path.resolve()
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)
        self._lock = threading.Lock()
        with self._connection() as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS postflight_outbox (
                    sequence INTEGER PRIMARY KEY,
                    dedup_key TEXT NOT NULL UNIQUE,
                    target_channel TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING', 'DELIVERED', 'FAILED'))
                )"""
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self._db_path), timeout=self._timeout_seconds)
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _record(row: tuple[Any, ...]) -> OutboxRecord:
        return OutboxRecord(row[0], row[1], row[2], json.loads(row[3]), *row[4:])

    def append(
        self,
        dedup_key: str,
        target_channel: str,
        payload: Mapping[str, Any],
        timestamp: Optional[str] = None,
    ) -> Tuple[OutboxRecord, bool]:
        """Atomically append once per key, returning persisted records on retry."""
        if not isinstance(dedup_key, str) or not dedup_key.strip():
            raise ValueError("dedup_key must be a non-empty string")
        if not isinstance(target_channel, str) or not target_channel.strip():
            raise ValueError("target_channel must be a non-empty string")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be an object")
        payload_json = canonical_json(payload)
        created_at = _resolve_timestamp(timestamp)

        with self._lock, self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(f"{_SELECT_RECORD} WHERE dedup_key = ?", (dedup_key,)).fetchone()
            if duplicate is not None:
                return self._record(duplicate), False

            previous = connection.execute(
                "SELECT sequence, record_hash FROM postflight_outbox ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = previous[0] + 1 if previous is not None else 0
            previous_hash = previous[1] if previous is not None else GENESIS_HASH
            rec = _build_record(sequence, dedup_key, target_channel, json.loads(payload_json), created_at, previous_hash)
            connection.execute(
                "INSERT INTO postflight_outbox "
                "(sequence, dedup_key, target_channel, payload_json, created_at, previous_hash, record_hash, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')",
                (sequence, dedup_key, target_channel, payload_json, created_at, previous_hash, rec.record_hash),
            )
            return rec, True

    def mark_delivered(self, dedup_key: str) -> bool:
        with self._lock, self._connection() as connection, connection:
            cursor = connection.execute(
                "UPDATE postflight_outbox SET status = 'DELIVERED' WHERE dedup_key = ?",
                (dedup_key,),
            )
            return cursor.rowcount > 0

    def get_pending(self) -> Sequence[OutboxRecord]:
        with self._connection() as connection:
            rows = connection.execute(f"{_SELECT_RECORD} WHERE status = 'PENDING' ORDER BY sequence").fetchall()
        return tuple(self._record(row) for row in rows)

    def verify_chain(self) -> Tuple[bool, Optional[str]]:
        with self._connection() as connection:
            rows = connection.execute(f"{_SELECT_RECORD} ORDER BY sequence").fetchall()
        return _verify_chain(self._record(row) for row in rows)

    def count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) FROM postflight_outbox").fetchone()
        return int(row[0])
