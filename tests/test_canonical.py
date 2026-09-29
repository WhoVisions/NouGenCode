from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path

import pytest

from nougencode.canonical import canonical_json, canonical_sha256, canonical_timestamp, normalize_timestamp
from nougencode.core.golden_slice import EventEnvelope


def test_canonical_json_orders_keys_and_uses_portable_float_spellings():
    assert canonical_json({"z": -0.0, "b": 1e-7, "a": 1e-6, "c": 1e20}) == (
        '{"a":0.000001,"b":1e-7,"c":100000000000000000000,"z":0}'
    )


def test_canonical_json_normalizes_aware_timestamps_to_fixed_utc():
    source = datetime(2026, 9, 29, 13, 0, 1, 20, tzinfo=timezone(timedelta(hours=-4)))
    assert canonical_timestamp(source) == "2026-09-29T17:00:01.000020Z"
    assert canonical_json({"observed_at": source}) == '{"observed_at":"2026-09-29T17:00:01.000020Z"}'
    assert normalize_timestamp("2026-09-29T13:00:01.000020-04:00") == "2026-09-29T17:00:01.000020Z"


def test_canonical_json_rejects_ambiguous_or_nonportable_values():
    with pytest.raises(ValueError, match="timezone"):
        canonical_timestamp(datetime(2026, 9, 29))
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_json(float("nan"))
    with pytest.raises(ValueError, match="safe range"):
        canonical_json(9_007_199_254_740_992)
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_json({1: "not portable"})


def test_canonical_json_supports_enums_and_hash_is_stable():
    class State(Enum):
        READY = "ready"

    payload = {"state": State.READY, "attempt": 2}
    assert canonical_json(payload) == '{"attempt":2,"state":"ready"}'
    assert canonical_sha256(payload) == canonical_sha256({"state": "ready", "attempt": 2})


def test_event_identity_is_independent_of_equivalent_timestamp_offsets():
    utc = EventEnvelope("mission", 1, "probe", "2026-09-29T17:00:00Z", "source", {})
    offset = EventEnvelope("mission", 1, "probe", "2026-09-29T13:00:00-04:00", "source", {})
    assert utc.to_dict()["event_id"] == offset.to_dict()["event_id"]


def test_shared_canonical_v1_vectors():
    """Language-neutral vectors keep canonical bytes stable across runtimes."""
    fixture_path = Path(__file__).parent / "fixtures" / "canonical-json-v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["canonical_version"] == "nougen.canonical-json.v1"
    for vector in fixture["vectors"]:
        assert canonical_json(vector["value"]) == vector["canonical_json"], vector["id"]
        assert canonical_sha256(vector["value"]) == vector["sha256"], vector["id"]

    for vector in fixture["timestamps"]:
        assert normalize_timestamp(vector["input"]) == vector["canonical"], vector["input"]
