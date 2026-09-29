"""Replayable evidence-first control-plane slice built on existing NouGenCode roles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import threading
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from nougencode.arbitration.arbiter import Claim, EvidenceArbiter, EvidenceReceipt
from nougencode.core.mission import Capability, MutationBudget, TaskNode


ENVELOPE_SCHEMA_VERSION = "1.0.0"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _timestamp(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timezone-qualified ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-qualified ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class EvidenceObservation:
    observation_id: str
    source_id: str
    provenance: str
    value: Optional[bool]
    observed_at: str
    freshness_ttl_seconds: float
    status: str = "OBSERVED"
    elapsed_seconds: Optional[float] = None
    budget_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.source_id.strip() or not self.provenance.strip():
            raise ValueError("observation id, source id, and provenance are required")
        if self.status not in {"OBSERVED", "UNKNOWN", "TIMED_OUT", "STALE"}:
            raise ValueError("observation status must be OBSERVED, UNKNOWN, TIMED_OUT, or STALE")
        if self.status == "OBSERVED" and not isinstance(self.value, bool):
            raise ValueError("observed truth values must be boolean")
        if self.status != "OBSERVED" and self.value is not None:
            raise ValueError("unobserved values must be null")
        if self.status == "TIMED_OUT":
            for field, value in (("elapsed_seconds", self.elapsed_seconds), ("budget_seconds", self.budget_seconds)):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                    raise ValueError(f"timed out observations require non-negative {field}")
        elif self.elapsed_seconds is not None or self.budget_seconds is not None:
            raise ValueError("elapsed_seconds and budget_seconds are only valid for TIMED_OUT observations")
        if (
            isinstance(self.freshness_ttl_seconds, bool)
            or not isinstance(self.freshness_ttl_seconds, (int, float))
            or self.freshness_ttl_seconds < 0
        ):
            raise ValueError("freshness_ttl_seconds must be non-negative")
        _timestamp(self.observed_at, "observation.observed_at")

    def is_fresh(self, as_of: datetime) -> bool:
        if self.status != "OBSERVED" or as_of.tzinfo is None:
            return False
        now = as_of.astimezone(timezone.utc)
        observed = _timestamp(self.observed_at, "observation.observed_at")
        expires = observed + timedelta(seconds=self.freshness_ttl_seconds)
        return observed <= now <= expires

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "observation_id": self.observation_id,
            "source_id": self.source_id,
            "provenance": self.provenance,
            "value": self.value,
            "status": self.status,
            "observed_at": self.observed_at,
            "freshness_ttl_seconds": self.freshness_ttl_seconds,
        }
        if self.status == "TIMED_OUT":
            result["elapsed_seconds"] = self.elapsed_seconds
            result["budget_seconds"] = self.budget_seconds
        return result


@dataclass(frozen=True)
class EventEnvelope:
    mission_id: str
    sequence: int
    event_type: str
    observed_at: str
    source_id: str
    payload: Mapping[str, Any]
    schema_version: str = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.mission_id.strip() or not self.event_type.strip() or not self.source_id.strip():
            raise ValueError("mission_id, event_type, and source_id are required")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if self.schema_version != ENVELOPE_SCHEMA_VERSION:
            raise ValueError(f"unsupported envelope schema version: {self.schema_version}")
        _timestamp(self.observed_at, "event.observed_at")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be an object")
        _canonical_json(self.payload)

    def to_dict(self) -> Dict[str, Any]:
        body = {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "observed_at": self.observed_at,
            "source_id": self.source_id,
            "payload": dict(self.payload),
        }
        return {"event_id": _sha256(body), **body}


@dataclass(frozen=True)
class CoverageEnvelope:
    expected_source_ids: Tuple[str, ...]
    observations: Tuple[EvidenceObservation, ...]
    schema_version: str = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ENVELOPE_SCHEMA_VERSION:
            raise ValueError(f"unsupported envelope schema version: {self.schema_version}")
        if len(set(self.expected_source_ids)) != len(self.expected_source_ids):
            raise ValueError("expected source ids must be unique")
        if any(not source.strip() for source in self.expected_source_ids):
            raise ValueError("expected source ids cannot be empty")
        observation_ids = [item.observation_id for item in self.observations]
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("observation ids must be unique")

    @property
    def missing_source_ids(self) -> Tuple[str, ...]:
        observed = {item.source_id for item in self.observations}
        return tuple(sorted(set(self.expected_source_ids) - observed))

    def to_dict(self) -> Dict[str, Any]:
        body = {
            "schema_version": self.schema_version,
            "expected_source_ids": sorted(self.expected_source_ids),
            "observations": [item.to_dict() for item in sorted(self.observations, key=lambda row: row.observation_id)],
            "missing_source_ids": list(self.missing_source_ids),
        }
        return {"coverage_id": _sha256(body), **body}


class TruthStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    UNKNOWN_WITHIN_BUDGET = "UNKNOWN_WITHIN_BUDGET"


@dataclass(frozen=True)
class TruthResult:
    status: TruthStatus
    reason: str
    evidence_ids: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
        }


class TruthResolver:
    """Resolve a truth claim only when expected evidence is complete and fresh."""

    @staticmethod
    def resolve(coverage: CoverageEnvelope, as_of: datetime) -> TruthResult:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not coverage.expected_source_ids:
            return TruthResult(TruthStatus.UNKNOWN, "coverage declares no expected sources", ())
        unexpected = {item.source_id for item in coverage.observations} - set(coverage.expected_source_ids)
        if unexpected:
            return TruthResult(TruthStatus.UNKNOWN, "coverage contains unexpected sources", ())
        selected = [item for item in coverage.observations if item.source_id in coverage.expected_source_ids]
        evidence_ids = tuple(sorted(item.observation_id for item in selected))
        if coverage.missing_source_ids:
            return TruthResult(TruthStatus.UNKNOWN, "expected sources are missing", evidence_ids)
        by_source: Dict[str, list[EvidenceObservation]] = {}
        for item in selected:
            by_source.setdefault(item.source_id, []).append(item)
        if any(len(by_source.get(source_id, [])) != 1 for source_id in coverage.expected_source_ids):
            return TruthResult(TruthStatus.UNKNOWN, "source evidence is ambiguous", evidence_ids)
        timed_out = [item for item in selected if item.status == "TIMED_OUT"]
        if timed_out:
            within_budget = all(
                item.elapsed_seconds is not None
                and item.budget_seconds is not None
                and item.elapsed_seconds <= item.budget_seconds
                for item in timed_out
            )
            if within_budget:
                return TruthResult(TruthStatus.UNKNOWN_WITHIN_BUDGET, "source timed out within its execution budget", evidence_ids)
            return TruthResult(TruthStatus.UNKNOWN, "source timed out without proving it stayed within budget", evidence_ids)
        source_values = []
        for source_id in sorted(coverage.expected_source_ids):
            items = by_source.get(source_id, [])
            if not items[0].is_fresh(as_of):
                return TruthResult(TruthStatus.UNKNOWN, "source evidence is ambiguous, unknown, or stale", evidence_ids)
            source_values.append(items[0].value)
        if len(set(source_values)) != 1:
            return TruthResult(TruthStatus.UNKNOWN, "fresh sources disagree", evidence_ids)
        status = TruthStatus.PASS if source_values[0] else TruthStatus.FAIL
        return TruthResult(status, "all expected sources agree with fresh evidence", evidence_ids)


class CapabilityGraph:
    """Evidence edges for the existing Capability enum; this adds no role registry."""

    def __init__(self) -> None:
        self._assessments: Dict[Capability, list[TruthResult]] = {}

    def record(self, capability: Capability, result: TruthResult) -> None:
        if not isinstance(capability, Capability):
            raise TypeError("capability must use the existing NouGenCode Capability enum")
        self._assessments.setdefault(capability, []).append(result)

    def resolve(self, capability: Capability) -> TruthStatus:
        results = self._assessments.get(capability, [])
        if not results or any(item.status in {TruthStatus.UNKNOWN, TruthStatus.UNKNOWN_WITHIN_BUDGET} for item in results):
            return TruthStatus.UNKNOWN
        states = {item.status for item in results}
        return states.pop() if len(states) == 1 else TruthStatus.UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            capability.value: self.resolve(capability).value
            for capability in sorted(self._assessments, key=lambda item: item.value)
        }


@dataclass(frozen=True)
class PolicyDecision:
    task_id: str
    capability: str
    action: str
    reason: str

    def canonical_fields(self) -> Dict[str, str]:
        return {"task_id": self.task_id, "capability": self.capability, "action": self.action}


class PolicyPlanner:
    """Translate evidence on the existing capability graph into a stable task action."""

    def plan(self, task: TaskNode, graph: CapabilityGraph) -> PolicyDecision:
        state = graph.resolve(task.capability)
        if state == TruthStatus.PASS:
            action, reason = "ROUTE", "capability has fresh agreeing evidence"
        elif state == TruthStatus.FAIL:
            action, reason = "AVOID", "capability has fresh negative evidence"
        else:
            action, reason = "UNKNOWN", "capability evidence is missing, stale, or inconclusive"
        return PolicyDecision(task.id, task.capability.value, action, reason)


def canonical_decision_hash(decisions: Sequence[PolicyDecision]) -> str:
    normalized = sorted((item.canonical_fields() for item in decisions), key=lambda item: (item["task_id"], item["capability"]))
    return _sha256({"schema_version": ENVELOPE_SCHEMA_VERSION, "decisions": normalized})


class MutationRejected(ValueError):
    """A mutation exceeded its explicit budget or reused a key with different content."""


class StaleFenceRejected(ValueError):
    """A mutation arrived with a fence older than the last accepted mutation."""


class MutationLedger:
    """Thread-safe in-process idempotency and monotonic-fence reference gate."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_fence = 0
        self._applied: Dict[str, str] = {}

    def apply(
        self,
        *,
        idempotency_key: str,
        fence: int,
        mutation: Mapping[str, Any],
        budget: MutationBudget,
        files_changed: int,
        lines_added: int,
        lines_deleted: int = 0,
    ) -> bool:
        if not idempotency_key.strip():
            raise MutationRejected("idempotency_key is required")
        if isinstance(fence, bool) or not isinstance(fence, int) or fence <= 0:
            raise MutationRejected("fence must be a positive integer")
        if budget.evaluate_drift(files_changed, lines_added, lines_deleted) > 1:
            raise MutationRejected("mutation exceeds its declared budget")
        digest = _sha256(mutation)
        with self._lock:
            prior = self._applied.get(idempotency_key)
            if prior is not None:
                if prior == digest:
                    return False
                raise MutationRejected("idempotency key was reused for different mutation content")
            if fence <= self._last_fence:
                raise StaleFenceRejected("mutation fence is not monotonic")
            self._last_fence = fence
            self._applied[idempotency_key] = digest
            return True


