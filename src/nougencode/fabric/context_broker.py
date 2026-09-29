"""ContextBroker retrieval ensemble with dynamic refresh and coherence-debt gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from nougencode.canonical import canonical_sha256


def _canonical_hash(payload: Any) -> str:
    return canonical_sha256(payload)


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    source: str
    content: str
    confidence: float  # 0.0 to 1.0
    observed_at: str
    freshness_ttl_seconds: float
    claims: Sequence[str] = field(default_factory=tuple)
    references: Sequence[str] = field(default_factory=tuple)
    status: str = "OBSERVED"  # OBSERVED, UNKNOWN, STALE, CONTRADICTED

    def is_fresh(self, as_of: Optional[datetime] = None) -> bool:
        if self.status != "OBSERVED":
            return False
        now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            obs_dt = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except Exception:
            return False
        return obs_dt <= now <= obs_dt + timedelta(seconds=self.freshness_ttl_seconds)


@dataclass(frozen=True)
class CoherenceReport:
    is_admitted: bool
    coherence_debt_score: float  # 0.0 (perfect) to 1.0 (unusable)
    debt_threshold: float
    contradictions: Sequence[Tuple[str, str, str]]  # (item1_id, item2_id, reason)
    stale_items: Sequence[str]
    missing_references: Sequence[str]
    admitted_items: Sequence[ContextItem]
    rejection_reasons: Sequence[str]


class ContextBroker:
    """Retrieval ensemble combining multiple context lanes with coherence-debt gating."""

    def __init__(
        self,
        debt_threshold: float = 0.35,
        default_ttl_seconds: float = 300.0,
    ) -> None:
        self.debt_threshold = max(0.0, min(1.0, float(debt_threshold)))
        self.default_ttl_seconds = max(1.0, float(default_ttl_seconds))
        self._cache: Dict[str, ContextItem] = {}
        self._source_adapters: Dict[str, Callable[[str], Sequence[ContextItem]]] = {}

    def register_adapter(self, source_name: str, adapter: Callable[[str], Sequence[ContextItem]]) -> None:
        self._source_adapters[source_name] = adapter

    def invalidate(self, source_pattern: Optional[str] = None) -> int:
        """Invalidate cached context items by source pattern or flush all."""
        if source_pattern is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        to_delete = [k for k, v in self._cache.items() if source_pattern in v.source]
        for k in to_delete:
            del self._cache[k]
        return len(to_delete)

    def retrieve_ensemble(
        self,
        query: str,
        sources: Optional[Sequence[str]] = None,
        as_of: Optional[datetime] = None,
    ) -> Sequence[ContextItem]:
        """Query registered adapters and collect raw candidate items."""
        now = as_of or datetime.now(timezone.utc)
        active_sources = sources if sources is not None else list(self._source_adapters.keys())
        candidates: List[ContextItem] = []

        for src in active_sources:
            adapter = self._source_adapters.get(src)
            if not adapter:
                continue
            try:
                items = adapter(query)
                for it in items:
                    self._cache[it.item_id] = it
                    candidates.append(it)
            except Exception:
                # UNKNOWN semantics: failure to observe produces UNKNOWN status item
                unknown_item = ContextItem(
                    item_id=f"unknown-{src}-{_canonical_hash(query)[:8]}",
                    source=src,
                    content="",
                    confidence=0.0,
                    observed_at=now.isoformat(),
                    freshness_ttl_seconds=self.default_ttl_seconds,
                    status="UNKNOWN",
                )
                candidates.append(unknown_item)

        return candidates

    def evaluate_coherence(
        self,
        items: Sequence[ContextItem],
        as_of: Optional[datetime] = None,
    ) -> CoherenceReport:
        """Measure coherence debt and gate context admission."""
        now = as_of or datetime.now(timezone.utc)
        if not items:
            return CoherenceReport(
                is_admitted=True,
                coherence_debt_score=0.0,
                debt_threshold=self.debt_threshold,
                contradictions=(),
                stale_items=(),
                missing_references=(),
                admitted_items=(),
                rejection_reasons=(),
            )

        stale_ids: List[str] = []
        admitted: List[ContextItem] = []
        contradictions: List[Tuple[str, str, str]] = []
        all_item_ids = {it.item_id for it in items}
        all_claims: Dict[str, ContextItem] = {}
        missing_refs: List[str] = []

        for it in items:
            if not it.is_fresh(now):
                stale_ids.append(it.item_id)
            else:
                admitted.append(it)

            for ref in it.references:
                if ref not in all_item_ids:
                    missing_refs.append(ref)

            for claim in it.claims:
                negated = f"NOT {claim}" if not claim.startswith("NOT ") else claim[4:]
                if negated in all_claims:
                    contradictions.append(
                        (it.item_id, all_claims[negated].item_id, f"Contradictory claims: '{claim}' vs '{negated}'")
                    )
                all_claims[claim] = it

        # Coherence debt calculation: weighted penalty for stale, missing refs, and contradictions
        total = len(items)
        stale_penalty = (len(stale_ids) / total) * 0.40
        ref_penalty = (min(len(missing_refs), total) / total) * 0.25
        contradiction_penalty = (min(len(contradictions), total) / total) * 0.50

        coherence_debt = min(1.0, stale_penalty + ref_penalty + contradiction_penalty)
        is_admitted = coherence_debt < self.debt_threshold
        reasons: List[str] = []
        if not is_admitted:
            reasons.append(
                f"Coherence debt {coherence_debt:.3f} reached or exceeded threshold {self.debt_threshold:.3f}"
            )
            if contradictions:
                reasons.append(f"Found {len(contradictions)} logical contradiction(s)")
            if stale_ids:
                reasons.append(f"Found {len(stale_ids)} stale item(s)")

        return CoherenceReport(
            is_admitted=is_admitted,
            coherence_debt_score=round(coherence_debt, 4),
            debt_threshold=self.debt_threshold,
            contradictions=tuple(contradictions),
            stale_items=tuple(stale_ids),
            missing_references=tuple(set(missing_refs)),
            admitted_items=tuple(admitted) if is_admitted else (),
            rejection_reasons=tuple(reasons),
        )
