"""Material-delta engine: report what changed, never repeat what did not.

Two snapshots compare by (status, value hash) per key. An unchanged key emits
nothing, so a periodic sweep over an unchanged system produces an empty delta
instead of the same paragraph every interval.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Mapping, Optional, Tuple


class DeltaKind(str, Enum):
    ADDED = "added"
    CHANGED = "changed"
    STATUS_CHANGED = "status_changed"
    DISAPPEARED = "disappeared"


@dataclass(frozen=True)
class Fact:
    status: str
    value_hash: str


@dataclass(frozen=True)
class Delta:
    key: str
    kind: DeltaKind
    before: Optional[Fact]
    after: Optional[Fact]

    @property
    def delta_id(self) -> str:
        """Stable id: replaying the same change yields the same id (idempotent)."""
        b = self.before or Fact("", "")
        a = self.after or Fact("", "")
        raw = "|".join((self.key, self.kind.value, b.status, b.value_hash, a.status, a.value_hash))
        return sha256(raw.encode()).hexdigest()


def compute_deltas(
    before: Optional[Mapping[str, Fact]],
    after: Mapping[str, Fact],
) -> Tuple[Delta, ...]:
    old = before or {}
    out = []
    for key in sorted(set(old) | set(after)):
        b, a = old.get(key), after.get(key)
        if b is None:
            out.append(Delta(key, DeltaKind.ADDED, None, a))
        elif a is None:
            out.append(Delta(key, DeltaKind.DISAPPEARED, b, None))
        elif b.status != a.status:
            out.append(Delta(key, DeltaKind.STATUS_CHANGED, b, a))
        elif b.value_hash != a.value_hash:
            out.append(Delta(key, DeltaKind.CHANGED, b, a))
    return tuple(out)
