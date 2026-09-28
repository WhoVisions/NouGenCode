"""Shard recorder for persisting code scan audits into NouGen memory."""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .models import ScanSummary


class ShardRecorder:
    """Interacts with NouGen shards to save code audits, deadcode scans, and bloat receipts."""

    def __init__(self, agent_id: str = "antigravity") -> None:
        self.agent_id = agent_id

    def record_scan_receipt(self, summary: ScanSummary) -> Optional[str]:
        """Creates a shard payload for the scan."""
        try:
            # Try importing nougen_shards if available in environment
            from nougen_shards import core

            content = (
                f"# NouGenCode Dead Code & Bloat Audit\n\n"
                f"- **Target**: `{summary.target_root}`\n"
                f"- **Files Scanned**: {summary.files_scanned}\n"
                f"- **Total Issues**: {len(summary.issues)}\n"
                f"- **Issue Breakdown**:\n"
            )
            for itype, count in summary.issues_by_type.items():
                content += f"  - `{itype}`: {count}\n"

            content += f"\n```json\n{json.dumps(summary.to_dict(), indent=2)}\n```\n"

            res = core.capture(
                event_type="audit",
                title=f"NouGenCode Audit: {summary.target_root}",
                content=content,
                tags=["ncode", "audit", "deadcode", "bloat", "ast"],
                domain_key="code_health",
                utility=1.0,
            )
            if isinstance(res, dict):
                return str(res.get("shard_id") or res.get("id") or res.get("reason"))
            return str(res)
        except ImportError:
            # Fallback or standalone execution
            return None
        except Exception:
            return None
