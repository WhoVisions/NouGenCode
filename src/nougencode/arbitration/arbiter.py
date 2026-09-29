"""Evidence arbiter, claims, disagreement graph, and proof object compilation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Dict, List

from nougencode.routing.switchboard import ExecutionStatus


@dataclass
class Claim:
    """Explicit claim with evidence weighting."""
    id: str
    statement: str
    severity: float  # 0.0 to 1.0 (1.0 = blocking / critical)
    confidence: float
    evidence: List[str] = field(default_factory=list)
    supporters: List[str] = field(default_factory=list)
    opponents: List[str] = field(default_factory=list)
    resolved: bool = False

    @property
    def is_blocking(self) -> bool:
        """A claim is blocking if unresolved, critical, and supported by concrete evidence."""
        return not self.resolved and self.severity >= 0.7 and len(self.evidence) > 0


@dataclass(frozen=True)
class EvidenceReceipt:
    """Immutable content-addressed evidence reference without copying raw payloads."""

    stage: str
    source: str
    sha256: str
    observed_at: str

    @classmethod
    def from_payload(cls, stage: str, source: str, payload: Any) -> "EvidenceReceipt":
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return cls(
            stage=stage,
            source=source,
            sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            observed_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass
class ProofObject:
    """Formal proof object verifying repository mutation state."""
    schema: str = "nougen.code.proof.v1"
    task_id: str = ""
    baseline_commit: str = ""
    mutations: List[Dict[str, Any]] = field(default_factory=list)
    validation: Dict[str, str] = field(default_factory=dict)
    reviews: Dict[str, str] = field(default_factory=dict)
    unresolved_claims: List[str] = field(default_factory=list)
    evidence_receipts: tuple[EvidenceReceipt, ...] = ()
    result: str = "verified"  # verified, rejected, replan
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "baseline_commit": self.baseline_commit,
            "mutations": self.mutations,
            "validation": self.validation,
            "reviews": self.reviews,
            "unresolved_claims": self.unresolved_claims,
            "evidence_receipts": [receipt.__dict__ for receipt in self.evidence_receipts],
            "result": self.result,
            "timestamp": self.timestamp,
        }


class EvidenceArbiter:
    """Ranks evidence over model eloquence and resolves claims non-democratically."""

    # Hierarchy: Runtime > Targeted Test > Static Proof > Repo Evidence > Shards > Reasoning
    EVIDENCE_WEIGHTS = {
        "runtime_reproduction": 1.0,
        "targeted_automated_test": 0.95,
        "static_proof": 0.85,
        "repo_architecture": 0.70,
        "historical_shard": 0.60,
        "model_reasoning": 0.30,
        "model_confidence": 0.10,
    }

    def evaluate_claims(self, claims: List[Claim]) -> bool:
        """Returns True if all claims permit shipping (no blocking critical claims)."""
        for claim in claims:
            if claim.is_blocking:
                return False
        return True

    def compile_proof(
        self,
        task_id: str,
        baseline_commit: str,
        mutations: List[Dict[str, Any]],
        validation_results: Dict[str, ExecutionStatus],
        claims: List[Claim],
        evidence_receipts: tuple[EvidenceReceipt, ...] = (),
    ) -> ProofObject:
        """Compiles canonical proof object."""
        can_ship = self.evaluate_claims(claims)
        unresolved = [c.id for c in claims if not c.resolved]
        val_summary = {k: v.value for k, v in validation_results.items()}

        all_tests_passed = all(
            status == ExecutionStatus.PASS
            for status in validation_results.values()
        )

        result_verdict = "verified" if (can_ship and all_tests_passed) else "rejected"

        return ProofObject(
            task_id=task_id,
            baseline_commit=baseline_commit,
            mutations=mutations,
            validation=val_summary,
            reviews={"security": "pass" if can_ship else "blocked"},
            unresolved_claims=unresolved,
            evidence_receipts=evidence_receipts,
            result=result_verdict,
        )
