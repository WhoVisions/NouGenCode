"""Top .001% Deterministic Truth & Evidence Kernel for NouGen.

Implements the canonical 2026 mathematical models:
1. EventEnvelope & Canonical Hashing
2. CoverageEnvelope & Absence-is-Provable Logic
3. TruthResolver (3-Valued Multi-Observation Arbiter)
4. Monotonic Fencing & Cadence Lease (Anti-Zombie Mutation Guard)
5. ChangeContract & ProofReceipt (Cryptographic PoE Hash Chaining)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple


class EvidenceState(str, Enum):
    VERIFIED = "verified"
    OBSERVED = "observed"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True)
class Provenance:
    source_type: str
    source_id: str
    node_id: Optional[str] = None
    provider: Optional[str] = None
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class EventEnvelope:
    """Canonical observation unit across all NouGen planes."""
    schema_version: str
    event_type: str
    subject: str
    state: EvidenceState
    payload: Mapping[str, Any]
    provenance: Provenance
    correlation_id: str
    causation_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    tags: Tuple[str, ...] = field(default_factory=tuple)

    def canonical_hash(self) -> str:
        """Deterministic SHA-256 hash invariant across machines and transports."""
        payload_items = tuple(sorted((str(k), str(v)) for k, v in self.payload.items()))
        canonical_repr = (
            self.schema_version,
            self.event_type,
            self.subject,
            self.state.value,
            payload_items,
            self.provenance.source_type,
            self.provenance.source_id,
            self.correlation_id,
        )
        return sha256(repr(canonical_repr).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CoverageEnvelope:
    """Explicitly tracks queried vs successful sources to prevent negative hallucination."""
    expected_sources: FrozenSet[str]
    queried_sources: FrozenSet[str]
    successful_sources: FrozenSet[str]
    failed_sources: FrozenSet[str]
    timed_out_sources: FrozenSet[str]

    @property
    def complete(self) -> bool:
        return (
            self.expected_sources == self.successful_sources
            and not self.failed_sources
            and not self.timed_out_sources
        )

    @property
    def absence_is_provable(self) -> bool:
        """Absence can ONLY be proven if 100% of expected sources responded successfully."""
        return self.complete


@dataclass(frozen=True)
class Decision:
    state: EvidenceState
    confidence: float
    reasons: Tuple[str, ...]
    evidence_hashes: Tuple[str, ...]
    canonical_hash: str


class TruthResolver:
    """Resolves multi-observation evidence under partial or complete coverage."""

    def resolve(
        self,
        observations: List[EventEnvelope],
        coverage: CoverageEnvelope,
    ) -> Decision:
        if not observations:
            if coverage.absence_is_provable:
                reasons = ("complete coverage produced zero observations",)
                d_hash = sha256(("VERIFIED:ABSENCE:" + repr(reasons)).encode()).hexdigest()
                return Decision(
                    state=EvidenceState.VERIFIED,
                    confidence=1.0,
                    reasons=reasons,
                    evidence_hashes=(),
                    canonical_hash=d_hash,
                )
            reasons = ("coverage incomplete; absence cannot be inferred",)
            d_hash = sha256(("UNKNOWN:INCOMPLETE_COVERAGE:" + repr(reasons)).encode()).hexdigest()
            return Decision(
                state=EvidenceState.UNKNOWN,
                confidence=0.0,
                reasons=reasons,
                evidence_hashes=(),
                canonical_hash=d_hash,
            )

        live = [
            x for x in observations
            if x.state not in {EvidenceState.STALE, EvidenceState.FAILED}
        ]

        states = {x.state for x in live}
        if len(states) > 1:
            state = EvidenceState.CONFLICT
            conf = 0.5
            reasons = (f"conflicting observations: {sorted(s.value for s in states)}",)
        elif live:
            state = next(iter(states))
            conf = 1.0 if coverage.complete else 0.8
            reasons = (f"unanimous active state: {state.value}",)
        else:
            state = EvidenceState.UNKNOWN
            conf = 0.0
            reasons = ("no active non-stale observations",)

        ev_hashes = tuple(x.canonical_hash() for x in live)
        dec_repr = (state.value, conf, reasons, ev_hashes)
        canonical_dec_hash = sha256(repr(dec_repr).encode("utf-8")).hexdigest()

        return Decision(
            state=state,
            confidence=conf,
            reasons=reasons,
            evidence_hashes=ev_hashes,
            canonical_hash=canonical_dec_hash,
        )


@dataclass
class CadenceLease:
    """Protects against zombie agents and stale writes via monotonic fencing."""
    fence: int = 0
    owner_node: Optional[str] = None
    last_success_ns: Optional[int] = None
    lease_until_ns: Optional[int] = None

    def acquire(self, node: str, ttl_seconds: float = 60.0) -> Tuple[bool, int]:
        now_ns = time.time_ns()
        if self.lease_until_ns is not None and now_ns < self.lease_until_ns and self.owner_node != node:
            return False, self.fence
        self.fence += 1
        self.owner_node = node
        self.lease_until_ns = now_ns + int(ttl_seconds * 1e9)
        return True, self.fence

    def validate_mutation(self, proposed_fence: int) -> bool:
        """Rejects any write where proposed_fence < current fence."""
        return proposed_fence >= self.fence


@dataclass(frozen=True)
class ProofReceipt:
    """Cryptographic chained proof receipt (Receipt_n = H(Mission || Inputs || Patch || Tests || Receipt_{n-1}))."""
    mission_id: str
    input_hash: str
    patch_hash: str
    environment_hash: str
    test_manifest_hash: str
    decision_hash: str
    parent_receipt_hash: Optional[str] = None

    def compute_hash(self) -> str:
        chain_tuple = (
            self.mission_id,
            self.input_hash,
            self.patch_hash,
            self.environment_hash,
            self.test_manifest_hash,
            self.decision_hash,
            self.parent_receipt_hash or "GENESIS",
        )
        return sha256(repr(chain_tuple).encode("utf-8")).hexdigest()
