"""Information-gain TestSelector prioritizing early failure discovery and cost efficiency."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class TestMetadata:
    __test__ = False
    test_id: str
    target_files: Sequence[str]
    historical_failure_rate: float  # 0.0 to 1.0
    average_duration_ms: float
    flakiness_score: float = 0.0  # 0.0 (stable) to 1.0 (flaky)


@dataclass(frozen=True)
class SelectedTest:
    test_id: str
    information_gain: float
    rank: int
    rationale: str


def _entropy(p: float) -> float:
    """Binary Shannon entropy with epsilon clamping."""
    p_clamped = max(1e-6, min(1.0 - 1e-6, p))
    return -p_clamped * math.log2(p_clamped) - (1.0 - p_clamped) * math.log2(1.0 - p_clamped)


class InformationGainTestSelector:
    """Selects and orders tests to maximize information gain per unit compute time."""

    def __init__(
        self,
        default_failure_prior: float = 0.05,
        modified_file_boost: float = 0.45,
    ) -> None:
        self.default_failure_prior = default_failure_prior
        self.modified_file_boost = modified_file_boost

    def select_tests(
        self,
        candidates: Sequence[TestMetadata],
        modified_files: Sequence[str],
        max_duration_budget_ms: Optional[float] = None,
    ) -> Sequence[SelectedTest]:
        """Rank tests by expected information gain over duration."""
        scored: List[Tuple[float, TestMetadata, str]] = []
        mod_set = set(modified_files)

        for tm in candidates:
            # Check overlap with modified files
            overlap = any(f in mod_set for f in tm.target_files)
            
            # Prior probability of failure adjusted by file changes
            p_fail = tm.historical_failure_rate
            if overlap:
                p_fail = min(0.95, p_fail + self.modified_file_boost)
            else:
                p_fail = max(self.default_failure_prior, p_fail)

            # Raw entropy
            h = _entropy(p_fail)

            # Flakiness penalty: flaky tests have lower true signal
            signal_quality = max(0.1, 1.0 - (tm.flakiness_score * 0.7))
            effective_info = h * signal_quality

            # Duration cost scaling (logarithmic penalty for high duration)
            duration_factor = max(1.0, math.log10(max(10.0, tm.average_duration_ms)))
            score = effective_info / duration_factor

            rationale = (
                f"overlap={overlap}, p_fail={p_fail:.2f}, entropy={h:.3f}, "
                f"flakiness={tm.flakiness_score:.2f}, dur={tm.average_duration_ms:.0f}ms"
            )
            scored.append((score, tm, rationale))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)

        selected: List[SelectedTest] = []
        accumulated_duration = 0.0

        for idx, (score, tm, rat) in enumerate(scored):
            if max_duration_budget_ms is not None and accumulated_duration + tm.average_duration_ms > max_duration_budget_ms:
                if selected:  # ensure at least 1 test is selected if candidates exist
                    continue
            accumulated_duration += tm.average_duration_ms
            selected.append(
                SelectedTest(
                    test_id=tm.test_id,
                    information_gain=round(score, 4),
                    rank=idx + 1,
                    rationale=rat,
                )
            )

        return tuple(selected)