@dataclass(frozen=True)
class GoldenSliceResult:
    event: EventEnvelope
    coverage: CoverageEnvelope
    truth: TruthResult
    decision: PolicyDecision
    decision_hash: str
    proof_receipt: EvidenceReceipt
    arbiter_accepts: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "event": self.event.to_dict(),
            "coverage": self.coverage.to_dict(),
            "truth": self.truth.to_dict(),
            "decision": {
                **self.decision.canonical_fields(),
                "reason": self.decision.reason,
            },
            "decision_hash": self.decision_hash,
            "arbiter_accepts": self.arbiter_accepts,
            "proof_receipt": {
                "stage": self.proof_receipt.stage,
                "source": self.proof_receipt.source,
                "sha256": self.proof_receipt.sha256,
                "observed_at": self.proof_receipt.observed_at,
            },
        }


def run_golden_slice(task: TaskNode, coverage: CoverageEnvelope, as_of: datetime) -> GoldenSliceResult:
    """Run the pure assess-plan-arbitrate slice without provider or persistence side effects."""
    truth = TruthResolver.resolve(coverage, as_of)
    graph = CapabilityGraph()
    graph.record(task.capability, truth)
    decision = PolicyPlanner().plan(task, graph)
    decision_hash = canonical_decision_hash([decision])
    event = EventEnvelope(
        mission_id=task.id,
        sequence=0,
        event_type="capability_assessed",
        observed_at=as_of.astimezone(timezone.utc).isoformat(),
        source_id="truth_resolver",
        payload={
            "task_id": task.id,
            "capability": task.capability.value,
            "truth": truth.status.value,
            "coverage_id": coverage.to_dict()["coverage_id"],
            "decision_hash": decision_hash,
        },
    )
    resolved = truth.status in {TruthStatus.PASS, TruthStatus.FAIL}
    decision_claim = Claim(
        id=f"decision:{task.id}",
        statement="The task policy decision is supported by current evidence.",
        severity=1.0,
        confidence=1.0 if resolved else 0.0,
        evidence=list(truth.evidence_ids) or [f"coverage:{coverage.to_dict()['coverage_id']}"],
        resolved=resolved,
    )
    arbiter_accepts = EvidenceArbiter().evaluate_claims([decision_claim])
    proof = EvidenceReceipt.from_payload("golden_slice", "evidence_arbiter", {
        "event": event.to_dict(),
        "coverage": coverage.to_dict(),
        "truth": truth.to_dict(),
        "decision": decision.canonical_fields(),
        "decision_hash": decision_hash,
        "arbiter_accepts": arbiter_accepts,
    })
    return GoldenSliceResult(event, coverage, truth, decision, decision_hash, proof, arbiter_accepts)


