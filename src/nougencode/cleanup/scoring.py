"""Cleanup-pass scoring core.

Implements the repair/compression objective from relay leg 20261004T135520Z (source
20261004T040859Z__chatgpt-app). Every input is normalized to [0, 1] unless noted.

    ID    = (C*L*G*V*D) / (1 + LOCn + CC + DEP + AS)            intelligence density
    RP    = (S*R*F*B*U) / (1 + K)                               repair priority
    RED   = w1*AST + w2*SEM + w3*IO + w4*TEST + w5*STATE         redundancy similarity
    DV    = CR + DR + SR + BR + AR - CL - MC                     delete value
    MV    = (O*CR*SR*RR) / (1 + IR)                              merge value
    PV    = (N*O*STAB) / (1 + PE + VR)                           parameterization value
    Pdead = sigmoid(a1*unref + a2*uncov + a3*stale + a4*unreach + a5*unused_export - a6*dynamic)
    TBR   = EX*PRIV*MUT*UNSRC*REACH                              trust-boundary risk
    SG    = sum of normalized LOC/CC/DEP/STATE reductions        simplification gain
    J     = sum(SG + dCapability - TBR_after) over accepted actions

The weights and thresholds below are a *proposal*: the source leg left w1..w5, a1..a6 and every
threshold unspecified. They resolve env -> JSON file -> these defaults, so they can be tuned
without code changes. Nothing in this module mutates a repository; the action selector only
proposes, and any DELETE/MERGE still has to pass ``refactor_acceptance`` on real evidence.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

WEIGHTS_ENV = "NOUGENCODE_CLEANUP_WEIGHTS"  # path to a JSON file overriding DEFAULT_WEIGHTS

DEFAULT_WEIGHTS: Dict[str, float] = {
    # RED(a, b)
    "w_ast": 0.35, "w_sem": 0.25, "w_io": 0.15, "w_test": 0.10, "w_state": 0.15,
    # Pdead logit
    "a_unreferenced": 2.5, "a_uncovered": 1.0, "a_stale": 0.75, "a_unreachable": 2.0,
    "a_unused_export": 1.25, "a_dynamic_use": 3.0, "a_bias": -3.0,
    # selector thresholds
    "min_pdead_for_delete": 0.85,
    "min_red_for_merge": 0.80,
    "min_action_value": 0.15,
    "max_tbr_for_auto_action": 0.25,
}


def _clamp(x: float) -> float:
    return 0.0 if x != x else max(0.0, min(1.0, float(x)))  # NaN -> 0


def load_weights(path: Optional[str] = None) -> Dict[str, float]:
    """Defaults overlaid with a JSON file named by ``path`` or $NOUGENCODE_CLEANUP_WEIGHTS."""
    weights = dict(DEFAULT_WEIGHTS)
    src = path or os.environ.get(WEIGHTS_ENV)
    if src:
        data = json.loads(Path(src).read_text(encoding="utf-8"))
        unknown = set(data) - set(weights)
        if unknown:
            raise ValueError(f"unknown cleanup weight(s): {sorted(unknown)}")
        weights.update({k: float(v) for k, v in data.items()})
    return weights


def intelligence_density(C: float, L: float, G: float, V: float, D: float,
                         loc_n: float, cc: float, dep: float, abstraction: float) -> float:
    """Capability*leverage*generality*verifiability*determinism per unit of carried cost."""
    num = _clamp(C) * _clamp(L) * _clamp(G) * _clamp(V) * _clamp(D)
    return num / (1.0 + _clamp(loc_n) + _clamp(cc) + _clamp(dep) + _clamp(abstraction))


def repair_priority(S: float, R: float, F: float, B: float, U: float, K: float) -> float:
    """Severity*reach*frequency*blast-radius*urgency, discounted by repair cost K."""
    return (_clamp(S) * _clamp(R) * _clamp(F) * _clamp(B) * _clamp(U)) / (1.0 + _clamp(K))


def redundancy(ast_sim: float, sem_sim: float, io_sim: float, test_sim: float, state_sim: float,
               weights: Mapping[str, float] = DEFAULT_WEIGHTS) -> float:
    w = [weights["w_ast"], weights["w_sem"], weights["w_io"], weights["w_test"], weights["w_state"]]
    total = sum(w) or 1.0
    parts = [_clamp(ast_sim), _clamp(sem_sim), _clamp(io_sim), _clamp(test_sim), _clamp(state_sim)]
    return sum(wi * p for wi, p in zip(w, parts)) / total


def delete_value(CR: float, DR: float, SR: float, BR: float, AR: float, CL: float, MC: float) -> float:
    """Complexity+dependency+state+bug-surface+attack-surface removed, minus capability loss and migration cost.

    Range is [-2, 5]; the selector compares it against the other values on the same scale by
    dividing the positive part by 5 (see ``select_action``).
    """
    return (_clamp(CR) + _clamp(DR) + _clamp(SR) + _clamp(BR) + _clamp(AR)) - (_clamp(CL) + _clamp(MC))


def merge_value(overlap: float, CR: float, SR: float, RR: float, IR: float) -> float:
    """Overlap*complexity-removed*state-removed*redundancy-removed over integration risk."""
    return (_clamp(overlap) * _clamp(CR) * _clamp(SR) * _clamp(RR)) / (1.0 + _clamp(IR))


def parameterization_value(N: float, overlap: float, STAB: float, PE: float, VR: float) -> float:
    """Variant count*overlap*stability over parameter explosion and variant-specific risk."""
    return (_clamp(N) * _clamp(overlap) * _clamp(STAB)) / (1.0 + _clamp(PE) + _clamp(VR))


def dead_probability(unreferenced: float, uncovered: float, stale: float, unreachable: float,
                     unused_export: float, dynamic_use_evidence: float,
                     weights: Mapping[str, float] = DEFAULT_WEIGHTS) -> float:
    z = (weights["a_bias"]
         + weights["a_unreferenced"] * _clamp(unreferenced)
         + weights["a_uncovered"] * _clamp(uncovered)
         + weights["a_stale"] * _clamp(stale)
         + weights["a_unreachable"] * _clamp(unreachable)
         + weights["a_unused_export"] * _clamp(unused_export)
         - weights["a_dynamic_use"] * _clamp(dynamic_use_evidence))
    return 1.0 / (1.0 + math.exp(-z))


def trust_boundary_risk(EX: float, PRIV: float, MUT: float, UNSRC: float, REACH: float) -> float:
    """Exposure*privilege*mutation*untrusted-source*reachability. Any zero factor zeroes the risk."""
    return _clamp(EX) * _clamp(PRIV) * _clamp(MUT) * _clamp(UNSRC) * _clamp(REACH)


@dataclass(frozen=True)
class Metrics:
    """Raw (un-normalized) size metrics for a unit before or after a change."""
    loc: int
    cc: int
    deps: int
    state: int


def simplification_gain(before: Metrics, after: Metrics) -> float:
    """Sum of relative reductions in LOC, cyclomatic complexity, dependencies and mutable state.

    Each term is (before - after) / max(before, 1), so growth is negative and the sum is in [-inf, 4].
    """
    def rel(b: int, a: int) -> float:
        return (b - a) / max(b, 1)
    return rel(before.loc, after.loc) + rel(before.cc, after.cc) + rel(before.deps, after.deps) + rel(before.state, after.state)


@dataclass
class AcceptanceEvidence:
    capability_before: float
    capability_after: float
    correctness_before: float
    correctness_after: float
    before: Metrics
    after: Metrics
    required_tests_passed: Optional[bool]  # None = not run -> not accepted
    attack_surface_before: float
    attack_surface_after: float


@dataclass
class AcceptanceResult:
    accepted: bool
    reasons: list = field(default_factory=list)
    simplification_gain: float = 0.0


def refactor_acceptance(ev: AcceptanceEvidence) -> AcceptanceResult:
    """Gate every applied refactor: no capability/correctness regression, strictly lower complexity,
    required tests passed (unknown is a failure), no new attack surface."""
    reasons = []
    if ev.capability_after < ev.capability_before:
        reasons.append("capability regressed")
    if ev.correctness_after < ev.correctness_before:
        reasons.append("correctness regressed")
    if not (ev.after.cc < ev.before.cc or (ev.after.cc == ev.before.cc and ev.after.loc < ev.before.loc)):
        reasons.append("complexity not strictly lower")
    if ev.required_tests_passed is not True:
        reasons.append("required tests not passed" if ev.required_tests_passed is False else "required tests not run")
    if ev.attack_surface_after > ev.attack_surface_before:
        reasons.append("new attack surface")
    sg = simplification_gain(ev.before, ev.after)
    return AcceptanceResult(accepted=not reasons, reasons=reasons, simplification_gain=sg)


class CleanupAction(str, Enum):
    DELETE = "DELETE"
    MERGE = "MERGE"
    PARAMETERIZE = "PARAMETERIZE"
    REPAIR = "REPAIR"
    KEEP = "KEEP"


@dataclass
class ActionDecision:
    action: CleanupAction
    value: float
    candidates: Dict[str, float]
    blocked: list
    requires_review: bool


def select_action(*, dv: float, mv: float, pv: float, rp: float, pdead: float, red: float, tbr: float,
                  weights: Mapping[str, float] = DEFAULT_WEIGHTS) -> ActionDecision:
    """argmax over {DV, MV, PV, RP} subject to safety constraints.

    Constraints: DELETE needs Pdead >= min_pdead_for_delete; MERGE needs RED >= min_red_for_merge;
    the winner must clear min_action_value or the unit is KEPT. Anything with TBR above
    max_tbr_for_auto_action, and every DELETE/MERGE, is flagged requires_review: the selector never
    authorizes an unattended destructive change.
    """
    cand = {
        CleanupAction.DELETE.value: max(dv, 0.0) / 5.0,
        CleanupAction.MERGE.value: mv,
        CleanupAction.PARAMETERIZE.value: pv,
        CleanupAction.REPAIR.value: rp,
    }
    blocked = []
    if pdead < weights["min_pdead_for_delete"]:
        blocked.append(f"DELETE: Pdead {pdead:.2f} < {weights['min_pdead_for_delete']}")
        cand.pop(CleanupAction.DELETE.value)
    if red < weights["min_red_for_merge"]:
        blocked.append(f"MERGE: RED {red:.2f} < {weights['min_red_for_merge']}")
        cand.pop(CleanupAction.MERGE.value)
    if not cand:
        return ActionDecision(CleanupAction.KEEP, 0.0, {}, blocked, tbr > weights["max_tbr_for_auto_action"])
    name, val = max(cand.items(), key=lambda kv: (kv[1], kv[0]))
    if val < weights["min_action_value"]:
        return ActionDecision(CleanupAction.KEEP, val, cand, blocked, tbr > weights["max_tbr_for_auto_action"])
    action = CleanupAction(name)
    review = action in (CleanupAction.DELETE, CleanupAction.MERGE) or tbr > weights["max_tbr_for_auto_action"]
    return ActionDecision(action, val, cand, blocked, review)


def net_objective(accepted: Sequence[Dict[str, float]]) -> float:
    """J = sum(SG + capability_delta - TBR_after) over accepted actions; maximize."""
    return sum(a.get("sg", 0.0) + a.get("capability_delta", 0.0) - a.get("tbr_after", 0.0) for a in accepted)


def as_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: as_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: as_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [as_dict(v) for v in obj]
    return obj
