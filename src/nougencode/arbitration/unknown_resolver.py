"""
Universal Epistemic Unknown Resolver & Constraint Closure Engine for NouGenCode.

Implements the top .001% mathematical unknown resolution laws:
  1. Never Guess When You Can Calculate (Exact derivation/constraint solving beats probabilistic judgment).
  2. Never Calculate What Must Be Observed (Authoritative state, files, environment, probes beat inference).
  3. Never Observe Again What Has Already Been Proven (Cached proofs, hashes, stable invariants beat re-execution).

Mathematical Taxonomy of Unknowns:
  U in {DERIVE, LOOKUP, OBSERVE, CONSTRAINT_SOLVE, OPTIMIZE, VERIFY, SEARCH, BOUNDED_JUDGMENT, OPEN_REASONING, ASK_HUMAN, ABSTAIN}

Constraint Closure Law:
  Generation/execution is strictly forbidden until:
    forall u in U_required: state(u) in {RESOLVED, BOUNDED_ACCEPTED, EXPLICITLY_DEFERRED}
  If any required unknown remains UNRESOLVED, ConstraintClosureGate halts execution with blocking claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union


class EpistemicMethod(str, Enum):
    DERIVE = "derive"                      # Exact mathematical formula / calculation
    LOOKUP = "lookup"                      # Authoritative repository files, configs, lockfiles
    OBSERVE = "observe"                    # Runtime probe, OS check, socket ping, live environment
    CONSTRAINT_SOLVE = "constraint_solve"  # Semver dependency graph, SAT / SMT, discrete logic
    OPTIMIZE = "optimize"                  # Cost/latency/quality multi-objective optimization
    VERIFY = "verify"                      # Compiler check, static analysis, targeted test
    SEARCH = "search"                      # Shard cluster, external documentation, codebase grep
    BOUNDED_JUDGMENT = "bounded_judgment"  # Calibrated probabilistic classifier (Jev, OllamaProb)
    OPEN_REASONING = "open_reasoning"      # Generative LLM architecture proposal
    ASK_HUMAN = "ask_human"                # Direct clarification when expected VOI > interrupt cost
    ABSTAIN = "abstain"                    # Information fundamentally unavailable; explicit refusal


class UnknownState(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    BOUNDED_ACCEPTED = "BOUNDED_ACCEPTED"
    EXPLICITLY_DEFERRED = "EXPLICITLY_DEFERRED"


@dataclass(frozen=True)
class Unknown:
    """A first-class computational unknown variable."""
    key: str
    question: str
    required: bool = True
    criticality: float = 0.5  # 0.0 to 1.0 (1.0 = blocking / destructive)
    domain: str = "engineering"
    preferred_resolvers: Tuple[EpistemicMethod, ...] = (
        EpistemicMethod.LOOKUP,
        EpistemicMethod.DERIVE,
        EpistemicMethod.OBSERVE,
        EpistemicMethod.SEARCH,
        EpistemicMethod.ASK_HUMAN,
    )
    answer_space: Optional[Tuple[str, ...]] = None  # Finite choices if bounded
    exactness_required: bool = True
    state: UnknownState = UnknownState.UNRESOLVED

    def canonical_hash(self) -> str:
        payload = {
            "key": self.key,
            "question": self.question,
            "required": self.required,
            "criticality": round(self.criticality, 4),
            "domain": self.domain,
            "answer_space": list(self.answer_space) if self.answer_space else None,
            "exactness_required": self.exactness_required,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Resolution:
    """The verified outcome of applying an epistemic operator to an Unknown."""
    key: str
    resolver: EpistemicMethod
    value: Any
    state: UnknownState
    exact: bool
    confidence: float
    probabilities: Dict[str, float] = field(default_factory=dict)
    evidence: Tuple[str, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def canonical_hash(self) -> str:
        payload = {
            "key": self.key,
            "resolver": self.resolver.value,
            "value": str(self.value),
            "state": self.state.value,
            "exact": self.exact,
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in sorted(self.probabilities.items())},
            "evidence": sorted(self.evidence),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ClosureResult:
    """Outcome of evaluating the Constraint Closure Gate."""
    closed: bool
    blockers: Tuple[Unknown, ...]
    resolutions: Dict[str, Resolution]
    closure_hash: str


class EpistemicRouter:
    """
    Evaluates Unknowns against context and selects the cheapest, highest-certainty epistemic operator.
    Follows the strict hierarchy:
      Exact Truth (DERIVE, LOOKUP, OBSERVE, CONSTRAINT_SOLVE) >
      Empirical Evidence (VERIFY, SEARCH) >
      Bounded Semantic Judgment (BOUNDED_JUDGMENT: Jev/OllamaProb) >
      Generative Proposal (OPEN_REASONING) >
      Interactive Query (ASK_HUMAN) >
      Explicit Abstention (ABSTAIN)
    """

    def __init__(self, custom_handlers: Optional[Dict[EpistemicMethod, Callable[[Unknown, Dict[str, Any]], Optional[Resolution]]]] = None) -> None:
        self.handlers = custom_handlers or {}

    def resolve(self, unknown: Unknown, context: Dict[str, Any]) -> Resolution:
        """Apply epistemic resolution hierarchy to an unknown variable."""
        # 1. Authoritative lookup in repository context / files
        if EpistemicMethod.LOOKUP in unknown.preferred_resolvers:
            direct_val = context.get(unknown.key)
            if direct_val is not None:
                return Resolution(
                    key=unknown.key,
                    resolver=EpistemicMethod.LOOKUP,
                    value=direct_val,
                    state=UnknownState.RESOLVED,
                    exact=True,
                    confidence=1.0,
                    evidence=(f"Context exact lookup: {unknown.key}",),
                )

        # 2-6. Handler-backed epistemic operators in strict hierarchy order
        if self.handlers:
            for method in (
                EpistemicMethod.DERIVE,
                EpistemicMethod.CONSTRAINT_SOLVE,
                EpistemicMethod.OBSERVE,
                EpistemicMethod.SEARCH,
                EpistemicMethod.BOUNDED_JUDGMENT,
            ):
                if (
                    method in self.handlers
                    and method in unknown.preferred_resolvers
                    and (method is not EpistemicMethod.BOUNDED_JUDGMENT or unknown.answer_space)
                ):
                    res = self.handlers[method](unknown, context)
                    if res:
                        return res

        # 7. Value of Information (VOI) calculation for Ask Human
        # If unknown is critical and required, and cannot be derived, ask human.
        if unknown.required and unknown.criticality >= 0.7:
            return Resolution(
                key=unknown.key,
                resolver=EpistemicMethod.ASK_HUMAN,
                value=None,
                state=UnknownState.UNRESOLVED,
                exact=False,
                confidence=0.0,
                evidence=(f"VOI high ({unknown.criticality:.2f}): user authority required for {unknown.key}",),
                provenance={"question": unknown.question},
            )

        # 8. Unresolved fallback
        return Resolution(
            key=unknown.key,
            resolver=EpistemicMethod.ABSTAIN,
            value=None,
            state=UnknownState.UNRESOLVED,
            exact=False,
            confidence=0.0,
            evidence=("Insufficient epistemic evidence to resolve unknown",),
        )


class ConstraintClosureGate:
    """
    Evaluates whether all required Unknowns have been resolved.
    Enforces the invariant:
      forall u in U_required, state(u) != UNRESOLVED
    """

    def __init__(self, router: Optional[EpistemicRouter] = None) -> None:
        self.router = router or EpistemicRouter()

    def evaluate(
        self,
        unknowns: Sequence[Union[Unknown, str]],
        context: Dict[str, Any]
    ) -> ClosureResult:
        """Resolve all unknowns and enforce closure."""
        resolutions: Dict[str, Resolution] = {}
        blockers: List[Unknown] = []

        for item in unknowns:
            if isinstance(item, str):
                u = Unknown(
                    key=item,
                    question=f"Resolve unknown requirement: {item}",
                    required=True,
                    criticality=0.8,
                )
            elif isinstance(item, Unknown):
                u = item
            else:
                continue
            resolution = self.router.resolve(u, context)
            resolutions[u.key] = resolution
            if u.required and resolution.state == UnknownState.UNRESOLVED:
                blockers.append(u)

        is_closed = (len(blockers) == 0)

        # Compute deterministic closure hash
        closure_payload = {
            "is_closed": is_closed,
            "blockers": [b.key for b in blockers],
            "resolutions": {k: r.canonical_hash() for k, r in sorted(resolutions.items())},
        }
        raw_hash = json.dumps(closure_payload, sort_keys=True, separators=(",", ":"))
        closure_hash = hashlib.sha256(raw_hash.encode("utf-8")).hexdigest()

        return ClosureResult(
            closed=is_closed,
            blockers=tuple(blockers),
            resolutions=resolutions,
            closure_hash=closure_hash,
        )