def run_golden_slice_request(request: Mapping[str, Any]) -> GoldenSliceResult:
    """Parse and execute a portable JSON request for unattended evidence assessment."""
    if not isinstance(request, Mapping):
        raise ValueError("request must be an object")
    if set(request) != {"schema_version", "as_of", "task", "coverage"}:
        raise ValueError("request must contain schema_version, as_of, task, and coverage only")
    if request["schema_version"] != ENVELOPE_SCHEMA_VERSION:
        raise ValueError(f"request.schema_version must be {ENVELOPE_SCHEMA_VERSION}")
    task_doc = request["task"]
    if not isinstance(task_doc, Mapping):
        raise ValueError("request.task must be an object")
    required_task_fields = {"task_id", "objective", "capability", "files_expected", "mutation_budget"}
    if set(task_doc) != required_task_fields:
        raise ValueError("request.task does not match the task contract")
    for field in ("task_id", "objective", "capability"):
        if not isinstance(task_doc[field], str) or not task_doc[field].strip():
            raise ValueError(f"request.task.{field} must be a non-empty string")
    if not isinstance(task_doc["files_expected"], list) or not all(isinstance(item, str) for item in task_doc["files_expected"]):
        raise ValueError("request.task.files_expected must be a string array")
    budget_doc = task_doc["mutation_budget"]
    if not isinstance(budget_doc, Mapping):
        raise ValueError("request.task.mutation_budget must be an object")
    budget_fields = {"max_files", "max_added_lines", "max_deleted_lines"}
    if not budget_fields.issubset(budget_doc) or set(budget_doc) - budget_fields - {"allowed_roots", "forbidden_roots"}:
        raise ValueError("request.task.mutation_budget does not match the budget contract")
    for field in budget_fields:
        if isinstance(budget_doc[field], bool) or not isinstance(budget_doc[field], int) or budget_doc[field] < 0:
            raise ValueError(f"request.task.mutation_budget.{field} must be a non-negative integer")
    for field in ("allowed_roots", "forbidden_roots"):
        if field in budget_doc and (not isinstance(budget_doc[field], list) or not all(isinstance(item, str) for item in budget_doc[field])):
            raise ValueError(f"request.task.mutation_budget.{field} must be a string array")
    task = TaskNode(
        id=str(task_doc["task_id"]),
        objective=str(task_doc["objective"]),
        capability=Capability(task_doc["capability"]),
        files_expected=list(task_doc["files_expected"]),
        mutation_budget=MutationBudget(
            max_files=budget_doc["max_files"],
            max_added_lines=budget_doc["max_added_lines"],
            max_deleted_lines=budget_doc["max_deleted_lines"],
            allowed_roots=list(budget_doc.get("allowed_roots", [])),
            forbidden_roots=list(budget_doc.get("forbidden_roots", [])),
        ),
    )
    coverage_doc = request["coverage"]
    if not isinstance(coverage_doc, Mapping) or set(coverage_doc) != {"expected_source_ids", "observations"}:
        raise ValueError("request.coverage must contain expected_source_ids and observations")
    observations = coverage_doc["observations"]
    if not isinstance(observations, list):
        raise ValueError("request.coverage.observations must be an array")
    expected_source_ids = coverage_doc["expected_source_ids"]
    if not isinstance(expected_source_ids, list) or not all(isinstance(item, str) and item for item in expected_source_ids):
        raise ValueError("request.coverage.expected_source_ids must be a non-empty string array")
    try:
        coverage = CoverageEnvelope(
            tuple(expected_source_ids),
            tuple(EvidenceObservation(**item) for item in observations),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"request.coverage is invalid: {exc}") from exc
    return run_golden_slice(task, coverage, _timestamp(request["as_of"], "request.as_of"))


def mutation_within_budget(
    budget: MutationBudget, *, files_changed: int, lines_added: int, lines_deleted: int = 0
) -> bool:
    return budget.evaluate_drift(files_changed, lines_added, lines_deleted) <= 1
