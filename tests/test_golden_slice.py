import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nougencode.core.golden_slice import (
    CapabilityGraph,
    CoverageEnvelope,
    EventEnvelope,
    EvidenceObservation,
    MutationLedger,
    MutationRejected,
    PolicyPlanner,
    StaleFenceRejected,
    TruthResolver,
    TruthStatus,
    canonical_decision_hash,
    mutation_within_budget,
    run_golden_slice,
)
from nougencode.core.mission import Capability, MutationBudget, TaskNode


AS_OF = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)
OBSERVED_AT = "2026-09-29T15:59:30Z"


def evidence(source_id, observation_id, value=True, *, status="OBSERVED", observed_at=OBSERVED_AT, ttl=120, elapsed=None, budget=None):
    fields = dict(
        observation_id=observation_id,
        source_id=source_id,
        provenance=f"runtime:{source_id}",
        value=value if status == "OBSERVED" else None,
        status=status,
        observed_at=observed_at,
        freshness_ttl_seconds=ttl,
    )
    if elapsed is not None:
        fields["elapsed_seconds"] = elapsed
    if budget is not None:
        fields["budget_seconds"] = budget
    return EvidenceObservation(**fields)


def task():
    return TaskNode(
        id="golden-task",
        objective="assess evidence before planning",
        capability=Capability.IMPLEMENTATION,
        files_expected=["src/module.py"],
        mutation_budget=MutationBudget(max_files=1, max_added_lines=10, max_deleted_lines=10),
    )


def test_heterogeneous_worker_and_provider_fixtures_normalize_to_same_decision():
    first = CoverageEnvelope(("provider-a@node-one",), (evidence("provider-a@node-one", "evidence-a"),))
    second = CoverageEnvelope(("provider-b@node-two",), (evidence("provider-b@node-two", "evidence-b"),))

    first_result = run_golden_slice(task(), first, AS_OF)
    second_result = run_golden_slice(task(), second, AS_OF)

    assert first_result.truth.status == second_result.truth.status == TruthStatus.PASS
    assert first_result.arbiter_accepts is True
    assert first_result.decision.canonical_fields() == second_result.decision.canonical_fields()
    assert first_result.decision_hash == second_result.decision_hash
    assert first_result.coverage.to_dict()["coverage_id"] != second_result.coverage.to_dict()["coverage_id"]


def test_missing_or_stale_evidence_resolves_unknown():
    missing = CoverageEnvelope(("source-a", "source-b"), (evidence("source-a", "a"),))
    stale = CoverageEnvelope(("source-a",), (evidence("source-a", "a", observed_at="2026-09-29T15:00:00Z"),))

    assert TruthResolver.resolve(missing, AS_OF).status == TruthStatus.UNKNOWN
    assert TruthResolver.resolve(stale, AS_OF).status == TruthStatus.UNKNOWN
    assert run_golden_slice(task(), stale, AS_OF).decision.action == "UNKNOWN"
    assert run_golden_slice(task(), stale, AS_OF).arbiter_accepts is False


def test_timeout_remains_unknown_within_budget():
    timeout = CoverageEnvelope(("source-a",), (evidence("source-a", "timeout", status="TIMED_OUT", elapsed=2, budget=3),))
    result = TruthResolver.resolve(timeout, AS_OF)
    assert result.status == TruthStatus.UNKNOWN_WITHIN_BUDGET


def test_timeout_requires_time_budget_evidence():
    with pytest.raises(ValueError, match="require non-negative elapsed_seconds"):
        evidence("source-a", "timeout", status="TIMED_OUT")
    over_budget = CoverageEnvelope(("source-a",), (evidence("source-a", "timeout", status="TIMED_OUT", elapsed=4, budget=3),))
    assert TruthResolver.resolve(over_budget, AS_OF).status == TruthStatus.UNKNOWN


def test_timeout_does_not_hide_other_missing_or_ambiguous_sources():
    timeout = evidence("source-a", "timeout", status="TIMED_OUT", elapsed=2, budget=3)
    missing = CoverageEnvelope(("source-a", "source-b"), (timeout,))
    duplicate = CoverageEnvelope(("source-a",), (timeout, evidence("source-a", "second-timeout", status="TIMED_OUT", elapsed=2, budget=3)))
    assert TruthResolver.resolve(missing, AS_OF).status == TruthStatus.UNKNOWN
    assert TruthResolver.resolve(duplicate, AS_OF).status == TruthStatus.UNKNOWN


def test_fresh_conflicting_evidence_resolves_unknown():
    coverage = CoverageEnvelope(("source-a", "source-b"), (
        evidence("source-a", "a", True),
        evidence("source-b", "b", False),
    ))
    assert TruthResolver.resolve(coverage, AS_OF).status == TruthStatus.UNKNOWN


