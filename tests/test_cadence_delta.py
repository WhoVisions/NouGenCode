from datetime import datetime, timedelta, timezone

from nougencode.core.cadence import estimate_cadence
from nougencode.core.delta import DeltaKind, Fact, compute_deltas

T0 = datetime(2026, 9, 29, tzinfo=timezone.utc)


def stamps(*gaps):
    out, t = [T0], T0
    for g in gaps:
        t = t + timedelta(seconds=g)
        out.append(t)
    return out


def test_ttl_scales_with_source_cadence():
    fast = estimate_cadence(stamps(*[300] * 8))
    slow = estimate_cadence(stamps(*[3600] * 8))
    assert fast.ttl_seconds == 750.0
    assert slow.ttl_seconds == 9000.0


def test_single_outage_does_not_stretch_ttl():
    steady = estimate_cadence(stamps(*[300] * 8))
    with_outage = estimate_cadence(stamps(300, 300, 300, 50_000, 300, 300, 300, 300))
    assert with_outage.ttl_seconds == steady.ttl_seconds


def test_too_few_samples_use_floor():
    assert estimate_cadence(stamps(300)).ttl_seconds == 60.0


def test_ttl_is_clipped():
    assert estimate_cadence(stamps(*[10**9] * 4), ceiling_seconds=1000).ttl_seconds == 1000


def test_unchanged_state_emits_no_delta():
    snap = {"vol1_cells": Fact("verified", "h81"), "whoart": Fact("unknown", "h0")}
    assert compute_deltas(snap, dict(snap)) == ()


def test_delta_kinds_and_stable_ids():
    before = {"a": Fact("verified", "1"), "b": Fact("verified", "1"), "c": Fact("verified", "1")}
    after = {"a": Fact("stale", "1"), "b": Fact("verified", "2"), "d": Fact("verified", "1")}
    d = {x.key: x for x in compute_deltas(before, after)}
    assert d["a"].kind is DeltaKind.STATUS_CHANGED
    assert d["b"].kind is DeltaKind.CHANGED
    assert d["c"].kind is DeltaKind.DISAPPEARED
    assert d["d"].kind is DeltaKind.ADDED
    assert d["a"].delta_id == compute_deltas(before, after)[0].delta_id


def test_first_snapshot_is_all_added():
    assert {x.kind for x in compute_deltas(None, {"a": Fact("verified", "1")})} == {DeltaKind.ADDED}
