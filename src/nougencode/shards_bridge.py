"""Direct filesystem bridge to the canonical 9-DB NouGenShards memory substrate.

Provides native zero-overhead FTS5 search, canonical locator parsing (node:db#id),
and auto-discovery of the user's canonical shards grid across Outpost and ~/.nougen.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

NUM_DBS = 9


def detect_node_name() -> str:
    """Resolves the current machine locator name (WhoArt, blade, etc.)."""
    for var in ("NOUGEN_NODE", "NOUGEN_NODE_NAME", "NOUGEN_MACHINE"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    try:
        return socket.gethostname().split(".")[0] or "unknown"
    except Exception:
        return "unknown"


def resolve_canonical_shards_dir() -> Path:
    """Discovers and hooks into the user's canonical 9-DB NouGenShards grid.

    Priority order:
    1. Explicit NOUGEN_VAULT_DIR or NOUGEN_SHARDS_DIR environment variable
    2. Canonical authority: ~/.nougen/shards (C:\\Users\\super\\.nougen\\shards)
    3. User profile .nougen/shards fallback
    4. Repo-adjacent .vault fallback (if allowed)
    """
    explicit = os.environ.get("NOUGEN_VAULT_DIR") or os.environ.get("NOUGEN_SHARDS_DIR")
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.is_dir():
            return p

    # Canonical persistent local authority
    canonical = (Path.home() / ".nougen" / "shards").resolve()
    if canonical.is_dir():
        return canonical

    # Alternative check on Windows user profiles
    win_profile = os.environ.get("USERPROFILE")
    if win_profile:
        alt_canonical = (Path(win_profile) / ".nougen" / "shards").resolve()
        if alt_canonical.is_dir():
            return alt_canonical

    return canonical


class ShardsBridge:
    """Interacts directly with the user's canonical 9-DB NouGenShards grid."""

    def __init__(self, shards_dir: Optional[Path] = None) -> None:
        self.shards_dir = (shards_dir or resolve_canonical_shards_dir()).resolve()
        self.node_name = detect_node_name()

    @property
    def is_connected(self) -> bool:
        """Checks if at least one shard database in the grid is active on disk."""
        if not self.shards_dir.exists():
            return False
        return any((self.shards_dir / f"nougen_shards_{i}.db").exists() for i in range(1, NUM_DBS + 1))

    def get_grid_stats(self) -> Dict[str, Any]:
        """Returns discovery information and database health across the 9-DB grid."""
        active_dbs = []
        total_size = 0
        for i in range(1, NUM_DBS + 1):
            db_path = self.shards_dir / f"nougen_shards_{i}.db"
            if db_path.exists():
                size = db_path.stat().st_size
                total_size += size
                active_dbs.append({"db": i, "path": str(db_path), "size_mb": round(size / (1024 * 1024), 2)})

        return {
            "canonical_root": str(self.shards_dir),
            "node": self.node_name,
            "connected": self.is_connected,
            "active_databases": len(active_dbs),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "databases": active_dbs,
        }

    def search_shards(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Multi-DB FTS5 search across all active nougen_shards_*.db files."""
        results: List[Dict[str, Any]] = []

        # Sanitize query for FTS5
        clean_query = query.replace('"', '""').strip()
        if not clean_query:
            return results

        for i in range(1, NUM_DBS + 1):
            db_path = self.shards_dir / f"nougen_shards_{i}.db"
            if not db_path.exists():
                continue

            try:
                with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0) as conn:
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT s.id, s.title, s.content, s.tags, s.domain_key, s.utility_score
                        FROM shards s
                        JOIN shards_fts fts ON s.id = fts.rowid
                        WHERE shards_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (clean_query, limit),
                    )
                    for row in cur.fetchall():
                        item = dict(row)
                        item["locator"] = f"{self.node_name}:{i}#{item['id']}"
                        results.append(item)
            except Exception:
                continue

        # Sort by utility score descending
        results.sort(key=lambda x: float(x.get("utility_score") or 0.0), reverse=True)
        return results[:limit]

    def get_shard(self, db_index: int, shard_id: int) -> Optional[Dict[str, Any]]:
        """Direct fetch of a single shard by db and id."""
        db_path = self.shards_dir / f"nougen_shards_{db_index}.db"
        if not db_path.exists():
            return None
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, title, content, tags, domain_key, utility_score FROM shards WHERE id = ?",
                    (shard_id,),
                )
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    res["locator"] = f"{self.node_name}:{db_index}#{shard_id}"
                    return res
        except Exception:
            return None
        return None
