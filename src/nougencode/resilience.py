"""Portable, deterministic resilience decisions over discovered evidence.

This module contains no network discovery or persistence. Runtime adapters collect
evidence from whichever capabilities are available and pass normalized values to
these pure functions. Missing or stale evidence stays UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _score_hypotheses(evidence: Sequence[Evidence]) -> tuple[dict[str, float], int]:
    # Correlated evidence gets one vote: within an independent group only the
    # strongest support and strongest contradiction count, so ten telemetry rows
    # from one source family cannot outscore two independent observations.
    # Evidence without a group is its own group.
    support: dict[tuple[str, str], float] = {}
    penalty: dict[tuple[str, str], float] = {}
    attack_groups: set[str] = set()
    for item in evidence:
        weight = min(1.0, max(0.0, item.reliability)) * min(1.0, max(0.0, item.freshness))
        pen = max(0.0, item.contradiction_penalty)
        group = item.independent_group or f"_solo:{item.source}:{item.evidence_id}"
        for hypothesis, specificity in item.specificity.items():
            contribution = weight * min(1.0, max(0.0, specificity))
            key = (hypothesis, group)
            support[key] = max(support.get(key, 0.0), contribution)
            penalty[key] = max(penalty.get(key, 0.0), pen)
            if hypothesis == "hostile_action" and contribution > 0 and item.independent_group:
                attack_groups.add(item.independent_group)
    scores: dict[str, float] = {}
    for (hypothesis, group), value in sorted(support.items()):
        scores[hypothesis] = scores.get(hypothesis, 0.0) + value - penalty[(hypothesis, group)]
    return {key: round(max(0.0, value), 12) for key, value in scores.items()}, len(attack_groups)


def _parse_utc(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


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
    domain_counts: dict[str, int] = {}
    total = serving = failed = 0
    evaluated = _parse_utc(evaluated_at)
    for row in sorted(observations, key=lambda r: r.route_id):
        all_evidence.extend(row.evidence)
        observed = _parse_utc(row.observed_at)
        fresh = bool(evaluated and observed and 0 <= (evaluated - observed).total_seconds() <= row.ttl_seconds)
        deps = tuple(sorted(set(row.dependencies)))
        if not row.expected:
            state = RouteState.NOT_EXPECTED
        else:
            total += 1
            if not fresh:
                state = RouteState.UNKNOWN
            elif row.health_ok is False or row.mcp_ok is False:
                state = RouteState.RED
                failed += 1
                for dep in deps:
                    domain_counts[dep] = domain_counts.get(dep, 0) + 1
            elif row.health_ok and row.mcp_ok:
                state = RouteState.GREEN
                serving += 1
            else:
                state = RouteState.UNKNOWN
        routes.append(RouteAssessment(row.route_id, state, deps, tuple(sorted(item.evidence_id for item in row.evidence))))

    if serving:
        decision = ResilienceDecision.DEGRADED if failed else ResilienceDecision.SERVING
    elif total and failed == total:
        decision = ResilienceDecision.UNAVAILABLE
    else:
        decision = ResilienceDecision.UNKNOWN
    domains = tuple(sorted(dep for dep, count in domain_counts.items() if count > 1))
    scores, attack_groups = _score_hypotheses(all_evidence)
    attack_classified = (
        attack_groups >= max(policy.attack_min_independent_groups, 2)
        and scores.get("hostile_action", 0.0) >= max(policy.attack_min_score, 0.0)
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
        decision=decision, routes=tuple(routes), expected_routes=total,
        serving_routes=serving, failed_routes=failed,
        blast_radius=round(failed / total, 12) if total else None,
        serving_ratio=round(serving / total, 12) if total else None,
        correlated_failure_domains=domains, hypothesis_scores=scores,
        attack_classified=attack_classified,
        mutation_allowed=mutation_allowed, mutation_reason=mutation_reason,
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
    evidence_hashes = []
    for item in sorted(observations, key=lambda row: row.route_id):
        evs = sorted(({**e.__dict__, "specificity": dict(e.specificity)} for e in item.evidence),
                     key=lambda ev: (ev["source"], ev["evidence_id"]))
        normalized_observations.append({**item.__dict__, "dependencies": sorted(set(item.dependencies)), "evidence": evs})
        evidence_hashes.extend(_hash(ev) for ev in evs)
    policy_dict = dict(policy.__dict__)
    normalized = {"observations": normalized_observations, "policy": policy_dict, "capability_graph": capability_graph}
    deterministic = {
        "protocol_version": PROTOCOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "normalized_input_hash": _hash(normalized),
        "capability_graph_hash": _hash(capability_graph),
        "evidence_hashes": sorted(evidence_hashes),
        "policy_hash": _hash(policy_dict),
        "decision": {
            **assessment.__dict__,
            "routes": tuple(dict(r.__dict__) for r in assessment.routes),
            "hypothesis_scores": dict(assessment.hypothesis_scores),
        },
        "planned_mutations": [dict(item.__dict__) for item in planned_mutations],
        "executed_mutations": list(executed_mutations),
        "validation_results": list(validation_results),
        "previous_receipt_hash": previous_receipt_hash,
    }
    canonical_decision = _canonical(deterministic)
    return {
        **deterministic,
        "canonical_decision": canonical_decision,
        "decision_hash": hashlib.sha256(canonical_decision.encode("utf-8")).hexdigest(),
        "observed_at": observed_at,
    }
