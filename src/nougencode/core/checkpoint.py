"""Provider-neutral lifecycle hooks for Tracker and Shards/Relay adapters."""

from dataclasses import dataclass
from typing import Protocol, Sequence

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
