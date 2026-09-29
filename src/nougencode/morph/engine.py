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
import hashlib
import json
from math import isfinite
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

    def __post_init__(self) -> None:
        if not self.source_uri.strip() or not self.claim.strip():
            raise ValueError("Morph evidence needs a source and claim")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("Morph evidence confidence must be finite and within [0, 1]")


@dataclass(frozen=True)
class MorphTestResult:
    test_id: str
    passed: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.test_id.strip() or not self.evidence_ref.strip():
            raise ValueError("Morph test result needs a test id and evidence reference")


@dataclass(frozen=True)
class MorphVerificationProof:
    candidate_digest: str
    verifier_id: str
    test_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    proof_ref: str
    passed: bool

    def __post_init__(self) -> None:
        if not all((self.candidate_digest, self.verifier_id.strip(), self.proof_ref.strip())):
            raise ValueError("Morph verification proof needs candidate, verifier, and proof references")
        if not self.test_ids or not self.evidence_refs:
            raise ValueError("Morph verification proof must reference tests and evidence")


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
    proposer_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.name, self.donor_behavior,
                                                self.generalized_behavior, self.nougen_target)):
            raise ValueError("Morph candidate text fields must be non-empty")
        for field_name in ("usefulness", "generalizability", "verifiability",
                           "compatibility", "reversibility", "integration_cost"):
            value = getattr(self, field_name)
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be finite and within [0, 1]")
        if self.proposer_id is not None and not self.proposer_id.strip():
            raise ValueError("proposer_id cannot be blank")

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

    def digest(self) -> str:
        """Stable digest of the proposed primitive, independent of lifecycle state."""
        body = {
            "name": self.name,
            "kind": self.kind.value,
            "donor_behavior": self.donor_behavior,
            "generalized_behavior": self.generalized_behavior,
            "nougen_target": self.nougen_target,
            "evidence": [
                {"source_uri": item.source_uri, "claim": item.claim,
                 "confidence": item.confidence, "provenance": item.provenance}
                for item in self.evidence
            ],
            "proposer_id": self.proposer_id,
            "metrics": [self.usefulness, self.generalizability, self.verifiability,
                        self.compatibility, self.reversibility, self.integration_cost],
        }
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class NouGenMorphEngine:
    """Evaluates and filters donor candidates into verified fleet primitives."""

    def __init__(self, acceptance_threshold: float = 0.40):
        if not isfinite(acceptance_threshold):
            raise ValueError("acceptance_threshold must be finite")
        self.acceptance_threshold = acceptance_threshold
        self.registry: Dict[str, MorphCandidate] = {}
        self.test_results: Dict[str, Dict[str, MorphTestResult]] = {}
        self.verification_digests: Dict[str, str] = {}

    def register_candidate(self, candidate: MorphCandidate) -> bool:
        score = candidate.morph_score()
        generalized = candidate.generalized_behavior.lower()
        target = candidate.nougen_target.lower()
        provider_brand_in_rule = any(brand in generalized or brand in target
                                     for brand in ("claude", "codex", "cursor", "gemini", "anthropic", "openai"))
        evidence_complete = bool(candidate.evidence) and all(
            item.provenance and item.provenance.strip() for item in candidate.evidence
        )
        if score >= self.acceptance_threshold and evidence_complete and not provider_brand_in_rule:
            candidate.state = AdoptionState.CANDIDATE
            self.registry[candidate.name] = candidate
            return True
        candidate.state = AdoptionState.QUARANTINED
        self.registry[candidate.name] = candidate
        return False

    def record_test_result(self, name: str, result: MorphTestResult) -> bool:
        """Record fixture-backed tests; any failure quarantines the candidate."""
        candidate = self.registry.get(name)
        if candidate is None or candidate.state not in {AdoptionState.CANDIDATE, AdoptionState.TESTED}:
            return False
        tests = self.test_results.setdefault(name, {})
        prior = tests.get(result.test_id)
        if prior is not None:
            if prior != result:
                raise ValueError("test id was reused for a different result")
            return False
        tests[result.test_id] = result
        if not result.passed:
            candidate.state = AdoptionState.QUARANTINED
            return False
        candidate.state = AdoptionState.TESTED
        return True

    def verify_candidate(self, name: str, proof: MorphVerificationProof) -> bool:
        """Advance only when an independent verifier binds proof to recorded tests."""
        candidate = self.registry.get(name)
        if candidate is None or candidate.state is not AdoptionState.TESTED:
            return False
        if not proof.passed or proof.candidate_digest != candidate.digest():
            return False
        if candidate.proposer_id is None or proof.verifier_id == candidate.proposer_id:
            return False
        tests = self.test_results.get(name, {})
        if not proof.test_ids or set(proof.test_ids) != set(tests):
            return False
        if any(not tests[test_id].passed for test_id in proof.test_ids):
            return False
        expected_evidence = {tests[test_id].evidence_ref for test_id in proof.test_ids}
        if not expected_evidence <= set(proof.evidence_refs):
            return False
        candidate.state = AdoptionState.VERIFIED
        canonical = json.dumps({
            "candidate_digest": proof.candidate_digest,
            "verifier_id": proof.verifier_id,
            "test_ids": sorted(proof.test_ids),
            "evidence_refs": sorted(proof.evidence_refs),
            "proof_ref": proof.proof_ref,
            "passed": proof.passed,
        }, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.verification_digests[name] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return True

    def promote_to_adopted(self, name: str, verification_proof: MorphVerificationProof) -> bool:
        candidate = self.registry.get(name)
        expected = self.verification_digests.get(name)
        if (candidate is None or candidate.state is not AdoptionState.VERIFIED
                or not isinstance(verification_proof, MorphVerificationProof)):
            return False
        if not verification_proof.passed or candidate.digest() != verification_proof.candidate_digest:
            return False
        supplied = json.dumps({
            "candidate_digest": verification_proof.candidate_digest,
            "verifier_id": verification_proof.verifier_id,
            "test_ids": sorted(verification_proof.test_ids),
            "evidence_refs": sorted(verification_proof.evidence_refs),
            "proof_ref": verification_proof.proof_ref,
            "passed": verification_proof.passed,
        }, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if expected != hashlib.sha256(supplied.encode("utf-8")).hexdigest():
            return False
        candidate.state = AdoptionState.ADOPTED
        return True
