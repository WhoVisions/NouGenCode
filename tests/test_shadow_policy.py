from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
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


@pytest.mark.parametrize("threshold", [0, 1])
def test_replayer_accepts_divergence_threshold_boundaries(threshold):
    assert ShadowPolicyReplayer(max_allowed_divergence=threshold).max_allowed_divergence == threshold


@pytest.mark.parametrize("threshold", [Decimal("0.25"), Fraction(1, 4)])
def test_replayer_accepts_real_and_decimal_threshold_types(threshold):
    assert ShadowPolicyReplayer(max_allowed_divergence=threshold).max_allowed_divergence == 0.25


def test_zero_threshold_rejects_one_divergence_and_one_threshold_accepts_it():
    now = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)
    trace = ExecutionTrace("trace-1", "session-1", "write", {}, True, now.isoformat())
    replayer = ShadowPolicyReplayer(max_allowed_divergence=0)
    replayer.register_shadow_rule(
        PolicyRule("rule-block", "1", "fixture", lambda _payload: False, now.isoformat(), 60)
    )
    accept_replayer = ShadowPolicyReplayer(max_allowed_divergence=1)
    accept_replayer.register_shadow_rule(
        PolicyRule("rule-block", "1", "fixture", lambda _payload: False, now.isoformat(), 60)
    )

    reject = replayer.replay_dataset([trace], as_of=now)
    accept = accept_replayer.replay_dataset([trace], as_of=now)

    assert reject.divergent_traces == 1
    assert reject.divergence_rate == 1.0
    assert reject.is_safe_for_rollout is False
    assert accept.is_safe_for_rollout is True


def test_predicate_errors_fail_closed_without_leaking_exception_text(caplog):
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
    report = replayer.replay_dataset([trace], as_of=now)

    assert first == second
    assert first.shadow_verdict is False
    assert first.is_divergent is True
    assert first.violated_rules == ("rule-safe:1(predicate_error)",)
    assert report.divergent_traces == 1
    assert report.is_safe_for_rollout is False
    assert "private provider response" not in repr(report)
    assert "private provider response" not in caplog.text


def test_mixed_dataset_cannot_average_away_a_predicate_error():
    now = datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc)

    def broken_predicate(payload):
        if payload["kind"] == "error":
            raise RuntimeError("private provider response")
        return True

    replayer = ShadowPolicyReplayer(max_allowed_divergence=0.75)
    replayer.register_shadow_rule(
        PolicyRule(
            "rule-safe", "1", "fixture", lambda payload: payload["kind"] in {"good", "error"},
            now.isoformat(), 60,
        )
    )
    replayer.register_shadow_rule(
        PolicyRule("rule-broken", "1", "fixture", broken_predicate, now.isoformat(), 60)
    )
    traces = [
        ExecutionTrace("good", "session-1", "write", {"kind": "good"}, True, now.isoformat()),
        ExecutionTrace("error", "session-1", "write", {"kind": "error"}, True, now.isoformat()),
    ]

    report = replayer.replay_dataset(traces, as_of=now)

    assert report.total_traces == 2
    assert report.divergent_traces == 1
    assert report.divergence_rate == 0.5
    assert report.is_safe_for_rollout is False
    assert "private provider response" not in repr(report)