def test_existing_capability_graph_and_policy_planner_are_fail_closed():
    graph = CapabilityGraph()
    graph.record(Capability.IMPLEMENTATION, TruthResolver.resolve(
        CoverageEnvelope(("source-a",), (evidence("source-a", "a"),)), AS_OF
    ))
    decision = PolicyPlanner().plan(task(), graph)
    assert decision.action == "ROUTE"
    assert graph.to_dict() == {Capability.IMPLEMENTATION.value: "PASS"}

    unknown = CapabilityGraph()
    assert PolicyPlanner().plan(task(), unknown).action == "UNKNOWN"


def test_mutation_ledger_is_idempotent_budgeted_and_fenced():
    ledger = MutationLedger()
    budget = MutationBudget(max_files=1, max_added_lines=10, max_deleted_lines=5)
    kwargs = {
        "idempotency_key": "mission:change-1",
        "fence": 1,
        "mutation": {"file": "src/module.py", "patch_sha256": "abc"},
        "budget": budget,
        "files_changed": 1,
        "lines_added": 5,
    }
    assert ledger.apply(**kwargs) is True
    assert ledger.apply(**kwargs) is False
    assert mutation_within_budget(budget, files_changed=1, lines_added=5)
    assert not mutation_within_budget(budget, files_changed=2, lines_added=5)

    with pytest.raises(MutationRejected, match="exceeds its declared budget"):
        ledger.apply(**{**kwargs, "idempotency_key": "mission:change-2", "fence": 2, "files_changed": 2})
    with pytest.raises(StaleFenceRejected, match="not monotonic"):
        ledger.apply(**{**kwargs, "idempotency_key": "mission:change-old", "fence": 1})
    with pytest.raises(MutationRejected, match="positive integer"):
        ledger.apply(**{**kwargs, "idempotency_key": "mission:change-invalid", "fence": 0})
    with pytest.raises(MutationRejected, match="different mutation content"):
        ledger.apply(**{**kwargs, "mutation": {"file": "src/module.py", "patch_sha256": "different"}})


def test_replay_produces_identical_event_and_decision_hashes():
    coverage = CoverageEnvelope(("source-a",), (evidence("source-a", "evidence-a"),))
    first = run_golden_slice(task(), coverage, AS_OF)
    replay = run_golden_slice(task(), coverage, AS_OF)
    assert first.event.to_dict() == replay.event.to_dict()
    assert first.decision_hash == replay.decision_hash
    assert first.proof_receipt.sha256 == replay.proof_receipt.sha256
    assert len(first.proof_receipt.sha256) == 64


def test_envelope_serialization_matches_published_schema_shape():
    coverage = CoverageEnvelope(("source-a",), (evidence("source-a", "evidence-a"),))
    result = run_golden_slice(task(), coverage, AS_OF).to_dict()
    schema_path = Path(__file__).parents[1] / "src/nougencode/schemas/control-plane-golden-slice.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:nougencode:control-plane-golden-slice:1"
    assert set(result) == set(schema["$defs"]["result"]["required"])
    assert set(result["event"]) == set(schema["$defs"]["event"]["required"])
    assert set(result["coverage"]) == set(schema["$defs"]["coverage"]["required"])


def test_cli_runs_golden_slice_from_a_portable_request(tmp_path):
    request = {
        "schema_version": "1.0.0",
        "as_of": "2026-09-29T16:00:00Z",
        "task": {
            "task_id": "golden-task",
            "objective": "assess a measured capability",
            "capability": "implementation",
            "files_expected": ["src/module.py"],
            "mutation_budget": {"max_files": 1, "max_added_lines": 10, "max_deleted_lines": 10},
        },
        "coverage": {
            "expected_source_ids": ["provider-a@node-one"],
            "observations": [evidence("provider-a@node-one", "evidence-a").to_dict()],
        },
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    completed = subprocess.run(
        [sys.executable, "-m", "nougencode.cli", "golden-slice", str(request_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["truth"]["status"] == "PASS"
    assert result["decision"]["action"] == "ROUTE"
    assert result["arbiter_accepts"] is True
    assert len(result["decision_hash"]) == 64
    assert result["proof_receipt"]["source"] == "evidence_arbiter"

    request["coverage"]["observations"] = []
    request_path.write_text(json.dumps(request), encoding="utf-8")
    unknown = subprocess.run(
        [sys.executable, "-m", "nougencode.cli", "golden-slice", str(request_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert unknown.returncode == 0
    assert json.loads(unknown.stdout)["decision"]["action"] == "UNKNOWN"
    assert json.loads(unknown.stdout)["arbiter_accepts"] is False


def test_event_envelope_rejects_naive_time_and_noncanonical_values():
    with pytest.raises(ValueError, match="timezone"):
        EventEnvelope("mission", 0, "event", "2026-09-29T16:00:00", "source", {})
    with pytest.raises(ValueError, match="Out of range float values"):
        EventEnvelope("mission", 0, "event", "2026-09-29T16:00:00Z", "source", {"value": float("nan")})
