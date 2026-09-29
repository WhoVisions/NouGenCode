"""Explicit civil-time resolution and elapsed-time primitives.

No network clock is implied: callers must provide trusted UTC samples when
they need a verified instant. All elapsed deadlines use a monotonic clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Iterable


UTC = timezone.utc


class TimeModelError(ValueError):
    """Input cannot be represented without silently changing its meaning."""


class WallTimeKind(str, Enum):
    NORMAL = "normal"
    AMBIGUOUS = "ambiguous"
    NONEXISTENT = "nonexistent"


@dataclass(frozen=True)
class ZoneResolution:
    zone: ZoneInfo
    source: str


@dataclass(frozen=True)
class InstantEstimate:
    instant_utc: datetime
    verified: bool
    sources: tuple[str, ...]
    max_skew: timedelta | None


@dataclass(frozen=True)
class WallTimeResolution:
    kind: WallTimeKind
    candidates_utc: tuple[datetime, ...]


@dataclass(frozen=True)
class Deadline:
    monotonic_target: float

    @classmethod
    def after(cls, seconds: float, monotonic_now: float) -> "Deadline":
        if seconds < 0:
            raise TimeModelError("deadline duration must be non-negative")
        return cls(monotonic_now + seconds)

    def remaining(self, monotonic_now: float) -> float:
        return max(0.0, self.monotonic_target - monotonic_now)


def resolve_zone(
    preferred_iana: str | None,
    machine_iana: str | None,
    *,
    fallback: str = "UTC",
) -> ZoneResolution:
    """Resolve explicit user zone, then machine zone, then UTC fallback."""
    for name, source in ((preferred_iana, "user"), (machine_iana, "machine"), (fallback, "fallback")):
        if name is None:
            continue
        try:
            return ZoneResolution(ZoneInfo(name), source)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    raise TimeModelError("no valid IANA zone was available")


def estimate_utc(samples: Iterable[tuple[str, datetime]], *, tolerance: timedelta) -> InstantEstimate:
    """Take median of independent aware UTC samples; mark verified only when
    at least two named sources agree within tolerance. With one source, return
    its instant as unverified rather than implying network trust.
    """
    normalized: list[tuple[str, datetime]] = []
    for source, sample in samples:
        if not source.strip() or sample.tzinfo is None or sample.utcoffset() is None:
            raise TimeModelError("each sample needs a source and aware timestamp")
        normalized.append((source, sample.astimezone(UTC)))
    if not normalized:
        raise TimeModelError("at least one UTC sample is required")
    values = sorted((value for _, value in normalized))
    span = values[-1] - values[0]
    mid = len(values) // 2
    if len(values) % 2:
        estimate = values[mid]
    else:
        estimate = values[mid - 1] + (values[mid] - values[mid - 1]) / 2
    independent = len({source for source, _ in normalized}) >= 2
    return InstantEstimate(estimate, independent and span <= tolerance,
                           tuple(source for source, _ in normalized), span)


def classify_wall_time(local: datetime, zone: ZoneInfo) -> WallTimeResolution:
    """Classify naive local wall time by round-tripping both PEP-495 folds."""
    if local.tzinfo is not None:
        raise TimeModelError("wall time must be naive; zone is supplied separately")
    candidates: set[datetime] = set()
    for fold in (0, 1):
        assumed = local.replace(tzinfo=zone, fold=fold)
        utc = assumed.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == local:
            candidates.add(utc)
    ordered = tuple(sorted(candidates))
    kind = (WallTimeKind.NONEXISTENT if not ordered else
            WallTimeKind.AMBIGUOUS if len(ordered) == 2 else WallTimeKind.NORMAL)
    return WallTimeResolution(kind, ordered)


def resolve_wall_time(local: datetime, zone: ZoneInfo, *, ambiguous: str = "raise") -> datetime:
    """Resolve local time; ambiguous choices are earlier/later/raise.

    Nonexistent times always raise. Recurrence callers should advance the
    calendar date and re-resolve, rather than silently shifting the clock.
    """
    result = classify_wall_time(local, zone)
    if result.kind is WallTimeKind.NONEXISTENT:
        raise TimeModelError(f"nonexistent local time {local.isoformat()} in {zone.key}")
    if result.kind is WallTimeKind.AMBIGUOUS:
        if ambiguous not in {"earlier", "later"}:
            raise TimeModelError(f"ambiguous local time {local.isoformat()} in {zone.key}")
        return result.candidates_utc[0 if ambiguous == "earlier" else -1]
    return result.candidates_utc[0]


def next_daily_occurrence(local_date_time: datetime, zone: ZoneInfo, *, ambiguous: str = "raise") -> datetime:
    """Resolve one recurrence occurrence. Caller persists date/zone/policy as id."""
    return resolve_wall_time(local_date_time, zone, ambiguous=ambiguous)
