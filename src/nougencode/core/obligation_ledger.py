"""Obligation ledger (REA port P8): unknown is not pass.

A claim is only closed by a unique owner's obligation whose required fixtures are all present
and whose verifier passed with authority at least that of the original observation. Absence
of evidence never closes anything; an empty ledger is UNKNOWN, never VERIFIED. Reuses
``EvidenceState`` from the evidence kernel (VERIFIED / UNKNOWN / FAILED).

Source pattern: morluto/rea docs/reconstruction-obligation-ledgers.md (read via fleet shard
31316 on blade, 2026-10-06). Not a port of REA code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Tuple

from .evidence_kernel import EvidenceState

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
_BAD_OWNERS = {"", "shared", "any", "anyone", "unowned", "tbd", "none"}


@dataclass(frozen=True)
class Obligation:
    id: str
    claim: str
    owner: str
    required_fixtures: FrozenSet[str] = frozenset()
    observed_authority: int = 0  # authority of the observation the verifier must match


@dataclass(frozen=True)
class VerifierResult:
    obligation_id: str
    verdict: str  # pass | fail | unknown
    authority: int = 0
    fixtures: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class Closure:
    closed: bool
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class LedgerVerdict:
    state: EvidenceState
    open_ids: Tuple[str, ...]
    failed_ids: Tuple[str, ...]
    reasons: Tuple[str, ...]


@dataclass
class ObligationLedger:
    _obligations: Dict[str, Obligation] = field(default_factory=dict)
    _last: Dict[str, VerifierResult] = field(default_factory=dict)
    _closed: Dict[str, bool] = field(default_factory=dict)

    def add(self, ob: Obligation) -> None:
        if ob.id in self._obligations:
            raise ValueError(f"duplicate obligation id {ob.id!r}")
        owner = ob.owner.strip().lower()
        if owner in _BAD_OWNERS or any(c in owner for c in ",;/&") or " and " in owner:
            raise ValueError(f"obligation {ob.id!r} needs exactly one named owner, got {ob.owner!r}")
        self._obligations[ob.id] = ob
        self._closed[ob.id] = False

    def record(self, result: VerifierResult) -> Closure:
        ob = self._obligations.get(result.obligation_id)
        if ob is None:
            raise KeyError(f"unknown obligation {result.obligation_id!r}")
        if result.verdict not in (PASS, FAIL, UNKNOWN):
            raise ValueError(f"verdict must be pass|fail|unknown, got {result.verdict!r}")
        self._last[ob.id] = result
        reasons: List[str] = []
        if result.verdict != PASS:
            reasons.append(f"verdict {result.verdict}: only a pass can close an obligation")
        missing = sorted(ob.required_fixtures - result.fixtures)
        if missing:
            reasons.append(f"missing required fixtures: {', '.join(missing)}")
        if result.authority < ob.observed_authority:
            reasons.append(f"verifier authority {result.authority} below the original observation's {ob.observed_authority}")
        closed = not reasons
        self._closed[ob.id] = closed
        return Closure(closed, tuple(reasons) or ("closed: unique owner, fixtures present, comparable authority",))

    def state_of(self, obligation_id: str) -> EvidenceState:
        if self._closed[obligation_id]:
            return EvidenceState.VERIFIED
        last = self._last.get(obligation_id)
        return EvidenceState.FAILED if last is not None and last.verdict == FAIL else EvidenceState.UNKNOWN

    def verdict(self) -> LedgerVerdict:
        if not self._obligations:
            return LedgerVerdict(EvidenceState.UNKNOWN, (), (), ("no obligations: an empty ledger proves nothing",))
        failed = tuple(i for i in self._obligations if self.state_of(i) is EvidenceState.FAILED)
        open_ids = tuple(i for i in self._obligations if not self._closed[i] and i not in failed)
        if failed:
            return LedgerVerdict(EvidenceState.FAILED, open_ids, failed, (f"{len(failed)} obligation(s) failed verification",))
        if open_ids:
            return LedgerVerdict(EvidenceState.UNKNOWN, open_ids, (), (f"{len(open_ids)} obligation(s) still open",))
        return LedgerVerdict(EvidenceState.VERIFIED, (), (), ("every obligation closed",))
