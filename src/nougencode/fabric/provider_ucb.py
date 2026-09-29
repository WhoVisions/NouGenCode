"""Deterministic contextual provider UCB routing with safety lower bounds."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ProviderArm:
    provider_id: str
    model_id: str
    is_local: bool = True
    total_calls: int = 0
    success_calls: int = 0
    cumulative_reward: float = 0.0
    average_latency_ms: float = 100.0
    cost_per_1k_tokens: float = 0.0


@dataclass(frozen=True)
class RouteDecision:
    selected_provider_id: str
    selected_model_id: str
    ucb_score: float
    safety_lower_bound: float
    is_fallback: bool
    rationale: str


class ContextualProviderUCB:
    """Multi-armed contextual bandit with safety lower bounds for model routing."""

    def __init__(
        self,
        exploration_weight: float = 1.414,
        safety_floor: float = 0.40,
        safety_beta: float = 2.0,
    ) -> None:
        self.exploration_weight = exploration_weight
        self.safety_floor = safety_floor
        self.safety_beta = safety_beta
        self._arms: Dict[str, ProviderArm] = {}

    def register_arm(
        self,
        provider_id: str,
        model_id: str,
        is_local: bool = True,
        cost_per_1k_tokens: float = 0.0,
    ) -> None:
        key = f"{provider_id}:{model_id}"
        self._arms[key] = ProviderArm(
            provider_id=provider_id,
            model_id=model_id,
            is_local=is_local,
            cost_per_1k_tokens=cost_per_1k_tokens,
        )

    def select_route(
        self,
        task_complexity: str = "medium",  # simple, medium, complex, critical
        enforce_safety: bool = True,
    ) -> RouteDecision:
        """Select best model arm balancing reward, exploration, and safety lower bounds."""
        if not self._arms:
            raise ValueError("No provider arms registered in router")

        total_trials = sum(arm.total_calls for arm in self._arms.values())
        total_trials_safe = max(1, total_trials)

        best_arm: Optional[ProviderArm] = None
        best_ucb: float = -float("inf")
        best_slb: float = 0.0
        best_rationale: str = ""

        # First pass: try untried arms if task is not critical
        if task_complexity != "critical":
            for arm in self._arms.values():
                if arm.total_calls == 0 and arm.is_local:
                    return RouteDecision(
                        selected_provider_id=arm.provider_id,
                        selected_model_id=arm.model_id,
                        ucb_score=1.0,
                        safety_lower_bound=1.0,
                        is_fallback=False,
                        rationale="Initial exploration of unvisited local arm",
                    )

        # Calculate UCB and SLB for each arm
        eligible_arms: List[Tuple[ProviderArm, float, float]] = []

        for arm in self._arms.values():
            n = max(1, arm.total_calls)
            mu = arm.cumulative_reward / n if arm.total_calls > 0 else 0.5
            
            # Confidence interval
            radius = self.exploration_weight * math.sqrt(math.log(total_trials_safe + 1) / n)
            ucb = mu + radius
            slb = mu - (self.safety_beta * math.sqrt(math.log(total_trials_safe + 1) / n))

            # Safety gate
            if enforce_safety and slb < self.safety_floor and not arm.is_local:
                # Arm failed safety lower bound
                continue

            eligible_arms.append((arm, ucb, slb))

        # If all non-local failed safety, pick best local
        if not eligible_arms:
            local_arms = [a for a in self._arms.values() if a.is_local]
            chosen = local_arms[0] if local_arms else list(self._arms.values())[0]
            return RouteDecision(
                selected_provider_id=chosen.provider_id,
                selected_model_id=chosen.model_id,
                ucb_score=0.5,
                safety_lower_bound=self.safety_floor,
                is_fallback=True,
                rationale="Fallback to trusted local provider (safety lower bound triggered)",
            )

        # Sort eligible arms by UCB score
        eligible_arms.sort(key=lambda x: x[1], reverse=True)
        best_arm, best_ucb, best_slb = eligible_arms[0]

        return RouteDecision(
            selected_provider_id=best_arm.provider_id,
            selected_model_id=best_arm.model_id,
            ucb_score=round(best_ucb, 4),
            safety_lower_bound=round(best_slb, 4),
            is_fallback=False,
            rationale=f"Selected optimal arm via UCB ({best_ucb:.3f}) with SLB ({best_slb:.3f})",
        )

    def update(
        self,
        provider_id: str,
        model_id: str,
        reward: float,  # 0.0 to 1.0
        latency_ms: float,
        success: bool = True,
    ) -> None:
        """Update arm statistics with observed reward and latency."""
        key = f"{provider_id}:{model_id}"
        arm = self._arms.get(key)
        if not arm:
            return

        new_total = arm.total_calls + 1
        new_success = arm.success_calls + (1 if success else 0)
        new_cum = arm.cumulative_reward + max(0.0, min(1.0, float(reward)))
        new_avg_lat = ((arm.average_latency_ms * arm.total_calls) + latency_ms) / new_total

        self._arms[key] = ProviderArm(
            provider_id=arm.provider_id,
            model_id=arm.model_id,
            is_local=arm.is_local,
            total_calls=new_total,
            success_calls=new_success,
            cumulative_reward=new_cum,
            average_latency_ms=round(new_avg_lat, 2),
            cost_per_1k_tokens=arm.cost_per_1k_tokens,
        )
