"""Capture compact mission outcomes in Shards and checkpoint an active Relay leg."""

from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict

from nougencode.core.checkpoint import MissionCheckpoint


_RELAY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}$")


def _load_shards_core():
    """Use the installed Shards package or a deployment-selected source tree."""
    source = os.environ.get("NOUGEN_SHARDS_SOURCE", "").strip()
    if source:
        root = Path(source).expanduser().resolve()
        for candidate in (root / "src", root):
            if (candidate / "nougen_shards").is_dir():
                sys.path.insert(0, str(candidate))
                break
        else:
            raise ImportError("NOUGEN_SHARDS_SOURCE does not contain nougen_shards")
    return importlib.import_module("nougen_shards.core")


def _capture_shard(checkpoint: MissionCheckpoint) -> str:
    core = _load_shards_core()
    payload: Dict[str, Any] = asdict(checkpoint)
    result = core.capture(
        event_type="MISSION_OUTCOME",
        title=f"NouGenCode mission {checkpoint.mission_id}",
        content=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        tags=["nougencode", "mission-outcome", checkpoint.result],
        domain_key="engineering",
        original_timestamp=checkpoint.observed_at,
    )
    if not result:
        reason = result.get("reason", "capture_failed") if isinstance(result, dict) else "capture_failed"
        raise RuntimeError(f"Shards capture returned {reason}")
    if isinstance(result, dict) and result.get("shard_id") is not None:
        return f"shard:captured:{result.get('db_index')}#{result['shard_id']}"
    return "shard:captured"


def _checkpoint_relay(checkpoint: MissionCheckpoint) -> str:
    leg_id = checkpoint.relay_leg_id
    if not leg_id:
        return "relay:skipped_no_active_leg"
    if not _RELAY_ID.fullmatch(leg_id):
        raise ValueError("relay leg id contains unsupported characters")

    relay_dir = os.environ.get("NOUGEN_RELAY_DIR", "").strip()
    if not relay_dir:
        return "relay:unknown_unconfigured"
    relay_root = Path(relay_dir).expanduser().resolve()
    if not relay_root.is_dir():
        return "relay:unknown_unreachable"

    env = os.environ.copy()
    if checkpoint.machine_id:
        env["NOUGEN_MACHINE"] = checkpoint.machine_id
    if checkpoint.agent_id:
        env["NOUGEN_AGENT"] = checkpoint.agent_id
    relay_src = relay_root / "src"
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(relay_src), current_pythonpath) if part
    )
    message = (
        f"NouGenCode postflight mission={checkpoint.mission_id} "
        f"result={checkpoint.result} observed_at={checkpoint.observed_at}; "
        "completion remains provisional pending independent evidence."
    )
    completed = subprocess.run(
        [
            sys.executable, "-m", "nougen_relay.cli", "relay", "checkpoint",
            "--id", leg_id, "--state", "in_progress", "-m", message,
        ],
        cwd=relay_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        if "published registry projection, but push of local commit failed" in output:
            return "relay:checkpointed_in_progress_registry_published_local_diverged"
        return f"relay:unknown_exit_{completed.returncode}"
    return "relay:checkpointed_in_progress"


class NouGenPostflightCapture:
    """Capture Shards evidence and update only an explicitly carried Relay leg."""

    def capture_checkpoint(self, checkpoint: MissionCheckpoint) -> str:
        statuses = []
        try:
            statuses.append(_capture_shard(checkpoint))
        except Exception as exc:
            statuses.append(f"shard:unknown_{type(exc).__name__}")
        try:
            statuses.append(_checkpoint_relay(checkpoint))
        except subprocess.TimeoutExpired:
            statuses.append("relay:unknown_timeout")
        except Exception as exc:
            statuses.append(f"relay:unknown_{type(exc).__name__}")
        return ";".join(statuses)


def create_adapter() -> NouGenPostflightCapture:
    return NouGenPostflightCapture()
