"""Portable, deterministic resilience decisions over discovered evidence.

This module contains no network discovery or persistence. Runtime adapters collect
evidence from whichever capabilities are available and pass normalized values to
these pure functions. Missing or stale evidence stays UNKNOWN.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Optional, Protocol, Sequence


PROTOCOL_VERSION = "nougen.resilience.v1"
SCHEMA_VERSION = "nougen.resilience.receipt.v1"


class RouteState(str, Enum):
    GREEN = "GREEN"
    RED = "RED"
    UNKNOWN = "UNKNOWN"
    NOT_EXPECTED = "NOT_EXPECTED"


class ResilienceDecision(str, Enum):
    SERVING = "SERVING"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Evidence:
    """A normalized, provenance-bearing signal supplied by a runtime adapter."""

    evidence_id: str
    source: str
    kind: str
    observed_at: str
    reliability: float = 1.0
    freshness: float = 1.0
    specificity: Mapping[str, float] = field(default_factory=dict)
    independent_group: str = ""
    contradiction_penalty: float = 0.0


@dataclass(frozen=True)
class RouteObservation:
    route_id: str
    expected: bool
    observed_at: str
    ttl_seconds: int
    health_ok: Optional[bool]
    mcp_ok: Optional[bool]
    dependencies: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class ResiliencePolicy:
    attack_min_independent_groups: int = 2
    attack_min_score: float = 1.0
    mutation_min_confidence: float = 0.75
    authorized_mutation_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class MutationProposal:
    kind: str
    description: str
    authorized: bool
    rollback_plan: str = ""
    verification: tuple[str, ...] = ()


@dataclass(frozen=True)
class RouteAssessment:
    route_id: str
    state: RouteState
    dependencies: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResilienceAssessment:
    decision: ResilienceDecision
    routes: tuple[RouteAssessment, ...]
    expected_routes: int
    serving_routes: int
    failed_routes: int
    blast_radius: Optional[float]
    serving_ratio: Optional[float]
    correlated_failure_domains: tuple[str, ...]
    hypothesis_scores: Mapping[str, float]
    attack_classified: bool
    mutation_allowed: bool
    mutation_reason: str


class EvidenceSource(Protocol):
    """Optional Shards, Relay, NouGenMsg, Tracker, or local adapter contract."""

    adapter_id: str
    capabilities: Sequence[str]

    def collect_resilience_evidence(self, scope: Mapping[str, Any]) -> Sequence[Evidence]: ...


@dataclass(frozen=True)
class CollectedEvidence:
    capability_graph: Mapping[str, tuple[str, ...]]
    evidence: tuple[Evidence, ...]
    unavailable_adapters: tuple[str, ...]


def collect_adapter_evidence(
    adapters: Sequence[EvidenceSource], scope: Mapping[str, Any]
) -> CollectedEvidence:
    """Collect optional live signals through injected adapters with provenance.

    A missing or failing integration is recorded as unavailable and contributes
    no health claim. The caller's route resolver consequently returns UNKNOWN
    when no other fresh evidence proves a state.
    """
    graph: dict[str, tuple[str, ...]] = {}
    evidence: list[Evidence] = []
    unavailable: list[str] = []
    for adapter in sorted(adapters, key=lambda item: item.adapter_id):
        key = str(adapter.adapter_id)
        graph[key] = tuple(sorted(set(str(cap) for cap in adapter.capabilities)))
        try:
            evidence.extend(adapter.collect_resilience_evidence(scope))
        except Exception:
            unavailable.append(key)
    evidence.sort(key=lambda item: (item.source, item.evidence_id))
    return CollectedEvidence(
        capability_graph=graph,
        evidence=tuple(evidence),
        unavailable_adapters=tuple(sorted(unavailable)),
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _score_hypotheses(evidence: Sequence[Evidence]) -> tuple[dict[str, float], int]:
    scores: dict[str, float] = {}
    attack_groups: set[str] = set()
    for item in sorted(evidence, key=lambda row: (row.source, row.evidence_id)):
        reliability = min(1.0, max(0.0, item.reliability))
        freshness = min(1.0, max(0.0, item.freshness))
        for hypothesis, specificity in sorted(item.specificity.items()):
            contribution = reliability * freshness * min(1.0, max(0.0, specificity))
            scores[hypothesis] = max(
                0.0,
                scores.get(hypothesis, 0.0) + contribution - max(0.0, item.contradiction_penalty),
            )
            if hypothesis == "hostile_action" and contribution > 0 and item.independent_group:
                attack_groups.add(item.independent_group)
    return {key: round(value, 12) for key, value in sorted(scores.items())}, len(attack_groups)


def _is_fresh(observed_at: str, ttl_seconds: int, evaluated_at: str) -> bool:
    """Check snapshot age using caller-supplied time; invalid clocks fail closed."""
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        evaluated = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
        if observed.tzinfo is None or evaluated.tzinfo is None or ttl_seconds < 0:
            return False
        age = (evaluated.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        return 0 <= age <= ttl_seconds
    except (TypeError, ValueError, OverflowError):
        return False


def assess_resilience(
    observations: Sequence[RouteObservation],
    *,
    evaluated_at: str,
    policy: ResiliencePolicy = ResiliencePolicy(),
    mutation: Optional[MutationProposal] = None,
) -> ResilienceAssessment:
    """Resolve route state and a bounded mutation gate from one normalized snapshot."""
    routes: list[RouteAssessment] = []
    all_evidence: list[Evidence] = []
    expected_observations = sorted((row for row in observations if row.expected), key=lambda r: r.route_id)
    for row in sorted(observations, key=lambda r: r.route_id):
        all_evidence.extend(row.evidence)
        fresh = _is_fresh(row.observed_at, row.ttl_seconds, evaluated_at)
        if not row.expected:
            state = RouteState.NOT_EXPECTED
        elif not fresh:
            state = RouteState.UNKNOWN
        elif row.health_ok is False or row.mcp_ok is False:
            state = RouteState.RED
        elif row.health_ok and row.mcp_ok:
            state = RouteState.GREEN
        else:
            state = RouteState.UNKNOWN
        routes.append(RouteAssessment(
            route_id=row.route_id,
            state=state,
            dependencies=tuple(sorted(set(row.dependencies))),
            evidence_ids=tuple(sorted(item.evidence_id for item in row.evidence)),
        ))

    expected = [row for row in routes if row.state != RouteState.NOT_EXPECTED]
    serving = sum(row.state == RouteState.GREEN for row in expected)
    failed = sum(row.state == RouteState.RED for row in expected)
    if serving:
        decision = ResilienceDecision.DEGRADED if failed else ResilienceDecision.SERVING
    elif expected and failed == len(expected):
        decision = ResilienceDecision.UNAVAILABLE
    else:
        decision = ResilienceDecision.UNKNOWN
    total = len(expected)
    red_dependencies = [dep for row in expected if row.state == RouteState.RED for dep in row.dependencies]
    domain_counts: dict[str, int] = {}
    for dependency in red_dependencies:
        domain_counts[dependency] = domain_counts.get(dependency, 0) + 1
    domains = tuple(sorted(dep for dep, count in domain_counts.items() if count > 1))
    scores, attack_groups = _score_hypotheses(all_evidence)
    attack_threshold = max(policy.attack_min_score, 0.0)
    attack_classified = (
        attack_groups >= max(policy.attack_min_independent_groups, 2)
        and scores.get("hostile_action", 0.0) >= attack_threshold
    )

    if mutation is None:
        mutation_allowed, mutation_reason = False, "no_mutation_proposed"
    elif not mutation.authorized or mutation.kind not in policy.authorized_mutation_kinds:
        mutation_allowed, mutation_reason = False, "policy_not_authorized"
    elif not mutation.rollback_plan.strip() or not mutation.verification:
        mutation_allowed, mutation_reason = False, "rollback_and_verification_required"
    elif scores.get("runtime_fault", 0.0) < policy.mutation_min_confidence:
        mutation_allowed, mutation_reason = False, "diagnostic_confidence_below_policy"
    else:
        mutation_allowed, mutation_reason = True, "authorized_reversible_plan"
    return ResilienceAssessment(
        decision=decision,
        routes=tuple(routes),
        expected_routes=total,
        serving_routes=serving,
        failed_routes=failed,
        blast_radius=round(failed / total, 12) if total else None,
        serving_ratio=round(serving / total, 12) if total else None,
        correlated_failure_domains=domains,
        hypothesis_scores=scores,
        attack_classified=attack_classified,
        mutation_allowed=mutation_allowed,
        mutation_reason=mutation_reason,
    )


def make_proof_receipt(
    *,
    observations: Sequence[RouteObservation],
    policy: ResiliencePolicy,
    assessment: ResilienceAssessment,
    capability_graph: Mapping[str, Any],
    planned_mutations: Sequence[MutationProposal] = (),
    executed_mutations: Sequence[Mapping[str, Any]] = (),
    validation_results: Sequence[Mapping[str, Any]] = (),
    observed_at: str = "",
    previous_receipt_hash: Optional[str] = None,
) -> dict[str, Any]:
    """Return a content-addressed receipt with a byte-stable canonical decision."""
    normalized_observations = []
    for item in sorted(observations, key=lambda row: row.route_id):
        row = asdict(item)
        row["evidence"] = sorted(row["evidence"], key=lambda evidence: (evidence["source"], evidence["evidence_id"]))
        row["dependencies"] = sorted(set(row["dependencies"]))
        normalized_observations.append(row)
    normalized = {
        "observations": normalized_observations,
        "policy": asdict(policy),
        "capability_graph": capability_graph,
    }
    decision = asdict(assessment)
    deterministic = {
        "protocol_version": PROTOCOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "normalized_input_hash": _hash(normalized),
        "capability_graph_hash": _hash(capability_graph),
        "evidence_hashes": sorted(_hash(asdict(item)) for row in observations for item in row.evidence),
        "policy_hash": _hash(asdict(policy)),
        "decision": decision,
        "planned_mutations": [asdict(item) for item in planned_mutations],
        "executed_mutations": list(executed_mutations),
        "validation_results": list(validation_results),
        "previous_receipt_hash": previous_receipt_hash,
    }
    canonical_decision = _canonical(deterministic).decode("utf-8")
    return {
        **deterministic,
        "canonical_decision": canonical_decision,
        "decision_hash": hashlib.sha256(canonical_decision.encode("utf-8")).hexdigest(),
        "observed_at": observed_at,
    }
