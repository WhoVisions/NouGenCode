"""Lossless, deterministic partitioning for already-extracted meaning units.

Semantic extraction is deliberately an upstream model task. This module does
not claim to infer meaning from raw prose; it orders and partitions a sourced
unit graph while enforcing size and qualification/dependency constraints.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Sequence


class DigestibilityError(ValueError):
    pass


@dataclass(frozen=True)
class MeaningUnit:
    unit_id: str
    text: str
    source_ref: str
    token_cost: int
    depends_on: tuple[str, ...] = ()
    qualifies: tuple[str, ...] = ()
    required: bool = True
    introduces_concepts: tuple[str, ...] = ()
    specialist_terms: tuple[str, ...] = ()
    decisions: int = 0


@dataclass(frozen=True)
class Chunk:
    unit_ids: tuple[str, ...]
    text: str
    token_cost: int


@dataclass(frozen=True)
class ChunkPlan:
    chunks: tuple[Chunk, ...]
    objective_cost: float
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class ReaderContext:
    """Only explicitly known concepts are treated as known."""
    known_concepts: frozenset[str] = frozenset()
    known_terms: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ComprehensionWeights:
    new_concept: float = 1.0
    unresolved_dependency: float = 2.0
    unexplained_term: float = 1.0
    decision: float = 1.0


@dataclass(frozen=True)
class Verification:
    missing_units: tuple[str, ...]
    added_claims: tuple[str, ...]
    certainty_changes: tuple[str, ...]
    instruction_order_ok: bool
    source_coverage_ok: bool

    @property
    def passed(self) -> bool:
        return (not self.missing_units and not self.added_claims
                and not self.certainty_changes and self.instruction_order_ok
                and self.source_coverage_ok)


def comprehension_cost(
    chunk: Sequence[MeaningUnit], reader: ReaderContext, *,
    weights: ComprehensionWeights = ComprehensionWeights(),
) -> float:
    """Calibratable proposed cost; does not claim to measure comprehension."""
    known = set(reader.known_concepts)
    new_concepts = {concept for unit in chunk for concept in unit.introduces_concepts} - known
    present = {unit.unit_id for unit in chunk}
    unresolved = {dep for unit in chunk for dep in unit.depends_on} - present - known
    terms = {term for unit in chunk for term in unit.specialist_terms} - reader.known_terms
    decisions = sum(unit.decisions for unit in chunk)
    return (weights.new_concept * len(new_concepts)
            + weights.unresolved_dependency * len(unresolved)
            + weights.unexplained_term * len(terms)
            + weights.decision * decisions)


def _validate(units: Sequence[MeaningUnit], budget: int) -> dict[str, int]:
    if budget <= 0:
        raise DigestibilityError("budget must be positive")
    positions: dict[str, int] = {}
    for i, unit in enumerate(units):
        if not unit.unit_id or unit.unit_id in positions:
            raise DigestibilityError("unit ids must be unique and non-empty")
        if not unit.source_ref or not unit.text.strip() or unit.token_cost <= 0:
            raise DigestibilityError(f"unit {unit.unit_id!r} needs text, source and positive token cost")
        if unit.token_cost > budget:
            raise DigestibilityError(f"unit {unit.unit_id!r} exceeds the hard budget and cannot be split losslessly")
        positions[unit.unit_id] = i
    for i, unit in enumerate(units):
        for dep in (*unit.depends_on, *unit.qualifies):
            if dep not in positions:
                raise DigestibilityError(f"unit {unit.unit_id!r} references missing unit {dep!r}")
            if positions[dep] > i:
                raise DigestibilityError(f"input order violates dependency/qualification {dep!r} -> {unit.unit_id!r}")
            # Keep qualifications with the claim they constrain.
            if dep in unit.qualifies and positions[dep] != i - 1:
                raise DigestibilityError(f"qualification {dep!r} must immediately precede {unit.unit_id!r}")
    return positions


def partition_units(
    units: Sequence[MeaningUnit], *, max_tokens: int, target_tokens: int | None = None,
    fragmentation_penalty: float = 1.0, repetition_penalty: float = 0.5,
    balance_weight: float = 0.25, reader: ReaderContext | None = None,
    weights: ComprehensionWeights = ComprehensionWeights(),
) -> ChunkPlan:
    """Minimize reader burden, repetition, fragmentation, and size imbalance.

    Atomic units stay intact and in source order. Hard budget is max_tokens.
    A chunk boundary may not split a qualification pair. The exact cost model
    is explicit and tunable; readability still requires empirical evaluation.
    Dependencies in earlier chunks count as introduced; future dependencies
    count as unresolved. The default reader has no assumed prior knowledge.
    """
    values = tuple(units)
    _validate(values, max_tokens)
    if not values:
        return ChunkPlan((), 0.0, ())
    target = max_tokens if target_tokens is None else target_tokens
    if target <= 0 or target > max_tokens:
        raise DigestibilityError("target_tokens must be in (0, max_tokens]")
    if any(value < 0 for value in (fragmentation_penalty, repetition_penalty, balance_weight)):
        raise DigestibilityError("objective penalties must be non-negative")
    reader = reader or ReaderContext()
    n = len(values)
    positions = {unit.unit_id: i for i, unit in enumerate(values)}
    # Suffix dynamic program: dp[i] is cheapest partition of units[i:].
    dp = [inf] * (n + 1)
    choice = [-1] * n
    dp[n] = 0.0
    for i in range(n - 1, -1, -1):
        cost = 0
        for j in range(i, n):
            cost += values[j].token_cost
            if cost > max_tokens:
                break
            # Do not split any immediately adjacent qualification pair.
            if j < n - 1 and (values[j + 1].unit_id in values[j].qualifies
                               or values[j].unit_id in values[j + 1].qualifies):
                continue
            group = values[i:j + 1]
            present = {unit.unit_id for unit in group}
            introduced_before = {concept for unit in values[:i]
                                 for concept in unit.introduces_concepts}
            known = reader.known_concepts | introduced_before
            new_concepts = {concept for unit in group
                            for concept in unit.introduces_concepts} - known
            unresolved = {dep for unit in group for dep in unit.depends_on
                          if positions[dep] > j} - present - known
            terms = {term for unit in group for term in unit.specialist_terms} - reader.known_terms
            decisions = sum(unit.decisions for unit in group)
            reader_cost = (weights.new_concept * len(new_concepts)
                           + weights.unresolved_dependency * len(unresolved)
                           + weights.unexplained_term * len(terms)
                           + weights.decision * decisions)
            repeats = sum(1 for unit in group for concept in unit.introduces_concepts
                          if concept in known)
            balance = balance_weight * ((cost - target) / target) ** 2
            candidate = (reader_cost + repetition_penalty * repeats
                         + fragmentation_penalty + balance + dp[j + 1])
            if candidate < dp[i]:
                dp[i], choice[i] = candidate, j + 1
    if choice[0] < 0:
        raise DigestibilityError("no valid partition satisfies constraints")
    chunks: list[Chunk] = []
    i = 0
    while i < n:
        end = choice[i]
        group = values[i:end]
        chunks.append(Chunk(tuple(unit.unit_id for unit in group),
                            " ".join(unit.text.strip() for unit in group),
                            sum(unit.token_cost for unit in group)))
        i = end
    return ChunkPlan(tuple(chunks), dp[0], tuple(unit.source_ref for unit in values))


def verify_plan(units: Sequence[MeaningUnit], plan: ChunkPlan, *, max_tokens: int) -> bool:
    """Structural checks only; this cannot prove human comprehension or truth."""
    expected = [unit.unit_id for unit in units if unit.required]
    actual = [unit_id for chunk in plan.chunks for unit_id in chunk.unit_ids]
    if actual != expected:
        return False
    if any(chunk.token_cost > max_tokens for chunk in plan.chunks):
        return False
    if tuple(unit.source_ref for unit in units) != plan.source_refs:
        return False
    return True


def verify_rendering(
    units: Sequence[MeaningUnit], *, missing_units: Sequence[str],
    added_claims: Sequence[str], certainty_changes: Sequence[str],
    output_unit_order: Sequence[str],
) -> Verification:
    """Package extractor/verifier observations without asserting their accuracy.

    A semantic verifier may supply these observations; the caller must retain
    its model/version and source spans. This function only checks coverage and
    dependency order over the returned IDs.
    """
    known = {unit.unit_id for unit in units}
    positions = {unit_id: i for i, unit_id in enumerate(output_unit_order)}
    order_ok = all(dep not in positions or unit.unit_id not in positions
                   or positions[dep] < positions[unit.unit_id]
                   for unit in units for dep in unit.depends_on)
    expected_sources = {unit.source_ref for unit in units if unit.required}
    represented_sources = {unit.source_ref for unit in units if unit.unit_id in positions}
    return Verification(tuple(missing_units), tuple(added_claims),
                        tuple(certainty_changes), order_ok,
                        expected_sources <= represented_sources and known >= set(output_unit_order))
