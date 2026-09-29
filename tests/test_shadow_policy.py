from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from nougencode.fabric.shadow_policy import (
    ExecutionTrace,
    PolicyRule,
    ShadowPolicyReplayer,
)


def test_empty_versioned_replay_fixture_does_not_approve_rollout():
    fixture_path = Path(__file__).parent / "fixtures" / "shadow-replay-empty-v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "nougen.shadow-replay.v1"

    report = ShadowPolicyReplayer().replay_dataset(fixture["traces"])

    assert report.total_traces == fixture["expected"]["total_traces"]
    assert report.divergent_traces == fixture["expected"]["divergent_traces"]
    assert report.is_safe_for_rollout is fixture["expected"]["is_safe_for_rollout"]


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan"), float("inf"), 10**1000, True])
def test_replayer_rejects_invalid_divergence_threshold(threshold):
    with pytest.raises(ValueError, match="finite number from 0 to 1"):
        ShadowPolicyReplayer(max_allowed_divergence=threshold)


def test_predicate_errors_fail_closed_without_leaking_exception_text():
    now = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)

    def broken_predicate(_payload):
        raise RuntimeError("private provider response")

    replayer = ShadowPolicyReplayer()
    replayer.register_shadow_rule(
        PolicyRule(
            rule_id="rule-safe",
            version="1",
            description="fixture predicate",
            predicate=broken_predicate,
            created_at=now.isoformat(),
            ttl_seconds=60,
        )
    )
    trace = ExecutionTrace("trace-1", "session-1", "write", {}, True, now.isoformat())

    first = replayer.evaluate_trace(trace, as_of=now)
    second = replayer.evaluate_trace(trace, as_of=now)

    assert first == second
    assert first.shadow_verdict is False
    assert first.is_divergent is True
    assert first.violated_rules == ("rule-safe:1(predicate_error)",)
