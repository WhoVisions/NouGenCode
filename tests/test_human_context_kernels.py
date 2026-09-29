from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from nougencode.digestibility import (
    ComprehensionWeights, DigestibilityError, MeaningUnit, ReaderContext,
    comprehension_cost, partition_units, verify_plan, verify_rendering,
)
from nougencode.scenario_model import (
    Action, Feat, Outcome, PlanEstimate, PlanPolicy, Preparation,
    ScenarioError, ScenarioState, apply_preparation, choose_action,
    choose_plan, comparable,
)
from nougencode.mission_runtime import (
    MissionContract, MissionError, MissionJournal, ResourceBudget,
    StepRecord, StepStatus, verify_resume_packet,
)
from nougencode.physics_model import (
    EnergyState, PhysicsInputError, advance_energy, estimate_flight,
    estimate_impact, resolve_lift,
)
from nougencode.time_model import (
    TimeModelError, WallTimeKind, classify_wall_time, estimate_utc,
    next_daily_occurrence, resolve_wall_time, resolve_zone, Deadline,
)


def test_zone_precedence_and_fallback():
    assert resolve_zone("America/Los_Angeles", "Europe/London").source == "user"
    assert resolve_zone("bad/zone", "Europe/London").source == "machine"
    assert resolve_zone(None, "bad/zone").zone.key == "UTC"


def test_trusted_instant_requires_independent_agreement():
    now = datetime(2026, 9, 29, tzinfo=timezone.utc)
    assert not estimate_utc([("local", now)], tolerance=timedelta(seconds=2)).verified
    verified = estimate_utc([("a", now), ("b", now + timedelta(milliseconds=100))],
                            tolerance=timedelta(seconds=2))
    assert verified.verified
    assert verified.instant_utc == now + timedelta(milliseconds=50)


def test_dst_gap_and_fold_require_explicit_policy():
    zone = ZoneInfo("America/New_York")
    gap = classify_wall_time(datetime(2026, 3, 8, 2, 30), zone)
    assert gap.kind is WallTimeKind.NONEXISTENT
    with pytest.raises(TimeModelError):
        resolve_wall_time(datetime(2026, 3, 8, 2, 30), zone)
    fold = datetime(2026, 11, 1, 1, 30)
    assert classify_wall_time(fold, zone).kind is WallTimeKind.AMBIGUOUS
    with pytest.raises(TimeModelError):
        next_daily_occurrence(fold, zone)
    assert resolve_wall_time(fold, zone, ambiguous="later") - resolve_wall_time(
        fold, zone, ambiguous="earlier") == timedelta(hours=1)


def test_elapsed_deadline_uses_monotonic_value():
    deadline = Deadline.after(10, 100.0)
    assert deadline.remaining(106.0) == 4.0
    assert deadline.remaining(120.0) == 0.0


def test_partition_keeps_qualification_adjacent_and_lossless():
    units = [
        MeaningUnit("claim", "The machine clock is an estimate.", "doc#1", 7),
        MeaningUnit("caveat", "It is not externally verified.", "doc#2", 6,
                    depends_on=("claim",), qualifies=("claim",)),
        MeaningUnit("method", "Compare independent sources.", "doc#3", 5,
                    depends_on=("claim", "caveat")),
    ]
    plan = partition_units(units, max_tokens=13, target_tokens=12)
    assert verify_plan(units, plan, max_tokens=13)
    assert plan.chunks[0].unit_ids[:2] == ("claim", "caveat")
    with pytest.raises(DigestibilityError):
        partition_units([MeaningUnit("large", "cannot split", "doc", 14)], max_tokens=13)


def test_provenance_preserved_in_plan():
    units = [MeaningUnit("a", "A", "source:issue#1", 1)]
    plan = partition_units(units, max_tokens=4)
    assert plan.source_refs == ("source:issue#1",)
    assert verify_plan(units, plan, max_tokens=4)


def test_reader_cost_keeps_unknown_knowledge_unknown():
    unit = MeaningUnit("x", "Use the monotonic clock.", "doc", 5,
                       introduces_concepts=("monotonic-clock",),
                       specialist_terms=("monotonic",), decisions=1)
    new_reader = comprehension_cost([unit], ReaderContext())
    experienced = comprehension_cost([unit], ReaderContext(
        known_concepts=frozenset({"monotonic-clock"}),
        known_terms=frozenset({"monotonic"})))
    assert new_reader > experienced


def test_reader_cost_guides_chunk_boundaries():
    units = [MeaningUnit(str(i), f"Unit {i}", f"doc#{i}", 5,
                         introduces_concepts=("same-concept",)) for i in range(3)]
    plan = partition_units(units, max_tokens=10, target_tokens=10,
                           reader=ReaderContext())
    assert plan.chunks[0].unit_ids == ("0", "1")


