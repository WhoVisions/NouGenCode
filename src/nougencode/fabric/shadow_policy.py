"""Shadow-policy replay engine with rule TTL and versioning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    version: str
    description: str
    predicate: Callable[[Mapping[str, Any]], bool]
    created_at: str
    ttl_seconds: float
    is_blocking: bool = True

    def is_valid(self, as_of: Optional[datetime] = None) -> bool:
        now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            created_dt = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except Exception:
            return False
        return created_dt <= now <= created_dt + timedelta(seconds=self.ttl_seconds)


@dataclass(frozen=True)
class ExecutionTrace:
    trace_id: str
    session_id: str
    action_name: str
    payload: Mapping[str, Any]
    active_policy_verdict: bool  # True = allowed, False = blocked
    timestamp: str


@dataclass(frozen=True)
class ShadowEvaluationResult:
    trace_id: str
    action_name: str
    live_verdict: bool
    shadow_verdict: bool
    is_divergent: bool
    violated_rules: Sequence[str]
    expired_rules: Sequence[str]


@dataclass(frozen=True)
class ReplayReport:
    total_traces: int
    divergent_traces: int
    divergence_rate: float
    evaluations: Sequence[ShadowEvaluationResult]
    is_safe_for_rollout: bool


class ShadowPolicyReplayer:
    """Replays historical traces against candidate policy rules to evaluate rollout safety."""

    def __init__(self, max_allowed_divergence: float = 0.05) -> None:
        if (
            isinstance(max_allowed_divergence, bool)
            or not isinstance(max_allowed_divergence, (int, float))
            or not 0.0 <= max_allowed_divergence <= 1.0
            or not math.isfinite(max_allowed_divergence)
        ):
            raise ValueError("max_allowed_divergence must be a finite number from 0 to 1")
        self.max_allowed_divergence = max_allowed_divergence
        self._shadow_rules: Dict[str, PolicyRule] = {}

    def register_shadow_rule(self, rule: PolicyRule) -> None:
        self._shadow_rules[rule.rule_id] = rule

    def evaluate_trace(
        self,
        trace: ExecutionTrace,
        as_of: Optional[datetime] = None,
    ) -> ShadowEvaluationResult:
        now = as_of or datetime.now(timezone.utc)
        violations: List[str] = []
        expired: List[str] = []

        for r_id, rule in self._shadow_rules.items():
            if not rule.is_valid(now):
                expired.append(f"{r_id}:{rule.version}")
                continue
            try:
                allowed = rule.predicate(trace.payload)
                if not allowed and rule.is_blocking:
                    violations.append(f"{r_id}:{rule.version}")
            except Exception:
                # Keep replay verdicts deterministic and avoid returning raw
                # exception details that may contain input or credential data.
                violations.append(f"{r_id}:{rule.version}(predicate_error)")

        shadow_verdict = len(violations) == 0
        is_divergent = shadow_verdict != trace.active_policy_verdict

        return ShadowEvaluationResult(
            trace_id=trace.trace_id,
            action_name=trace.action_name,
            live_verdict=trace.active_policy_verdict,
            shadow_verdict=shadow_verdict,
            is_divergent=is_divergent,
            violated_rules=tuple(violations),
            expired_rules=tuple(expired),
        )

    def replay_dataset(
        self,
        traces: Sequence[ExecutionTrace],
        as_of: Optional[datetime] = None,
    ) -> ReplayReport:
        if not traces:
            return ReplayReport(
                total_traces=0,
                divergent_traces=0,
                divergence_rate=0.0,
                evaluations=(),
                # Zero observations provide no evidence that a candidate is safe.
                is_safe_for_rollout=False,
            )

        results: List[ShadowEvaluationResult] = []
        divergent_count = 0

        for tr in traces:
            res = self.evaluate_trace(tr, as_of=as_of)
            results.append(res)
            if res.is_divergent:
                divergent_count += 1

        div_rate = divergent_count / len(traces)
        is_safe = div_rate <= self.max_allowed_divergence

        return ReplayReport(
            total_traces=len(traces),
            divergent_traces=divergent_count,
            divergence_rate=round(div_rate, 4),
            evaluations=tuple(results),
            is_safe_for_rollout=is_safe,
        )
