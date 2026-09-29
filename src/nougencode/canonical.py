"""Portable canonical JSON encoding used by content-addressed NouGen records.

Version 1 accepts JSON values, enums, and timezone-aware datetimes. Integers are
limited to the interoperable IEEE-754 safe range; floats use finite binary64
values with shortest-round-trip decimal digits and ECMAScript-compatible
fixed/scientific notation thresholds. Timestamps are UTC with fixed
microsecond precision. Unsupported Python objects are rejected rather than
silently stringified.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping


CANONICAL_JSON_VERSION = "nougen.canonical-json.v1"
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def canonical_timestamp(value: datetime) -> str:
    """Encode an aware timestamp as UTC RFC 3339 with fixed microseconds."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize_timestamp(value: str) -> str:
    """Normalize a timezone-qualified ISO timestamp to the canonical UTC form."""
    if not isinstance(value, str):
        raise ValueError("canonical timestamps must be timezone-qualified ISO strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("canonical timestamps must be timezone-qualified ISO strings") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("canonical timestamps must include a timezone")
    return canonical_timestamp(parsed)


def _float_text(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("Out of range float values are not canonical JSON compliant")
    if value == 0:
        return "0"

    # repr(float) supplies the shortest decimal that round-trips to the same
    # binary64 value. Decimal expands that spelling without changing digits.
    from decimal import Decimal

    number = Decimal(repr(value))
    magnitude = abs(value)
    if 1e-6 <= magnitude < 1e21:
        fixed = format(number, "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        return fixed

    normalized = number.normalize()
    sign = "-" if normalized.is_signed() else ""
    digits = "".join(str(digit) for digit in normalized.copy_abs().as_tuple().digits)
    exponent = normalized.copy_abs().adjusted()
    mantissa = digits[0]
    if len(digits) > 1:
        mantissa += "." + digits[1:]
    return f"{sign}{mantissa}e{'+' if exponent >= 0 else ''}{exponent}"


def _encode(value: Any) -> str:
    if isinstance(value, Enum):
        return _encode(value.value)
    if isinstance(value, datetime):
        return json.dumps(canonical_timestamp(value), ensure_ascii=False)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError("canonical JSON integer exceeds the interoperable safe range")
        return str(value)
    if isinstance(value, float):
        return _float_text(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        members = []
        for key in sorted(value):
            members.append(f"{_encode(key)}:{_encode(value[key])}")
        return "{" + ",".join(members) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return the versioned canonical JSON representation of a value."""
    return _encode(value)


def canonical_sha256(value: Any) -> str:
    """Return the lowercase SHA-256 digest of :func:`canonical_json`."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
