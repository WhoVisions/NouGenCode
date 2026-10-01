"""Independent Verification Receipt engine for NouGenCode hourly worker kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from nougencode.core.golden_slice import (
    CoverageEnvelope,
    EventEnvelope,
    GoldenSliceResult,
    TruthResult,
    TruthStatus,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerificationReceipt:
    receipt_id: str
    stage: str
    source_id: str
    tenant_id: str
    mission_id: str
    observed_at: str
    truth_status: str
    decision_action: str
    decision_hash: str
    fence_token: int
    payload_sha256: str
    is_verified: bool
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "stage": self.stage,
            "source_id": self.source_id,
            "tenant_id": self.tenant_id,
            "mission_id": self.mission_id,
            "observed_at": self.observed_at,
            "truth_status": self.truth_status,
            "decision_action": self.decision_action,
            "decision_hash": self.decision_hash,
            "fence_token": self.fence_token,
            "payload_sha256": self.payload_sha256,
            "is_verified": self.is_verified,
        }


class VerificationEngine:
    """Generates and independently verifies cryptographic execution receipts."""

    @staticmethod
    def generate_receipt(
        *,
        stage: str,
        source_id: str,
        tenant_id: str,
        mission_id: str,
        truth: TruthResult,
        decision_action: str,
        decision_hash: str,
        fence_token: int,
        raw_payload: Mapping[str, Any],
        as_of: datetime,
    ) -> VerificationReceipt:
        payload_hash = _sha256(raw_payload)
        observed_at = as_of.astimezone(timezone.utc).isoformat()
        
        # Determine verified status: truth is PASS or FAIL (resolved), fence > 0
        is_verified = truth.status in {TruthStatus.PASS, TruthStatus.FAIL} and fence_token > 0
        
        receipt_body = {
            "stage": stage,
            "source_id": source_id,
            "tenant_id": tenant_id,
            "mission_id": mission_id,
            "observed_at": observed_at,
            "truth_status": truth.status.value,
            "decision_action": decision_action,
            "decision_hash": decision_hash,
            "fence_token": fence_token,
            "payload_sha256": payload_hash,
        }
        receipt_id = f"rcpt_{_sha256(receipt_body)[:24]}"
        
        return VerificationReceipt(
            receipt_id=receipt_id,
            stage=stage,
            source_id=source_id,
            tenant_id=tenant_id,
            mission_id=mission_id,
            observed_at=observed_at,
            truth_status=truth.status.value,
            decision_action=decision_action,
            decision_hash=decision_hash,
            fence_token=fence_token,
            payload_sha256=payload_hash,
            is_verified=is_verified,
        )

    @staticmethod
    def verify_receipt(receipt: VerificationReceipt, raw_payload: Mapping[str, Any]) -> bool:
        """Independently verifies that the receipt's payload hash matches the actual payload."""
        expected_hash = _sha256(raw_payload)
        return receipt.payload_sha256 == expected_hash