def test_render_verification_records_semantic_checks():
    units = [MeaningUnit("instruction", "Do X.", "src#1", 2),
             MeaningUnit("caveat", "Only if Y.", "src#2", 3,
                         depends_on=("instruction",), qualifies=("instruction",))]
    verified = verify_rendering(units, missing_units=(), added_claims=(),
                                certainty_changes=(),
                                output_unit_order=("instruction", "caveat"))
    assert verified.passed
    failed = verify_rendering(units, missing_units=("caveat",), added_claims=(),
                              certainty_changes=(), output_unit_order=("caveat", "instruction"))
    assert not failed.passed


def test_preparation_changes_only_declared_state_and_costs():
    start = ScenarioState(("health", 1.0), (("time", 30.0),), frozenset(),
                          frozenset(), frozenset({"continuity:main"}))
    ready = apply_preparation(start, Preparation(frozenset({"bridge-load"}),
                            frozenset({"rope"}), (("time", 5.0),), 60.0))
    assert "bridge-load" in ready.knowledge
    assert "rope" in ready.equipment
    assert dict(ready.resources)["time"] == 25.0
    with pytest.raises(ScenarioError):
        apply_preparation(start, Preparation(resource_cost=(("time", 31.0),)))


def test_action_selection_respects_knowledge_equipment_and_probability_model():
    state = ScenarioState((), (("time", 5.0),), frozenset({"route-known"}),
                          frozenset({"rope"}), frozenset())
    actions = [
        Action("unsupported", requires_knowledge=frozenset({"weakness-known"}),
               outcomes=(Outcome("win", 1, 100),)),
        Action("rescue", requires_equipment=frozenset({"rope"}),
               consumes=(("time", 1),),
               outcomes=(Outcome("success", .8, 10), Outcome("delay", .2, 2))),
    ]
    selected, score = choose_action(actions, state)
    assert selected.action_id == "rescue"
    assert score == pytest.approx(8.4)
    with pytest.raises(ScenarioError):
        choose_action([Action("bad", outcomes=(Outcome("x", .7, 1),))], state)


def test_feat_comparison_needs_measured_compatible_units():
    a = Feat("A", "main", "issue", "p. 1", "lifted", measured_value=10, unit="kg")
    b = Feat("B", "main", "issue", "p. 2", "lifted", measured_value=12, unit="kg")
    c = Feat("C", "alt", "issue", "p. 3", "lifted", measured_value=12, unit="N")
    assert comparable(a, b)
    assert not comparable(a, c)


def test_plan_selection_filters_infeasible_or_unauthorized_options():
    policy = PlanPolicy(max_seconds=60, max_cost=5, time_weight=1,
                       cost_weight=1, failure_weight=2)
    plans = [
        PlanEstimate("blocked", 100, 10, 1, 0, False, True),
        PlanEstimate("over-budget", 100, 10, 9, 0, True, True),
        PlanEstimate("best", 8, 20, 2, .1, True, True),
        PlanEstimate("fast", 6, 5, 1, .05, True, True),
    ]
    assert choose_plan(plans, policy).plan_id == "best"
    assert choose_plan(plans[:2], policy) is None


def _mission():
    contract = MissionContract(
        "stream-1", "Preserve and index stream speech",
        ("segments-captured", "transcript-searchable"),
        (("retain_original", "true"), ("capture_scope", "authorized")),
        ("coverage-report", "persistence-receipt", "retrieval-check"),
        "user:request-1",
    )
    return contract, MissionJournal(contract, ResourceBudget((
        ("seconds", 60.0), ("tokens", 1000.0), ("dollars", 2.0),
    )))


def test_reported_success_is_not_verified_completion():
    _, journal = _mission()
    record = StepRecord("capture", "capture:segment-1", "worker-a",
                        StepStatus.REPORTED_SUCCESS,
                        output_refs=("transcript-r1",),
                        outcome_ids=("segments-captured",),
                        remaining_work=("persist",))
    assert journal.append(record)
    assert not journal.is_complete()


def test_independent_evidence_controls_completion_and_resume():
    contract, journal = _mission()
    reported = StepRecord("persist", "persist:1", "worker-a",
                          StepStatus.REPORTED_SUCCESS,
                          output_refs=("transcript-r1",),
                          outcome_ids=("transcript-searchable",))
    journal.append(reported)
    packet = journal.resume_packet("worker-b")
    assert packet["contract"] == contract.canonical()
    assert packet["reported_but_unverified"][0]["worker_id"] == "worker-a"
    assert verify_resume_packet(packet, contract)
    tampered = {**packet, "contract": {**contract.canonical(), "objective": "changed"}}
    assert not verify_resume_packet(tampered, contract)

    journal.append(StepRecord("capture", "capture:1", "worker-b", StepStatus.VERIFIED,
                              output_refs=("transcript-r1",),
                              evidence_refs=("coverage-report", "persistence-receipt"),
                              outcome_ids=("segments-captured",),
                              verification_method="read-after-write", verification_passed=True))
    journal.append(StepRecord("retrieve", "retrieve:1", "worker-b", StepStatus.VERIFIED,
                              output_refs=("search-result-1",),
                              evidence_refs=("retrieval-check",),
                              outcome_ids=("transcript-searchable",),
                              verification_method="query-and-compare", verification_passed=True))
    assert journal.is_complete()


