"""NouGen Directives Operating System Kernel.

Translates conversational natural language into typed, deterministic system directives.
Reflects the architectural core:
    "I stopped prompting the model. I started commanding the system around it."
    Conversation -> Protocol -> Orchestration.

Maps established NouGen operational vocabulary:
- shard: Persistent intelligence storage / recall in ~/.nougen/shards/
- relay: Cross-node asynchronous leg dispatch and handoff
- deep grep: Exhaustive semantic & AST code DNA retrieval
- Flash Kick: Rapid 3-tier resilience / failover protocol
- cadence fence: Monotonic lease protection against zombie mutations
- proof of execution: Cryptographically verifiable receipt chaining
- validation slice: Golden slice isolated verification ladder
- syntax heal: Pre-execution deterministic AST error repair
- dynamic route: Provider UCB multi-armed bandit dispatch

Zero hardcoding: all paths, keys, and endpoints are dynamically resolved via registry.
"""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


def _canonical_json(value: Any) -> str:
    """Serialize JSON-compatible values with recursive stable key ordering."""
    return json.dumps(
        _json_compatible(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _string_keyed_mapping(value: Mapping[Any, Any]) -> Dict[str, Any]:
    """Normalize object keys without silently collapsing distinct source keys."""
    result: Dict[str, Any] = {}
    for key, nested in value.items():
        normalized_key = str(key)
        if normalized_key in result:
            raise ValueError("duplicate object keys after JSON key normalization")
        result[normalized_key] = nested
    return result


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _json_compatible(nested)
            for key, nested in _string_keyed_mapping(value).items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_compatible(nested) for nested in value]
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({
            key: _freeze_json(nested)
            for key, nested in _string_keyed_mapping(value).items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(nested) for nested in value)
    return value


class DirectiveType(str, Enum):
    SHARD = "shard"
    RELAY = "relay"
    DEEP_GREP = "deep_grep"
    FLASH_KICK = "flash_kick"
    CADENCE_FENCE = "cadence_fence"
    PROOF_OF_EXECUTION = "proof_of_execution"
    VALIDATION_SLICE = "validation_slice"
    SYNTAX_HEAL = "syntax_heal"
    DYNAMIC_ROUTE = "dynamic_route"
    GENERIC_EXECUTION = "generic_execution"


@dataclass(frozen=True)
class DirectiveConstraint:
    name: str
    rule: str
    fail_closed: bool = True


@dataclass(frozen=True)
class DirectivePlan:
    directive_type: DirectiveType
    raw_instruction: str
    canonical_intent: str
    target_subsystem: str
    parameters: Mapping[str, Any]
    constraints: Tuple[DirectiveConstraint, ...]
    idempotency_key: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_plan_hash(self) -> str:
        """Deterministic content-addressed hash of the operational plan."""
        canonical_tuple = (
            self.directive_type.value,
            self.canonical_intent,
            self.target_subsystem,
            tuple(sorted((str(k), _canonical_json(v)) for k, v in self.parameters.items())),
            tuple(c.name for c in self.constraints),
            self.idempotency_key,
        )
        return sha256(repr(canonical_tuple).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DirectiveReceipt:
    """Execution receipt; success means the handler supplied completion proof."""

    plan_hash: str
    directive_type: DirectiveType
    success: bool
    runtime_evidence: Mapping[str, Any]
    output_hash: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_evidence", _freeze_json(self.runtime_evidence))

    def to_dict(self) -> Dict[str, Any]:
        """Return a detached JSON-compatible receipt for storage or transport."""
        if not self.has_valid_output_hash():
            raise ValueError("directive receipt output hash is invalid")
        return {
            "plan_hash": self.plan_hash,
            "directive_type": self.directive_type.value,
            "success": self.success,
            # Round-trip through the strict canonical serializer so even a
            # manually constructed receipt cannot export NaN or opaque values.
            "runtime_evidence": json.loads(_canonical_json(self.runtime_evidence)),
            "output_hash": self.output_hash,
            "timestamp": self.timestamp,
        }

    def has_valid_output_hash(self) -> bool:
        """Check that the receipt verdict and evidence match its output hash."""
        if not isinstance(self.plan_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.plan_hash) is None:
            return False
        if not isinstance(self.output_hash, str) or re.fullmatch(r"[0-9a-f]{64}", self.output_hash) is None:
            return False
        try:
            payload = {
                "plan_hash": self.plan_hash,
                "directive_type": self.directive_type.value,
                "success": self.success,
                "runtime_evidence": self.runtime_evidence,
            }
            expected = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        except (TypeError, ValueError):
            return False
        return hmac.compare_digest(expected, self.output_hash)

    @classmethod
    def verify_exported_dict(cls, value: Any) -> bool:
        """Verify an exported receipt after it crosses a JSON boundary."""
        if not isinstance(value, Mapping):
            return False
        try:
            if not isinstance(value["runtime_evidence"], Mapping):
                return False
            if type(value["success"]) is not bool or not isinstance(value["timestamp"], str):
                return False
            receipt = cls(
                plan_hash=value["plan_hash"],
                directive_type=DirectiveType(value["directive_type"]),
                success=value["success"],
                runtime_evidence=value["runtime_evidence"],
                output_hash=value["output_hash"],
                timestamp=value["timestamp"],
            )
            return receipt.has_valid_output_hash()
        except (KeyError, TypeError, ValueError):
            return False


class DirectiveCompiler:
    """Deterministic parser and compiler for NouGen conversational directives."""

    PATTERNS: Sequence[Tuple[DirectiveType, re.Pattern[str], str]] = [
        (
            DirectiveType.SHARD,
            re.compile(r"\b(shard|save to shards?|recall shard|persist shard|query shard)\b", re.IGNORECASE),
            "nougenshards",
        ),
        (
            DirectiveType.RELAY,
            re.compile(r"\b(relay|handoff|baton|dispatch leg|ack leg|sync relay)\b", re.IGNORECASE),
            "nougen_relay",
        ),
        (
            DirectiveType.DEEP_GREP,
            re.compile(r"\b(deep grep|dna search|code sweep|ast grep|search codebase)\b", re.IGNORECASE),
            "code_navigator",
        ),
        (
            DirectiveType.FLASH_KICK,
            re.compile(r"\b(flash kick|resilience plane|failover|circuit break)\b", re.IGNORECASE),
            "resilience_engine",
        ),
        (
            DirectiveType.CADENCE_FENCE,
            re.compile(r"\b(cadence fence|monotonic fence|anti-?zombie|lease acquire)\b", re.IGNORECASE),
            "lease_coordinator",
        ),
        (
            DirectiveType.PROOF_OF_EXECUTION,
            re.compile(r"\b(proof of execution|poe|cryptographic receipt|verify execution)\b", re.IGNORECASE),
            "evidence_kernel",
        ),
        (
            DirectiveType.VALIDATION_SLICE,
            re.compile(r"\b(validation slice|golden slice|ladder test|unit verify)\b", re.IGNORECASE),
            "test_selector",
        ),
        (
            DirectiveType.SYNTAX_HEAL,
            re.compile(r"\b(syntax heal|auto-?fix syntax|repair syntax|syntax guard)\b", re.IGNORECASE),
            "syntax_guard",
        ),
        (
            DirectiveType.DYNAMIC_ROUTE,
            re.compile(r"\b(dynamic route|bandit route|provider ucb|zero-?cost route)\b", re.IGNORECASE),
            "provider_ucb",
        ),
    ]

    @classmethod
    def parse(cls, conversational_text: str, session_context: Optional[Mapping[str, Any]] = None) -> DirectivePlan:
        """Parse natural language into a structured operational DirectivePlan."""
        cleaned = conversational_text.strip()
        matched_type = DirectiveType.GENERIC_EXECUTION
        subsystem = "core_executor"
        canonical_intent = cleaned

        for dir_type, pattern, sub in cls.PATTERNS:
            if pattern.search(cleaned):
                matched_type = dir_type
                subsystem = sub
                canonical_intent = f"Execute {dir_type.value} operational sequence from instruction"
                break

        # Extract dynamic parameters without hardcoding
        params: Dict[str, Any] = {
            "raw_text": cleaned,
            "session_id": (session_context or {}).get("session_id", "default_session"),
            "lane": (session_context or {}).get("lane", "default_lane"),
            "dynamic_resolution": True,
        }

        # Mathematical idempotency key: H(text || matched_type || session)
        seed = f"{cleaned}:{matched_type.value}:{params['session_id']}"
        idempotency_key = sha256(seed.encode("utf-8")).hexdigest()

        # Deterministic constraints
        constraints = (
            DirectiveConstraint("fail_closed_on_error", "Operation must halt and report on runtime error", True),
            DirectiveConstraint("cryptographic_proof_required", "Operation must yield a deterministic receipt", True),
            DirectiveConstraint(
                "dispatch_is_not_completion",
                "Sending, routing, or acknowledgment alone must remain provisional",
                True,
            ),
            DirectiveConstraint(
                "completion_requires_verification",
                "Completion requires an explicit verifier result and evidence references",
                True,
            ),
            DirectiveConstraint("no_hardcoded_credentials", "Credentials must resolve via opaque vaults", True),
        )

        return DirectivePlan(
            directive_type=matched_type,
            raw_instruction=cleaned,
            canonical_intent=canonical_intent,
            target_subsystem=subsystem,
            parameters=params,
            constraints=constraints,
            idempotency_key=idempotency_key,
        )


class DirectiveOrchestrator:
    """Execute directives without equating dispatch or handler return with completion."""

    _DIAGNOSTIC_KEYS = frozenset(
        {
            "error",
            "error_message",
            "exception",
            "exception_message",
            "diagnostic",
            "diagnostics",
            "raw_response",
            "response_body",
            "traceback",
            "stack_trace",
        }
    )
    _SECRET_KEY_PARTS = frozenset(
        {
            "apikey",
            "authorization",
            "credential",
            "password",
            "privatekey",
            "secret",
            "token",
        }
    )
    _SECRET_KEYS = frozenset({"api_key", "private_key"})
    _NON_COMPLETE_STATUSES = frozenset(
        {
            "accepted",
            "acknowledged",
            "blocked",
            "cancelled",
            "dispatched",
            "error",
            "failed",
            "failure",
            "in_progress",
            "partial",
            "pending",
            "queued",
            "running",
            "unknown",
            "unknown_within_budget",
        }
    )

    def __init__(self, handlers: Optional[Mapping[DirectiveType, Callable[[DirectivePlan], Mapping[str, Any]]]] = None) -> None:
        self._handlers: Dict[DirectiveType, Callable[[DirectivePlan], Mapping[str, Any]]] = dict(handlers or {})

    def register_handler(self, dir_type: DirectiveType, handler: Callable[[DirectivePlan], Mapping[str, Any]]) -> None:
        self._handlers[dir_type] = handler

    def execute(self, plan: DirectivePlan) -> DirectiveReceipt:
        """Run one handler and mark success only when its result carries verification evidence.

        A successful handoff or acknowledgment is still only dispatch evidence. A
        handler must return ``completed=True``, ``verification_passed=True``, a
        non-empty ``verification_method``, and non-empty ``evidence_refs`` before
        this receipt can report completion. The evidence contract is structural;
        adapters remain responsible for supplying genuine, independently checked
        references.
        """
        plan_hash = plan.compute_plan_hash()
        handler = self._handlers.get(plan.directive_type)

        if handler is None:
            evidence = {
                "dispatched": False,
                "execution_attempted": False,
                "subsystem": plan.target_subsystem,
                "status": "not_configured",
                "completion_state": "unconfigured",
                "remaining_work": "Register an executor; no work was performed.",
            }
            out_hash = self._evidence_hash(plan_hash, plan.directive_type, False, evidence)
            return DirectiveReceipt(
                plan_hash=plan_hash,
                directive_type=plan.directive_type,
                success=False,
                runtime_evidence=evidence,
                output_hash=out_hash,
            )

        try:
            evidence, diagnostics_redacted = self._sanitize_evidence(dict(handler(plan)))
            # The registered handler did run, but this fact alone does not
            # establish that the requested work was dispatched or completed.
            evidence["execution_attempted"] = True
            if diagnostics_redacted:
                evidence["diagnostic_fields_redacted"] = True
            verified = self._has_completion_evidence(evidence) and not diagnostics_redacted
            evidence["completion_state"] = "verified" if verified else "unverified"
            if not verified:
                evidence.setdefault(
                    "remaining_work",
                    "Verify the result and provide verification_method, verification_passed, and evidence_refs.",
                )
            out_hash = self._evidence_hash(plan_hash, plan.directive_type, verified, evidence)
            return DirectiveReceipt(
                plan_hash=plan_hash,
                directive_type=plan.directive_type,
                success=verified,
                runtime_evidence=evidence,
                output_hash=out_hash,
            )
        except Exception as e:
            # Exception text may contain request data, URLs, or credentials. Keep
            # the receipt useful without copying raw diagnostics into the relay.
            err_evidence = {
                "execution_attempted": True,
                "error_type": type(e).__name__,
                "failed_subsystem": plan.target_subsystem,
                "status": "failed",
                "completion_state": "failed",
                "remaining_work": "Inspect protected diagnostics and retry only after the cause is understood.",
            }
            out_hash = self._evidence_hash(plan_hash, plan.directive_type, False, err_evidence)
            return DirectiveReceipt(
                plan_hash=plan_hash,
                directive_type=plan.directive_type,
                success=False,
                runtime_evidence=err_evidence,
                output_hash=out_hash,
            )

    @staticmethod
    def _has_completion_evidence(evidence: Mapping[str, Any]) -> bool:
        method = evidence.get("verification_method")
        refs = evidence.get("evidence_refs")
        status = evidence.get("status")
        non_complete_status = (
            isinstance(status, str)
            and status.strip().casefold().replace("-", "_").replace(" ", "_")
            in DirectiveOrchestrator._NON_COMPLETE_STATUSES
        )
        return (
            not non_complete_status
            and evidence.get("completed") is True
            and evidence.get("verification_passed") is True
            and isinstance(method, str)
            and bool(method.strip())
            and isinstance(refs, (list, tuple))
            and bool(refs)
            and all(isinstance(ref, str) and bool(ref.strip()) for ref in refs)
        )

    @staticmethod
    def _evidence_hash(
        plan_hash: str,
        directive_type: DirectiveType,
        success: bool,
        evidence: Mapping[str, Any],
    ) -> str:
        """Bind the receipt hash to its plan, verdict, type, and evidence."""
        payload = {
            "plan_hash": plan_hash,
            "directive_type": directive_type.value,
            "success": success,
            "runtime_evidence": evidence,
        }
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @classmethod
    def _sanitize_evidence(cls, value: Any) -> Tuple[Dict[str, Any], bool]:
        """Remove common raw diagnostic fields before evidence enters a receipt.

        If any diagnostic is removed, the orchestrator keeps the result
        provisional even when the handler also supplied completion flags.
        """
        redacted = False

        def clean(item: Any) -> Any:
            nonlocal redacted
            if isinstance(item, Mapping):
                result: Dict[str, Any] = {}
                for key, nested in item.items():
                    normalized_key = str(key).strip().casefold().replace("-", "_")
                    key_parts = set(normalized_key.split("_"))
                    if (
                        normalized_key in cls._DIAGNOSTIC_KEYS
                        or normalized_key in cls._SECRET_KEYS
                        or key_parts & cls._SECRET_KEY_PARTS
                    ):
                        redacted = True
                        continue
                    output_key = str(key)
                    if output_key in result:
                        raise ValueError("duplicate object keys after JSON key normalization")
                    result[output_key] = clean(nested)
                return result
            if isinstance(item, list):
                return [clean(nested) for nested in item]
            if isinstance(item, tuple):
                return tuple(clean(nested) for nested in item)
            return item

        sanitized = clean(value)
        return sanitized, redacted
