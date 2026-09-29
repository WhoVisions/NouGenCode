import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nougencode.capability_profile import (
    CapabilityProfileError,
    SCHEMA_PATH,
    capability_summary,
    validate_profile,
)


def observed(observation_id, metric, value, *, status="OBSERVED", observed_at="2026-09-29T16:00:00Z", ttl=60):
    result = {
        "observation_id": observation_id,
        "metric": metric,
        "value": value,
        "status": status,
        "observed_at": observed_at,
        "source": {"kind": "benchmark", "name": "fixture"},
        "freshness_ttl_seconds": ttl,
    }
    if status == "UNKNOWN":
        result["unknown_reason"] = "measurement was not run"
    return result


def profile_fixture():
    return {
        "schema_version": "1.0.0",
        "profile_id": "fixture-profile",
        "observed_at": "2026-09-29T16:00:00Z",
        "worker": {
            "worker_id": "fixture-worker",
            "observations": [observed("ram", "memory.total_bytes", 32000000000)],
        },
        "devices": [{
            "device_id": "device-0",
            "kind": "cuda",
            "observations": [observed("vram", "memory.total_bytes", 8000000000)],
        }],
        "capabilities": [
            {
                "workload_id": "llm-small",
                "kind": "llm",
                "result": "PASS",
                "parameters": {"quantization": "4bit"},
                "observations": [
                    observed("llm-outcome", "outcome", "PASS"),
                    observed("llm-tps", "throughput", 10, status="OBSERVED"),
                ],
            },
            {
                "workload_id": "video-small",
                "kind": "video_generation",
                "result": "UNKNOWN",
                "parameters": {"frames": 8},
                "observations": [observed("video-outcome", "outcome", None, status="UNKNOWN")],
            },
        ],
    }


def test_profile_schema_is_packaged_and_versioned():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:nougencode:scheduler-capability-profile:1"
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"


def test_profile_validation_accepts_measured_and_unknown_workloads():
    assert validate_profile(profile_fixture())["profile_id"] == "fixture-profile"


def test_profile_rejects_outcome_without_provenance():
    profile = profile_fixture()
    profile["capabilities"][0]["observations"] = []
    with pytest.raises(CapabilityProfileError, match="at least one provenance-bearing observation"):
        validate_profile(profile)


def test_profile_rejects_outcome_that_disagrees_with_the_claim():
    profile = profile_fixture()
    profile["capabilities"][0]["observations"][0]["value"] = "FAIL"
    with pytest.raises(CapabilityProfileError, match="must match its observed outcome"):
        validate_profile(profile)


def test_unknown_observation_requires_reason():
    profile = profile_fixture()
    profile["capabilities"][1]["observations"][0].pop("unknown_reason")
    with pytest.raises(CapabilityProfileError, match="unknown_reason"):
        validate_profile(profile)


def test_capability_summary_suppresses_stale_and_unknown_carry_forward():
    profile = profile_fixture()
    summary = capability_summary(profile, datetime(2026, 9, 29, 16, 2, tzinfo=timezone.utc))
    results = {item["workload_id"]: item["effective_result"] for item in summary["capabilities"]}
    assert results == {"llm-small": "UNKNOWN", "video-small": "UNKNOWN"}
    llm_observations = {item["metric"]: item for item in summary["capabilities"][0]["observations"]}
    assert llm_observations["throughput"]["value"] is None
    assert llm_observations["throughput"]["status"] == "UNKNOWN"


def test_capability_summary_preserves_fresh_outcome_and_unknown_video():
    summary = capability_summary(profile_fixture(), datetime(2026, 9, 29, 16, 0, 30, tzinfo=timezone.utc))
    results = {item["workload_id"]: item["effective_result"] for item in summary["capabilities"]}
    assert results == {"llm-small": "PASS", "video-small": "UNKNOWN"}


def test_future_dated_observation_resolves_unknown():
    profile = profile_fixture()
    summary = capability_summary(profile, datetime(2026, 9, 29, 15, 59, tzinfo=timezone.utc))
    assert summary["capabilities"][0]["effective_result"] == "UNKNOWN"


def test_recommendation_must_reference_captured_evidence():
    profile = profile_fixture()
    profile["recommendations"] = [{
        "workload_id": "llm-small",
        "decision": "ROUTE",
        "evidence_ids": ["missing-observation"],
    }]
    with pytest.raises(CapabilityProfileError, match="reference missing evidence"):
        validate_profile(profile)


def test_recommendation_resolves_unknown_when_its_evidence_expires():
    profile = profile_fixture()
    profile["recommendations"] = [{
        "workload_id": "llm-small",
        "decision": "ROUTE",
        "evidence_ids": ["llm-outcome"],
    }]
    summary = capability_summary(profile, datetime(2026, 9, 29, 16, 2, tzinfo=timezone.utc))
    assert summary["recommendations"] == [{
        "workload_id": "llm-small",
        "declared_decision": "ROUTE",
        "effective_decision": "UNKNOWN",
        "evidence_ids": ["llm-outcome"],
    }]


def test_cli_emits_deterministic_json_and_rejects_invalid_profile(tmp_path):
    source = tmp_path / "profile.json"
    source.write_text(json.dumps(profile_fixture()), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "nougencode.cli", "capability-profile", "validate", str(source), "--as-of", "2026-09-29T16:00:30Z"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    decoded = json.loads(result.stdout)
    assert decoded["worker_id"] == "fixture-worker"
    assert decoded["capabilities"][0]["effective_result"] == "PASS"

    source.write_text("{}", encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, "-m", "nougencode.cli", "capability-profile", "validate", str(source)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert failed.returncode == 2
    assert "schema_version" in failed.stderr
