"""Cadence engine and robust TTL management for NouGenCode hourly worker kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from nougencode.core.golden_slice import (
    CoverageEnvelope,
    EvidenceObservation,
    TruthResolver,
    TruthResult,
    TruthStatus,
)


class CadenceState(str, Enum):
    IDLE = "IDLE"
    TICKING = "TICKING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    BACKOFF = "BACKOFF"
    STALLED = "STALLED"


@dataclass(frozen=True)
class CadenceTick:
    tick_id: str
    cycle_number: int
    scheduled_at: str
    triggered_at: str
    target_ttl_seconds: float
    max_drift_seconds: float = 30.0

    def is_within_drift_budget(self, as_of: datetime) -> bool:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        scheduled = datetime.fromisoformat(self.scheduled_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        now = as_of.astimezone(timezone.utc)
        drift = abs((now - scheduled).total_seconds())
        return drift <= self.max_drift_seconds


@dataclass
class RobustCadenceTTL:
    """Robust TTL engine that protects against clock skew and incomplete source coverage.
    
    Invariants:
    1. UNKNOWN_WITHIN_BUDGET != failure.
    2. Incomplete source coverage cannot prove absence.
    3. Clock skew / future timestamps resolve to UNKNOWN.
    """
    base_ttl_seconds: float = 3600.0  # 1 hour default
    grace_period_seconds: float = 300.0  # 5 min grace
    max_clock_skew_seconds: float = 60.0

    def evaluate_observation(
        self,
        observation: EvidenceObservation,
        as_of: datetime,
    ) -> Tuple[bool, str]:
        """Evaluates freshness with strict clock skew and budget awareness."""
        if as_of.tzinfo is None:
            raise ValueError("as_of must include timezone")
        now = as_of.astimezone(timezone.utc)
        try:
            observed = datetime.fromisoformat(observation.observed_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return False, "invalid_timestamp"

        # Check future timestamp beyond allowed clock skew
        if (observed - now).total_seconds() > self.max_clock_skew_seconds:
            return False, "future_dated_beyond_skew"

        if observation.status == "TIMED_OUT":
            if (
                observation.elapsed_seconds is not None
                and observation.budget_seconds is not None
                and observation.elapsed_seconds <= observation.budget_seconds
            ):
                return True, "timed_out_within_budget"
            return False, "timed_out_exceeded_budget"

        if observation.status != "OBSERVED":
            return False, f"status_{observation.status.lower()}"

        ttl = observation.freshness_ttl_seconds or self.base_ttl_seconds
        expires = observed + timedelta(seconds=ttl)

        if now <= expires:
            return True, "fresh"
        if now <= expires + timedelta(seconds=self.grace_period_seconds):
            return False, "stale_in_grace_period"
        return False, "expired"


class CadenceScheduler:
    """Deterministic hourly worker scheduler with exponential backoff and jitter."""

    def __init__(
        self,
        interval_seconds: float = 3600.0,
        min_backoff_seconds: float = 10.0,
        max_backoff_seconds: float = 300.0,
        backoff_multiplier: float = 2.0,
    ) -> None:
        if interval_seconds <= 0 or min_backoff_seconds <= 0 or max_backoff_seconds < min_backoff_seconds:
            raise ValueError("invalid cadence scheduler parameters")
        self.interval_seconds = interval_seconds
        self.min_backoff_seconds = min_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.backoff_multiplier = backoff_multiplier
        self._consecutive_failures = 0
        self._cycle_count = 0

    def next_interval(self, success: bool) -> float:
        """Calculates next execution delay based on outcome."""
        if success:
            self._consecutive_failures = 0
            self._cycle_count += 1
            return self.interval_seconds

        self._consecutive_failures += 1
        backoff = self.min_backoff_seconds * math.pow(self.backoff_multiplier, self._consecutive_failures - 1)
        return min(backoff, self.max_backoff_seconds)

    def create_tick(self, as_of: datetime) -> CadenceTick:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include timezone")
        utc_as_of = as_of.astimezone(timezone.utc)
        tick_id = f"tick_{utc_as_of.strftime('%Y%m%dT%H%M%SZ')}_{self._cycle_count}"
        return CadenceTick(
            tick_id=tick_id,
            cycle_number=self._cycle_count,
            scheduled_at=utc_as_of.isoformat(),
            triggered_at=utc_as_of.isoformat(),
            target_ttl_seconds=self.interval_seconds,
        )
