"""Deterministic contextual provider UCB routing with safety lower bounds.

Two entry points share one arm registry:

* ``select_route`` - the original bandit (reward UCB + safety lower bound). Unchanged.
* ``select_engine`` - constraint-aware engine selection (MEDEM / Torch-PIM morph,
  arXiv:2609.37399, arXiv:2609.34657): placement is a function of the observed
  workload and runtime state, not a hardcoded device.

      e* = argmin_e  a*L(e,w) + d*$(e,w) - q*Qucb(e,w)
      s.t. Capabilities(e) >= Requirements(w), Memory(e) <= Free(host(e)),
           Available(e), L(e,w) <= L_max, Qslb(e,w) >= Q_min (critical only)

  L, $ and Q are per-(arm, workload_class) estimates updated by ``observe``:
      C_{t+1} = (1 - lam) * C_t + lam * C_observed
  so the fleet learns which engine is good at what, per class of work.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    # Engine-selection metadata (optional; select_route ignores it).
    capabilities: frozenset = frozenset()
    memory_mb: float = 0.0  # resident memory the engine needs on its host
    host: str = ""  # node the engine runs on; memory is checked against this host
    available: bool = True


@dataclass(frozen=True)
class WorkloadSpec:
    """What a unit of work needs. Hard limits filter; weights rank what survives."""

    workload_class: str
    required_capabilities: frozenset = frozenset()
    max_latency_ms: Optional[float] = None
    min_quality: float = 0.0  # enforced on the quality lower bound when critical=True
    critical: bool = False
    confidence: float = 0.95  # one-sided confidence for that lower bound
    est_tokens: int = 1000
    w_latency: float = 1.0  # per second of expected latency
    w_cost: float = 1.0  # per USD of expected cost
    w_quality: float = 1.0  # per unit of optimistic quality (0..1)


@dataclass
class WorkloadStats:
    n: int = 0
    quality_sum: float = 0.0
    ewma_latency_ms: Optional[float] = None
    ewma_cost_usd: Optional[float] = None


@dataclass(frozen=True)
class EngineDecision:
    selected_provider_id: Optional[str]
    selected_model_id: Optional[str]
    objective: Optional[float]
    rationale: str
    rejected: Tuple[Tuple[str, str], ...] = ()  # (arm key, reason) for every filtered arm


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
        self._stats: Dict[Tuple[str, str], WorkloadStats] = {}

    def register_arm(
        self,
        provider_id: str,
        model_id: str,
        is_local: bool = True,
        cost_per_1k_tokens: float = 0.0,
        *,
        capabilities: Sequence[str] = (),
        memory_mb: float = 0.0,
        host: str = "",
        available: bool = True,
    ) -> None:
        key = f"{provider_id}:{model_id}"
        self._arms[key] = ProviderArm(
            provider_id=provider_id,
            model_id=model_id,
            is_local=is_local,
            cost_per_1k_tokens=cost_per_1k_tokens,
            capabilities=frozenset(capabilities),
            memory_mb=float(memory_mb),
            host=host,
            available=available,
        )

    def set_available(self, provider_id: str, model_id: str, available: bool) -> None:
        key = f"{provider_id}:{model_id}"
        if key in self._arms:
            self._arms[key] = replace(self._arms[key], available=available)

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

        self._arms[key] = replace(
            arm,
            total_calls=new_total,
            success_calls=new_success,
            cumulative_reward=new_cum,
            average_latency_ms=round(new_avg_lat, 2),
        )

    # ------------------------------------------------------------------
    # Constraint-aware engine selection
    # ------------------------------------------------------------------

    def observe(
        self,
        provider_id: str,
        model_id: str,
        workload_class: str,
        quality: float,
        latency_ms: float,
        cost_usd: Optional[float] = None,
        *,
        success: bool = True,
        ewma_lambda: float = 0.3,
    ) -> None:
        """Record one observed run: updates the global arm AND its per-class estimates."""
        key = f"{provider_id}:{model_id}"
        if key not in self._arms:
            return
        if not 0.0 < ewma_lambda <= 1.0:
            raise ValueError("ewma_lambda must be in (0, 1]")
        q = max(0.0, min(1.0, float(quality)))
        self.update(provider_id, model_id, reward=q, latency_ms=latency_ms, success=success)
        st = self._stats.setdefault((key, workload_class), WorkloadStats())
        st.n += 1
        st.quality_sum += q
        lam = ewma_lambda
        st.ewma_latency_ms = latency_ms if st.ewma_latency_ms is None else (1 - lam) * st.ewma_latency_ms + lam * latency_ms
        if cost_usd is not None:
            st.ewma_cost_usd = cost_usd if st.ewma_cost_usd is None else (1 - lam) * st.ewma_cost_usd + lam * cost_usd

    def workload_stats(self, provider_id: str, model_id: str, workload_class: str) -> Optional[WorkloadStats]:
        return self._stats.get((f"{provider_id}:{model_id}", workload_class))

    def select_engine(
        self,
        workload: WorkloadSpec,
        host_free_mb: Optional[Mapping[str, float]] = None,
    ) -> EngineDecision:
        """Pick the feasible arm with the lowest objective for this workload.

        Hard constraints are applied first and every rejection is reported, so a
        caller can see WHY an engine was skipped (unavailable, missing capability,
        no memory on its host, too slow, unproven for critical work). Unknown host
        memory or unknown latency passes: absence of a measurement is not a veto.
        """
        if not self._arms:
            raise ValueError("No provider arms registered in router")
        if not 0.0 < workload.confidence < 1.0:
            raise ValueError("confidence must be in (0, 1)")
        total = sum(st.n for (k, c), st in self._stats.items() if c == workload.workload_class)
        log_t = math.log(max(1, total) + 1)
        rejected: List[Tuple[str, str]] = []
        scored: List[Tuple[float, str, ProviderArm]] = []

        for key, arm in self._arms.items():
            if not arm.available:
                rejected.append((key, "unavailable"))
                continue
            missing = workload.required_capabilities - arm.capabilities
            if missing:
                rejected.append((key, f"missing capabilities: {', '.join(sorted(missing))}"))
                continue
            if host_free_mb is not None and arm.host in host_free_mb and arm.memory_mb > host_free_mb[arm.host]:
                rejected.append((key, f"needs {arm.memory_mb:.0f}MB, {arm.host} has {host_free_mb[arm.host]:.0f}MB free"))
                continue

            st = self._stats.get((key, workload.workload_class)) or WorkloadStats()
            n = st.n
            mu = st.quality_sum / n if n else 0.5
            radius = math.sqrt(log_t / max(1, n))
            q_ucb = mu + self.exploration_weight * radius
            # Critical gate uses a Hoeffding lower bound (a real confidence bound for a
            # mean in [0,1]), not the exploration radius: with that radius, 25 straight
            # 0.95 runs still bound at 0.23, so critical work could never be placed.
            q_slb = mu - math.sqrt(math.log(1.0 / (1.0 - workload.confidence)) / (2 * n)) if n else 0.0

            latency = st.ewma_latency_ms if st.ewma_latency_ms is not None else (arm.average_latency_ms if arm.total_calls else None)
            if workload.max_latency_ms is not None and latency is not None and latency > workload.max_latency_ms:
                rejected.append((key, f"latency {latency:.0f}ms > max {workload.max_latency_ms:.0f}ms"))
                continue
            if workload.critical and q_slb < workload.min_quality:
                rejected.append((key, f"quality lower bound {q_slb:.2f} < {workload.min_quality:.2f} (critical)"))
                continue

            cost = st.ewma_cost_usd if st.ewma_cost_usd is not None else arm.cost_per_1k_tokens * workload.est_tokens / 1000.0
            lat_s = (latency if latency is not None else arm.average_latency_ms) / 1000.0
            objective = workload.w_latency * lat_s + workload.w_cost * cost - workload.w_quality * min(q_ucb, 2.0)
            scored.append((objective, key, arm))

        if not scored:
            return EngineDecision(None, None, None, "no feasible engine for this workload", tuple(rejected))
        scored.sort(key=lambda t: (t[0], t[1]))  # key breaks ties deterministically
        objective, key, arm = scored[0]
        return EngineDecision(
            selected_provider_id=arm.provider_id,
            selected_model_id=arm.model_id,
            objective=round(objective, 6),
            rationale=f"lowest objective {objective:.4f} of {len(scored)} feasible for '{workload.workload_class}'",
            rejected=tuple(rejected),
        )
