"""Provider-neutral lifecycle hooks for Tracker and Shards/Relay adapters."""

from dataclasses import dataclass
import importlib
import os
from typing import Optional, Protocol, Tuple

from nougencode.arbitration.arbiter import EvidenceReceipt


@dataclass(frozen=True)
class MissionCheckpoint:
    """Small, immutable postflight envelope; it intentionally excludes source text."""

    mission_id: str
    result: str
    observed_at: str
    provider_ids: tuple[str, ...]
    evidence_receipts: tuple[EvidenceReceipt, ...]
    latency_ms: int = 0
    tokens_used: int = 0


class TrackerFeedback(Protocol):
    """Receives outcome metadata so Tracker can calibrate route and cost decisions."""

    def record_checkpoint(self, checkpoint: MissionCheckpoint) -> None: ...


class PostflightCapture(Protocol):
    """Adapter that may persist a verified checkpoint to Shards and Relay."""

    def capture_checkpoint(self, checkpoint: MissionCheckpoint) -> None: ...


class NullTrackerFeedback:
    def record_checkpoint(self, checkpoint: MissionCheckpoint) -> None:
        return None


class NullPostflightCapture:
    def capture_checkpoint(self, checkpoint: MissionCheckpoint) -> None:
        return None


def _load_adapter(spec: str, required_method: str):
    """Load an adapter object or zero-argument factory from ``module:attribute``."""
    module_name, separator, attribute_name = spec.partition(":")
    if not separator or not module_name.strip() or not attribute_name.strip():
        raise ValueError("adapter must use the format 'python.module:factory_or_object'")

    module = importlib.import_module(module_name.strip())
    configured = getattr(module, attribute_name.strip())
    adapter = configured() if callable(configured) else configured
    if not callable(getattr(adapter, required_method, None)):
        raise TypeError(f"configured adapter must provide {required_method}()")
    return adapter


def load_configured_adapters(
    *, load_tracker: bool = True, load_postflight: bool = True
) -> Tuple[Optional[TrackerFeedback], Optional[PostflightCapture]]:
    """Resolve deployment plugins without embedding machine or tenant paths.

    ``NOUGENCODE_TRACKER_ADAPTER`` and ``NOUGENCODE_POSTFLIGHT_ADAPTER`` each
    accept a Python ``module:factory`` or ``module:object`` reference. A plugin
    is imported only when that setting is present.
    """
    tracker_spec = os.environ.get("NOUGENCODE_TRACKER_ADAPTER", "").strip() if load_tracker else ""
    postflight_spec = (
        os.environ.get("NOUGENCODE_POSTFLIGHT_ADAPTER", "").strip()
        if load_postflight else ""
    )
    tracker = _load_adapter(tracker_spec, "record_checkpoint") if tracker_spec else None
    postflight = _load_adapter(postflight_spec, "capture_checkpoint") if postflight_spec else None
    return tracker, postflight
