"""Deterministic fixtures for the portable Flash Kick resilience plane."""

from nougencode.resilience import (
    Evidence,
    collect_adapter_evidence,
    MutationProposal,
    ResilienceDecision,
    ResiliencePolicy,
    RouteObservation,
    RouteState,
    assess_resilience,
    make_proof_receipt,
)


NOW = "2026-09-29T15:30:00+00:00"


def observation(route, *, health=True, mcp=True, observed=NOW, dependencies=(), evidence=(), ttl=300):
    return RouteObservation(
        route_id=route,
        expected=True,
        observed_at=observed,
        ttl_seconds=ttl,
        health_ok=health,
        mcp_ok=mcp,
        dependencies=tuple(dependencies),
        evidence=tuple(evidence),
    )


def test_three_green_one_red_keeps_federation_serving_and_reports_blast_radius():
    rows = [observation(f"route-{i}") for i in range(3)]
    rows.append(observation("route-red", health=False, mcp=False))

    result = assess_resilience(rows, evaluated_at=NOW)

    assert result.decision == ResilienceDecision.DEGRADED
    assert (result.expected_routes, result.serving_routes, result.failed_routes) == (4, 3, 1)
    assert result.blast_radius == 0.25
    assert result.serving_ratio == 0.75


def test_stale_or_invalid_time_evidence_becomes_unknown():
    result = assess_resilience(
        [observation("stale", observed="2026-09-29T15:00:00+00:00", ttl=60)],
        evaluated_at=NOW,
    )

    assert result.routes[0].state == RouteState.UNKNOWN
    assert result.decision == ResilienceDecision.UNKNOWN
    assert result.blast_radius is None or result.blast_radius == 0.0


def test_shared_dependency_is_reported_as_correlated_fault_domain():
    rows = [
        observation("a", health=False, mcp=False, dependencies=("dependency.shared",)),
        observation("b", health=False, mcp=False, dependencies=("dependency.shared",)),
        observation("c"),
    ]

    result = assess_resilience(rows, evaluated_at=NOW)

    assert result.correlated_failure_domains == ("dependency.shared",)
    assert result.decision == ResilienceDecision.DEGRADED


def test_single_503_signal_never_infers_hostile_action_or_opens_mutation_gate():
    signal = Evidence(
        evidence_id="origin-503",
        source="health-probe",
        kind="origin_503",
        observed_at=NOW,
        specificity={"runtime_fault": 0.9},
        independent_group="route-probe",
    )
    result = assess_resilience(
        [observation("route", health=False, mcp=False, evidence=(signal,))],
        evaluated_at=NOW,
        policy=ResiliencePolicy(
            authorized_mutation_kinds=("restart",), mutation_min_confidence=0.8
        ),
        mutation=MutationProposal(
            kind="restart", description="restart service", authorized=True,
            rollback_plan="restore previous process", verification=("health", "mcp"),
        ),
    )

    assert result.hypothesis_scores["runtime_fault"] == 0.9
    assert result.attack_classified is False
    assert result.mutation_allowed is True


def test_attack_requires_multiple_independent_signals_and_receipt_is_canonical():
    signals = (
        Evidence("a", "source-a", "auth-anomaly", NOW, specificity={"hostile_action": 0.7}, independent_group="a"),
        Evidence("b", "source-b", "integrity-change", NOW, specificity={"hostile_action": 0.7}, independent_group="b"),
    )
    rows = [observation("route", health=False, mcp=False, evidence=signals)]
    policy = ResiliencePolicy(attack_min_score=1.0)
    assessment = assess_resilience(rows, evaluated_at=NOW, policy=policy)
    assert assessment.attack_classified is True

    left = make_proof_receipt(
        observations=rows, policy=policy, assessment=assessment,
        capability_graph={"capabilities": ["health", "mcp"]}, observed_at=NOW,
    )
    right = make_proof_receipt(
        observations=list(reversed(rows)), policy=policy, assessment=assessment,
        capability_graph={"capabilities": ["health", "mcp"]}, observed_at="2026-09-29T15:31:00+00:00",
    )
    assert left["canonical_decision"] == right["canonical_decision"]
    assert left["decision_hash"] == right["decision_hash"]
    assert left["observed_at"] != right["observed_at"]


def test_evidence_adapters_are_replaceable_and_optional_failures_are_explicit():
    signal = Evidence("probe", "adapter", "health", NOW)

    class Adapter:
        adapter_id = "runtime.capability"
        capabilities = ("health", "mcp")

        def collect_resilience_evidence(self, scope):
            return (signal,)

    class OfflineAdapter:
        adapter_id = "optional.persistence"
        capabilities = ("memory",)

        def collect_resilience_evidence(self, scope):
            raise TimeoutError

    gathered = collect_adapter_evidence([OfflineAdapter(), Adapter()], {"scope": "fixture"})
    assert gathered.capability_graph == {
        "optional.persistence": ("memory",),
        "runtime.capability": ("health", "mcp"),
    }
    assert gathered.evidence == (signal,)
    assert gathered.unavailable_adapters == ("optional.persistence",)


def test_correlated_evidence_gets_one_vote():
    from nougencode.resilience import Evidence, _score_hypotheses

    def row(i, group):
        return Evidence(
            evidence_id=f"e{i}", source="telemetry", kind="http_503",
            observed_at="2026-09-29T00:00:00Z",
            specificity={"upstream_outage": 0.5}, independent_group=group,
        )

    one_family = [row(i, "cf-edge") for i in range(10)]
    two_families = [row(0, "cf-edge"), row(1, "origin-probe")]
    correlated, _ = _score_hypotheses(one_family)
    independent, _ = _score_hypotheses(two_families)
    assert correlated["upstream_outage"] == 0.5
    assert independent["upstream_outage"] == 1.0
