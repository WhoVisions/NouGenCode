"""Cadence-derived freshness: a source's TTL comes from how it actually behaves.

A fixed "stale after one hour" rule marks a slow source stale on schedule and
lets a fast source rot unnoticed. The TTL here is a robust function of the
observed update intervals, so the same observations always give the same TTL.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

_MAD_TO_SIGMA = 1.4826  # MAD -> sigma for roughly normal data


@dataclass(frozen=True)
class CadenceModel:
    median_interval_seconds: float
    robust_sigma_seconds: float
    ttl_seconds: float
    sample_count: int


def estimate_cadence(
    timestamps: Sequence[datetime],
    *,
    floor_seconds: float = 60.0,
    ceiling_seconds: float = 86_400.0 * 14,
    cadence_multiplier: float = 2.5,
    jitter_multiplier: float = 4.0,
) -> CadenceModel:
    """TTL = clip(k_c * median(interval) + k_j * 1.4826 * MAD, floor, ceiling).

    Median and MAD resist a single long outage or burst. Fewer than three
    observations is not enough to infer a cadence, so the floor applies.
    """
    stamps = sorted(timestamps)
    if len(stamps) < 3:
        return CadenceModel(floor_seconds, 0.0, floor_seconds, len(stamps))
    intervals = [max(0.0, (b - a).total_seconds()) for a, b in zip(stamps, stamps[1:])]
    median = statistics.median(intervals)
    mad = statistics.median(abs(x - median) for x in intervals)
    sigma = _MAD_TO_SIGMA * mad
    ttl = cadence_multiplier * median + jitter_multiplier * sigma
    return CadenceModel(median, sigma, min(ceiling_seconds, max(floor_seconds, ttl)), len(stamps))
