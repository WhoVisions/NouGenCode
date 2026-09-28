"""NouGen Context Mode Integration: WAL SQLite FTS5 Session & Zero-Token-Flood Protection.

HARD RULE: 99% OF ALL TOOL OUTPUTS, INSPECTIONS, TRACES, AND DATA EXPLORATION
MUST ROUTE THROUGH NOUGEN CONTEXT MODE TO PREVENT CONTEXT WINDOW SATURATION.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

# Canonical local NouGen context path
NOUGEN_CONTEXT_DIR = Path.home() / ".nougen" / "context"
SESSION_DB_PATH = NOUGEN_CONTEXT_DIR / "session.db"


class ContextGate:
    """Hard gatekeeper that logs session events and enforces sandboxed execution."""

    def __init__(self, session_name: str = "nougencode_session") -> None:
        self.session_name = session_name
        self.db_path = SESSION_DB_PATH
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ctx_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT
                );
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS ctx_events_fts USING fts5(
                    content,
                    content='ctx_events',
                    content_rowid='id'
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ctx_sandbox (
                    handle TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    data TEXT NOT NULL,
                    summary TEXT
                );
            """)
            conn.commit()

    def log_event(self, event_type: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        """Stores raw logs, bash outputs, or file traces in the local WAL FTS5 DB."""
        ts = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata or {})
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO ctx_events (timestamp, type, content, metadata) VALUES (?, ?, ?, ?)",
                (ts, event_type, content, meta_json),
            )
            event_id = cur.lastrowid
            cur.execute(
                "INSERT INTO ctx_events_fts (rowid, content) VALUES (?, ?)",
                (event_id, content),
            )
            conn.commit()
            return event_id or 0

    def search_context(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fast FTS5 search inside context events."""
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                """
                SELECT e.id, e.timestamp, e.type, e.content, e.metadata
                FROM ctx_events e
                JOIN ctx_events_fts fts ON e.id = fts.rowid
                WHERE ctx_events_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
            return [dict(row) for row in cur.fetchall()]

    def clamp_for_llm(self, raw_output: str, max_lines: int = 15, event_type: str = "tool_output") -> str:
        """99% Rule: Intercepts raw output, saves full text into Context DB, and returns a concise summary to the model."""
        lines = raw_output.splitlines()
        total_lines = len(lines)
        event_id = self.log_event(event_type, raw_output, {"total_lines": total_lines, "clamped": total_lines > max_lines})

        if total_lines <= max_lines:
            return raw_output

        preview = "\n".join(lines[:max_lines])
        return (
            f"{preview}\n\n"
            f"⚡ [NouGen Context Guard: {total_lines - max_lines} lines routed to Context DB "
            f"(Event #{event_id}). Context preserved. Full output stored in session.db]"
        )
