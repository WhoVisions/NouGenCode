"""Replayable mission contract, progress journal, budget, and worker resume.

This is an in-process reference kernel. Durable storage, authenticated identity,
and remote effect idempotency remain adapter responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from math import isfinite
import threading
from typing import Mapping, Sequence


class MissionError(ValueError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MissionContract:
    mission_id: str
    objective: str
    required_outcomes: tuple[str, ...]
    constraints: tuple[tuple[str, str], ...]
    completion_evidence: tuple[str, ...]
    authority_ref: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.mission_id, self.objective, self.authority_ref)):
            raise MissionError("mission id, objective, and authority reference are required")
        if not self.required_outcomes or not self.completion_evidence:
            raise MissionError("at least one required outcome and completion evidence item are required")
        if len(set(self.required_outcomes)) != len(self.required_outcomes):
            raise MissionError("required outcome ids must be unique")
        if len({key for key, _ in self.constraints}) != len(self.constraints):
            raise MissionError("constraint keys must be unique")

    def canonical(self) -> dict[str, object]:
        return {
            "mission_id": self.mission_id,
            "objective": self.objective,
            "required_outcomes": list(self.required_outcomes),
            "constraints": [list(item) for item in sorted(self.constraints)],
            "completion_evidence": list(self.completion_evidence),
            "authority_ref": self.authority_ref,
        }

    @property
    def contract_hash(self) -> str:
        return _digest(self.canonical())


class StepStatus(str, Enum):
    REPORTED_SUCCESS = "reported_success"
    VERIFIED = "verified"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StepRecord:
    step_id: str
    idempotency_key: str
    worker_id: str
    status: StepStatus
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    outcome_ids: tuple[str, ...] = ()
    verification_method: str | None = None
    verification_passed: bool = False
    remaining_work: tuple[str, ...] = ()
    observed_result_hash: str = ""

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.step_id, self.idempotency_key, self.worker_id)):
            raise MissionError("step id, idempotency key, and worker id are required")
        refs = self.input_refs + self.output_refs + self.evidence_refs + self.outcome_ids + self.remaining_work
        if any(not value.strip() for value in refs):
            raise MissionError("step references must be non-empty strings")
        if self.status is StepStatus.VERIFIED:
            if not self.verification_method or not self.verification_passed or not self.evidence_refs:
                raise MissionError("verified steps require a passing named verifier and evidence references")
        elif self.verification_passed:
            raise MissionError("only verified steps can have passing verification")

    def canonical(self) -> dict[str, object]:
        return {
            "step_id": self.step_id, "idempotency_key": self.idempotency_key,
            "worker_id": self.worker_id, "status": self.status.value,
            "input_refs": list(self.input_refs), "output_refs": list(self.output_refs),
            "evidence_refs": list(self.evidence_refs), "outcome_ids": list(self.outcome_ids),
            "verification_method": self.verification_method,
            "verification_passed": self.verification_passed,
            "remaining_work": list(self.remaining_work),
            "observed_result_hash": self.observed_result_hash,
        }

    @property
    def record_hash(self) -> str:
        return _digest(self.canonical())

    @property
    def idempotency_hash(self) -> str:
        """Hash logical effect/result, excluding the worker that delivered it."""
        body = self.canonical()
        body.pop("worker_id")
        return _digest(body)


@dataclass(frozen=True)
class ResourceBudget:
    limits: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not self.limits or len({name for name, _ in self.limits}) != len(self.limits):
            raise MissionError("resource budget needs unique resource limits")
        if any(not name or isinstance(value, bool) or not isfinite(value) or value < 0
               for name, value in self.limits):
            raise MissionError("resource limits must have names and non-negative amounts")


@dataclass(frozen=True)
class SpendReceipt:
    operation_id: str
    amounts: tuple[tuple[str, float], ...]
    receipt_hash: str


class MissionJournal:
    """Append-only, idempotent journal with immutable mission intent."""

    def __init__(self, contract: MissionContract, budget: ResourceBudget):
        self.contract = contract
        self.budget = budget
        self._lock = threading.RLock()
        self._steps: list[StepRecord] = []
        self._step_keys: dict[str, str] = {}
        self._spends: dict[str, tuple[tuple[str, float], ...]] = {}
        self._spent = {name: 0.0 for name, _ in budget.limits}

    @property
    def steps(self) -> tuple[StepRecord, ...]:
        with self._lock:
            return tuple(self._steps)

    def append(self, record: StepRecord) -> bool:
        """Append once. Duplicate key+identical record is a safe no-op."""
        if not set(record.outcome_ids) <= set(self.contract.required_outcomes):
            raise MissionError("step declares an outcome absent from the immutable mission contract")
        with self._lock:
            prior = self._step_keys.get(record.idempotency_key)
            if prior is not None:
                if prior == record.idempotency_hash:
                    return False
                raise MissionError("idempotency key reused for different step content")
            self._step_keys[record.idempotency_key] = record.idempotency_hash
            self._steps.append(record)
            return True

    def spend(self, operation_id: str, amounts: Mapping[str, float]) -> SpendReceipt:
        """Reserve declared spend once and reject unknown/over-budget resources."""
        if not operation_id.strip() or not amounts:
            raise MissionError("spend operation id and amounts are required")
        if any(isinstance(value, bool) for value in amounts.values()):
            raise MissionError("spend amounts must be numeric values, not booleans")
        normalized = tuple(sorted((name, float(value)) for name, value in amounts.items()))
        if any(not name or not isfinite(value) or value < 0 for name, value in normalized):
            raise MissionError("spend amounts must be non-negative")
        digest = _digest([operation_id, [list(item) for item in normalized]])
        with self._lock:
            prior = self._spends.get(operation_id)
            if prior is not None:
                if prior != normalized:
                    raise MissionError("spend id reused for different amounts")
                return SpendReceipt(operation_id, normalized, digest)
            limits = dict(self.budget.limits)
            for name, value in normalized:
                if name not in limits:
                    raise MissionError(f"resource is not budgeted: {name}")
                if self._spent[name] + value > limits[name]:
                    raise MissionError(f"resource budget exceeded: {name}")
            for name, value in normalized:
                self._spent[name] += value
            self._spends[operation_id] = normalized
        return SpendReceipt(operation_id, normalized, digest)

    def spent(self) -> dict[str, float]:
        with self._lock:
            return dict(self._spent)

    def is_complete(self) -> bool:
        """Completion requires independently verified outcomes and evidence."""
        with self._lock:
            verified = [row for row in self._steps
                        if row.status is StepStatus.VERIFIED and row.verification_passed]
        outcomes = {item for row in verified for item in row.outcome_ids}
        evidence = {item for row in verified for item in row.evidence_refs}
        return (set(self.contract.required_outcomes) <= outcomes
                and set(self.contract.completion_evidence) <= evidence)

    def resume_packet(self, next_worker_id: str) -> dict[str, object]:
        """Create a content-hashed handoff carrying intent, evidence, and remaining work."""
        if not next_worker_id.strip():
            raise MissionError("next worker id is required")
        steps = self.steps
        verified_outcomes = {item for row in steps if row.status is StepStatus.VERIFIED
                             and row.verification_passed for item in row.outcome_ids}
        remaining = [item for row in steps for item in row.remaining_work]
        remaining.extend(item for item in self.contract.required_outcomes
                         if item not in verified_outcomes)
        body: dict[str, object] = {
            "contract": self.contract.canonical(),
            "contract_hash": self.contract.contract_hash,
            "next_worker_id": next_worker_id,
            "verified_records": [row.canonical() for row in steps if row.status is StepStatus.VERIFIED],
            "reported_but_unverified": [row.canonical() for row in steps
                                        if row.status is StepStatus.REPORTED_SUCCESS],
            "remaining_work": list(dict.fromkeys(remaining)),
            "spent": self.spent(),
        }
        body["packet_hash"] = _digest(body)
        return body


def verify_resume_packet(packet: Mapping[str, object], contract: MissionContract) -> bool:
    """Reject tampering or mission-intent drift in a handoff packet."""
    received = dict(packet)
    packet_hash = received.pop("packet_hash", None)
    return (packet_hash == _digest(received)
            and received.get("contract_hash") == contract.contract_hash
            and received.get("contract") == contract.canonical())
