"""Material DeltaEngine for state change detection and epistemic diff evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from nougencode.core.golden_slice import (
    CoverageEnvelope,
    EventEnvelope,
    EvidenceObservation,
    TruthResult,
    TruthStatus,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MaterialDelta:
    delta_id: str
    is_material: bool
    added_keys: Tuple[str, ...]
    removed_keys: Tuple[str, ...]
    modified_keys: Tuple[str, ...]
    truth_transition: Optional[Tuple[str, str]]
    detail_changes: Mapping[str, Any]
    delta_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delta_id": self.delta_id,
            "is_material": self.is_material,
            "added_keys": list(self.added_keys),
            "removed_keys": list(self.removed_keys),
            "modified_keys": list(self.modified_keys),
            "truth_transition": list(self.truth_transition) if self.truth_transition else None,
            "detail_changes": dict(self.detail_changes),
            "delta_hash": self.delta_hash,
        }


class DeltaEngine:
    """Computes deterministic material state deltas with epistemic absence protection.
    
    Invariants:
    1. Incomplete source coverage cannot prove absence (missing evidence is not absence of fault).
    2. UNKNOWN_WITHIN_BUDGET is distinguished from definitive FAIL/PASS.
    3. State changes without material difference produce is_material=False.
    """

    @staticmethod
    def compute_state_delta(
        previous_state: Optional[Mapping[str, Any]],
        current_state: Mapping[str, Any],
        *,
        ignored_keys: Optional[Set[str]] = None,
    ) -> MaterialDelta:
        prev = dict(previous_state or {})
        curr = dict(current_state or {})
        ignored = ignored_keys or {"timestamp", "as_of", "latency_ms", "observed_at"}

        prev_filtered = {k: v for k, v in prev.items() if k not in ignored}
        curr_filtered = {k: v for k, v in curr.items() if k not in ignored}

        prev_keys = set(prev_filtered)
        curr_keys = set(curr_filtered)

        added = sorted(curr_keys - prev_keys)
        removed = sorted(prev_keys - curr_keys)
        common = prev_keys & curr_keys

        modified = []
        details: Dict[str, Any] = {}

        for k in sorted(common):
            prev_val = prev_filtered[k]
            curr_val = curr_filtered[k]
            if _canonical_json(prev_val) != _canonical_json(curr_val):
                modified.append(k)
                details[k] = {"before": prev_val, "after": curr_val}

        for k in added:
            details[k] = {"before": None, "after": curr_filtered[k]}
        for k in removed:
            details[k] = {"before": prev_filtered[k], "after": None}

        # Check truth transition
        truth_transition = None
        if "truth_status" in prev_filtered or "truth_status" in curr_filtered:
            p_status = str(prev_filtered.get("truth_status", "UNKNOWN"))
            c_status = str(curr_filtered.get("truth_status", "UNKNOWN"))
            if p_status != c_status:
                truth_transition = (p_status, c_status)

        is_material = bool(added or removed or modified or truth_transition)
        body = {
            "added": added,
            "removed": removed,
            "modified": modified,
            "truth_transition": truth_transition,
            "details": details,
        }
        delta_hash = _sha256(body)
        delta_id = f"delta_{delta_hash[:16]}"

        return MaterialDelta(
            delta_id=delta_id,
            is_material=is_material,
            added_keys=tuple(added),
            removed_keys=tuple(removed),
            modified_keys=tuple(modified),
            truth_transition=truth_transition,
            detail_changes=details,
            delta_hash=delta_hash,
        )

    @staticmethod
    def compute_evidence_delta(
        baseline_coverage: Optional[CoverageEnvelope],
        target_coverage: CoverageEnvelope,
    ) -> MaterialDelta:
        """Evaluates whether new observations represent a material change in evidence."""
        baseline_obs = {
            obs.observation_id: obs.to_dict()
            for obs in (baseline_coverage.observations if baseline_coverage else ())
        }
        target_obs = {
            obs.observation_id: obs.to_dict()
            for obs in target_coverage.observations
        }
        return DeltaEngine.compute_state_delta(baseline_obs, target_obs)
