"""
NouGenMorph Cognitive Evolution Engine.

Implements the formal extraction law:
    MorphScore = U * G * V * C * R - I
Where:
    U = Usefulness
    G = Generalizability
    V = Verifiability
    C = Architectural Compatibility
    R = Reversibility
    I = Integration Cost

Processes external donor systems through the lifecycle:
    DISCOVERED -> GENERALIZED -> CANDIDATE -> TESTED -> VERIFIED -> ADOPTED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence


class MorphKind(str, Enum):
    FACT = "fact"
    PATTERN = "pattern"
    BEHAVIOR = "behavior"
    MECHANISM = "mechanism"
    ALGORITHM = "algorithm"
    ANTI_PATTERN = "anti_pattern"
    EXPERIMENT = "experiment"


class AdoptionState(str, Enum):
    DISCOVERED = "discovered"
    GENERALIZED = "generalized"
    CANDIDATE = "candidate"
    TESTED = "tested"
    VERIFIED = "verified"
    ADOPTED = "adopted"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class MorphEvidence:
    source_uri: str
    claim: str
    confidence: float
    provenance: Optional[str] = None


@dataclass
class MorphCandidate:
    name: str
    kind: MorphKind
    donor_behavior: str
    generalized_behavior: str
    nougen_target: str
    evidence: List[MorphEvidence] = field(default_factory=list)

    usefulness: float = 0.0
    generalizability: float = 0.0
    verifiability: float = 0.0
    compatibility: float = 0.0
    reversibility: float = 0.0
    integration_cost: float = 0.0

    state: AdoptionState = AdoptionState.DISCOVERED

    def morph_score(self) -> float:
        """MorphScore = U * G * V * C * R - I"""
        positive = (
            self.usefulness
            * self.generalizability
            * self.verifiability
            * self.compatibility
            * self.reversibility
        )
        return positive - self.integration_cost


class NouGenMorphEngine:
    """Evaluates and filters donor candidates into verified fleet primitives."""

    def __init__(self, acceptance_threshold: float = 0.40):
        self.acceptance_threshold = acceptance_threshold
        self.registry: Dict[str, MorphCandidate] = {}

    def register_candidate(self, candidate: MorphCandidate) -> bool:
        score = candidate.morph_score()
        if score >= self.acceptance_threshold:
            candidate.state = AdoptionState.CANDIDATE
            self.registry[candidate.name] = candidate
            return True
        else:
            candidate.state = AdoptionState.QUARANTINED
            self.registry[candidate.name] = candidate
            return False

    def promote_to_adopted(self, name: str, verification_proof: str) -> bool:
        if name in self.registry:
            cand = self.registry[name]
            if cand.state in (AdoptionState.CANDIDATE, AdoptionState.VERIFIED, AdoptionState.TESTED):
                cand.state = AdoptionState.ADOPTED
                return True
        return False
