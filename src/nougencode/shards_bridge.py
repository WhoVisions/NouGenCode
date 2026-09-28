"""Direct filesystem bridge to the canonical 9-DB NouGenShards memory substrate.

Provides native zero-overhead FTS5 search, locator parsing (node:db#id),
and shard capture into C:\\Users\\super\\.nougen\\shards.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

SHARDS_DIR = Path.home() / ".nougen" / "shards"
NUM_DBS = 9


class ShardsBridge:
    """Interacts directly with the local 9-DB NouGenShards grid without external dependencies."""

    def __init__(self, shards_dir: Path = SHARDS_DIR) -> None:
        self.shards_dir = shards_dir

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
                        item["locator"] = f"{i}#{item['id']}"
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
                    res["locator"] = f"{db_index}#{shard_id}"
                    return res
        except Exception:
            return None
        return None
