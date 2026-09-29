"""Deterministic fanout governor for concurrent task graph execution."""

from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class FanoutGovernor:
    """Bounds each execution wave and keeps selection stable for equal inputs."""

    max_parallel_tasks: int = 1

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be at least one")

    def select_wave(self, ready: Sequence[T]) -> tuple[T, ...]:
        """Select the first bounded wave; the caller preserves graph order."""
        return tuple(ready[: self.max_parallel_tasks])