def test_step_idempotency_survives_worker_replacement():
    _, journal = _mission()
    original = StepRecord("save", "save:segment-1", "worker-a", StepStatus.VERIFIED,
                          input_refs=("audio-1",), output_refs=("text-r1",),
                          evidence_refs=("readback-r1",), outcome_ids=("segments-captured",),
                          verification_method="read-after-write", verification_passed=True,
                          observed_result_hash="sha256:result")
    retry = StepRecord("save", "save:segment-1", "worker-b", StepStatus.VERIFIED,
                       input_refs=("audio-1",), output_refs=("text-r1",),
                       evidence_refs=("readback-r1",), outcome_ids=("segments-captured",),
                       verification_method="read-after-write", verification_passed=True,
                       observed_result_hash="sha256:result")
    assert journal.append(original)
    assert not journal.append(retry)
    changed = StepRecord("save", "save:segment-1", "worker-b", StepStatus.VERIFIED,
                         input_refs=("audio-1",), output_refs=("text-r2",),
                         evidence_refs=("readback-r2",), outcome_ids=("segments-captured",),
                         verification_method="read-after-write", verification_passed=True)
    with pytest.raises(MissionError, match="different step content"):
        journal.append(changed)


def test_resource_budget_is_idempotent_and_enforced():
    _, journal = _mission()
    first = journal.spend("operation-1", {"seconds": 12, "tokens": 300})
    retry = journal.spend("operation-1", {"tokens": 300, "seconds": 12})
    assert first.receipt_hash == retry.receipt_hash
    assert journal.spent()["seconds"] == 12
    with pytest.raises(MissionError, match="different amounts"):
        journal.spend("operation-1", {"seconds": 13})
    with pytest.raises(MissionError, match="exceeded"):
        journal.spend("operation-2", {"dollars": 3})
    with pytest.raises(MissionError, match="booleans"):
        journal.spend("operation-3", {"seconds": True})


def test_energy_balance_harvests_spends_and_clips_reserve():
    state = EnergyState(available_j=100, capacity_j=120)
    step = advance_energy(state, duration_s=10, irradiance_w_m2=2,
                          collection_area_m2=3, absorption_efficiency=.5,
                          abilities_w=2, baseline_w=1)
    assert step.harvested_j == 30
    assert step.expended_j == 30
    assert step.state.available_j == 100
    full = advance_energy(EnergyState(110, 120), duration_s=10,
                          irradiance_w_m2=2, collection_area_m2=3,
                          absorption_efficiency=1, abilities_w=0, baseline_w=0)
    assert full.state.available_j == 120
    depleted = advance_energy(EnergyState(10, 120), duration_s=10,
                              irradiance_w_m2=0, collection_area_m2=0,
                              absorption_efficiency=1, abilities_w=2, baseline_w=0)
    assert depleted.state.available_j == 0


def test_lift_model_checks_force_and_energy_separately():
    result = resolve_lift(mass_kg=100_000, height_m=10,
                          available_energy_j=20_000_000, max_force_n=1_000_000,
                          efficiency=1)
    assert result.support_force_n == pytest.approx(981_000)
    assert result.useful_work_j == pytest.approx(9_810_000)
    assert result.feasible
    assert not resolve_lift(mass_kg=100_000, height_m=10,
                            available_energy_j=20_000_000, max_force_n=500_000,
                            efficiency=1).feasible
    with pytest.raises(PhysicsInputError):
        resolve_lift(mass_kg=1, height_m=1, available_energy_j=1,
                     max_force_n=1, efficiency=0)


def test_flight_model_separates_drag_and_net_acceleration():
    estimate = estimate_flight(mass_kg=1000, thrust_n=20_000,
                               gravity_m_s2=9.81, air_density_kg_m3=1.2,
                               drag_coefficient=.3, frontal_area_m2=2,
                               speed_m_s=10)
    assert estimate.drag_force_n == pytest.approx(36)
    assert estimate.acceleration_m_s2 == pytest.approx(10.154)


def test_impact_model_needs_effective_mass_and_stopping_distance():
    estimate = estimate_impact(effective_mass_kg=80, speed_m_s=10,
                               stopping_distance_m=.5, transfer_fraction=.5)
    assert estimate.kinetic_energy_j == 4000
    assert estimate.transferred_energy_j == 2000
    assert estimate.average_force_n == 4000
    with pytest.raises(PhysicsInputError):
        estimate_impact(effective_mass_kg=80, speed_m_s=10,
                        stopping_distance_m=0)
