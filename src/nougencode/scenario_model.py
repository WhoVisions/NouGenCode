"""Evidence-bounded scenario state and action selection primitives."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Callable, Sequence


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class Feat:
    subject: str
    continuity: str
    source: str
    locator: str
    observed_action: str
    conditions: tuple[str, ...] = ()
    measured_value: float | None = None
    unit: str | None = None


def comparable(a: Feat, b: Feat) -> bool:
    """Unit compatibility allows comparison; it does not normalize conditions."""
    return (a.measured_value is not None and b.measured_value is not None
            and a.unit is not None and a.unit == b.unit)


@dataclass(frozen=True)
class ScenarioState:
    physical: tuple[tuple[str, float], ...]
    resources: tuple[tuple[str, float], ...]
    knowledge: frozenset[str]
    equipment: frozenset[str]
    constraints: frozenset[str]


@dataclass(frozen=True)
class Preparation:
    evidence_added: frozenset[str] = frozenset()
    equipment_added: frozenset[str] = frozenset()
    resource_cost: tuple[tuple[str, float], ...] = ()
    time_cost_seconds: float = 0.0


def apply_preparation(state: ScenarioState, prep: Preparation) -> ScenarioState:
    """Apply only explicit observed results and affordable declared costs."""
    if prep.time_cost_seconds < 0 or any(value < 0 for _, value in prep.resource_cost):
        raise ScenarioError("preparation costs must be non-negative")
    available = dict(state.resources)
    for resource, cost in prep.resource_cost:
        if available.get(resource, 0.0) < cost:
            raise ScenarioError(f"insufficient resource: {resource}")
        available[resource] = available.get(resource, 0.0) - cost
    return ScenarioState(state.physical, tuple(sorted(available.items())),
                         state.knowledge | prep.evidence_added,
                         state.equipment | prep.equipment_added, state.constraints)


@dataclass(frozen=True)
class Outcome:
    label: str
    probability: float
    utility: float


@dataclass(frozen=True)
class Action:
    action_id: str
    requires_knowledge: frozenset[str] = frozenset()
    requires_equipment: frozenset[str] = frozenset()
    consumes: tuple[tuple[str, float], ...] = ()
    outcomes: tuple[Outcome, ...] = ()


@dataclass(frozen=True)
class PlanEstimate:
    plan_id: str
    quality: float
    seconds: float
    cost: float
    failure_probability: float
    authorized: bool
    capable: bool


@dataclass(frozen=True)
class PlanPolicy:
    max_seconds: float
    max_cost: float
    time_weight: float
    cost_weight: float
    failure_weight: float


def expected_utility(action: Action, state: ScenarioState) -> float:
    """Return expected utility only for feasible actions with a valid model."""
    if not action.requires_knowledge <= state.knowledge:
        raise ScenarioError("action depends on unknown evidence")
    if not action.requires_equipment <= state.equipment:
        raise ScenarioError("required equipment is unavailable")
    resources = dict(state.resources)
    if any(value < 0 or resources.get(name, 0.0) < value for name, value in action.consumes):
        raise ScenarioError("action exceeds remaining resources")
    if not action.outcomes or any(not 0 <= row.probability <= 1 for row in action.outcomes):
        raise ScenarioError("outcome probabilities must be declared in [0, 1]")
    if abs(sum(row.probability for row in action.outcomes) - 1.0) > 1e-9:
        raise ScenarioError("outcome probabilities must sum to 1")
    return sum(row.probability * row.utility for row in action.outcomes)


def choose_action(actions: Sequence[Action], state: ScenarioState) -> tuple[Action, float]:
    """Pick the feasible action with greatest declared expected utility."""
    scored: list[tuple[Action, float]] = []
    for action in actions:
        try:
            scored.append((action, expected_utility(action, state)))
        except ScenarioError:
            continue
    if not scored:
        raise ScenarioError("no feasible action has a declared outcome model")
    return max(scored, key=lambda item: item[1])


def choose_plan(plans: Sequence[PlanEstimate], policy: PlanPolicy) -> PlanEstimate | None:
    """Select among feasible, finite estimates using declared normalized costs.

    All feasible estimates are evaluated by an upstream source. This function
    does not certify their accuracy and returns None when no plan qualifies.
    """
    limits = (policy.max_seconds, policy.max_cost)
    weights = (policy.time_weight, policy.cost_weight, policy.failure_weight)
    if any(not isfinite(v) or v <= 0 for v in limits):
        raise ScenarioError("time and cost maxima must be positive finite values")
    if any(not isfinite(v) or v < 0 for v in weights):
        raise ScenarioError("plan weights must be non-negative finite values")
    ranked: list[tuple[float, PlanEstimate]] = []
    for plan in plans:
        fields = (plan.quality, plan.seconds, plan.cost, plan.failure_probability)
        if not all(isfinite(v) for v in fields):
            continue
        if not plan.authorized or not plan.capable:
            continue
        if plan.seconds < 0 or plan.cost < 0 or not 0 <= plan.failure_probability <= 1:
            continue
        if plan.seconds > policy.max_seconds or plan.cost > policy.max_cost:
            continue
        score = (plan.quality - policy.time_weight * plan.seconds / policy.max_seconds
                 - policy.cost_weight * plan.cost / policy.max_cost
                 - policy.failure_weight * plan.failure_probability)
        ranked.append((score, plan))
    return max(ranked, key=lambda row: row[0])[1] if ranked else None
