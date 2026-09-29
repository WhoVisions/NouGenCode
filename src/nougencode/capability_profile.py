"""Validation and freshness evaluation for portable scheduler profiles."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = Path(__file__).with_name("schemas") / "scheduler-capability-profile.schema.json"


class CapabilityProfileError(ValueError):
    """Raised when a capability profile violates the published contract."""


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise CapabilityProfileError(f"{field} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CapabilityProfileError(f"{field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise CapabilityProfileError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CapabilityProfileError(f"{field} must be an object")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityProfileError(f"{field} must be a non-empty string")
    return value


def _reject_extra(item: Mapping[str, Any], allowed: set[str], field: str) -> None:
    extra = sorted(set(item) - allowed)
    if extra:
        raise CapabilityProfileError(f"{field} has unsupported field(s): {', '.join(extra)}")


def _validate_observation(observation: Any, field: str) -> None:
    item = _require_mapping(observation, field)
    _reject_extra(
        item,
        {"observation_id", "metric", "value", "unit", "status", "observed_at", "source", "freshness_ttl_seconds", "unknown_reason"},
        field,
    )
    for key in ("observation_id", "metric"):
        _require_text(item.get(key), f"{field}.{key}")
    for key in ("unit", "unknown_reason"):
        if key in item and not isinstance(item[key], str):
            raise CapabilityProfileError(f"{field}.{key} must be a string")
    if item.get("status") not in {"OBSERVED", "UNKNOWN", "STALE"}:
        raise CapabilityProfileError(f"{field}.status must be OBSERVED, UNKNOWN, or STALE")
    _parse_timestamp(item.get("observed_at"), f"{field}.observed_at")
    ttl = item.get("freshness_ttl_seconds")
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl < 0:
        raise CapabilityProfileError(f"{field}.freshness_ttl_seconds must be a non-negative number")
    source = _require_mapping(item.get("source"), f"{field}.source")
    _reject_extra(source, {"kind", "name", "version", "reference"}, f"{field}.source")
    if source.get("kind") not in {"command", "api", "benchmark", "log", "adapter", "operator"}:
        raise CapabilityProfileError(f"{field}.source.kind is not supported")
    _require_text(source.get("name"), f"{field}.source.name")
    for key in ("version", "reference"):
        if key in source and not isinstance(source[key], str):
            raise CapabilityProfileError(f"{field}.source.{key} must be a string")
    if item["status"] == "UNKNOWN":
        _require_text(item.get("unknown_reason"), f"{field}.unknown_reason")
        if item.get("value") is not None:
            raise CapabilityProfileError(f"{field}.value must be null when status is UNKNOWN")


def _observations(value: Any, field: str, *, require_one: bool = False) -> List[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise CapabilityProfileError(f"{field} must be an array")
    if require_one and not value:
        raise CapabilityProfileError(f"{field} must contain at least one provenance-bearing observation")
    for index, observation in enumerate(value):
        _validate_observation(observation, f"{field}[{index}]")
    return value


def validate_profile(profile: Any) -> Mapping[str, Any]:
    """Validate the portable profile contract and return the original mapping.

    The validator is deliberately standard-library-only so worker agents can run it
    before an optional scheduler plugin or JSON Schema package is installed.
    """
    root = _require_mapping(profile, "profile")
    _reject_extra(root, {"schema_version", "profile_id", "observed_at", "worker", "devices", "capabilities", "recommendations"}, "profile")
    if root.get("schema_version") != SCHEMA_VERSION:
        raise CapabilityProfileError(f"profile.schema_version must be {SCHEMA_VERSION}")
    _require_text(root.get("profile_id"), "profile.profile_id")
    _parse_timestamp(root.get("observed_at"), "profile.observed_at")

    worker = _require_mapping(root.get("worker"), "profile.worker")
    _reject_extra(worker, {"worker_id", "display_name", "observations"}, "profile.worker")
    _require_text(worker.get("worker_id"), "profile.worker.worker_id")
    if "display_name" in worker and not isinstance(worker["display_name"], str):
        raise CapabilityProfileError("profile.worker.display_name must be a string")
    evidence_ids = set()
    worker_observations = _observations(worker.get("observations"), "profile.worker.observations")
    for observation in worker_observations:
        observation_id = observation["observation_id"]
        if observation_id in evidence_ids:
            raise CapabilityProfileError(f"duplicate observation_id: {observation_id}")
        evidence_ids.add(observation_id)

    devices = root.get("devices")
    if not isinstance(devices, list):
        raise CapabilityProfileError("profile.devices must be an array")
    for index, device_value in enumerate(devices):
        device = _require_mapping(device_value, f"profile.devices[{index}]")
        _reject_extra(device, {"device_id", "kind", "observations"}, f"profile.devices[{index}]")
        _require_text(device.get("device_id"), f"profile.devices[{index}].device_id")
        _require_text(device.get("kind"), f"profile.devices[{index}].kind")
        device_observations = _observations(device.get("observations"), f"profile.devices[{index}].observations")
        for observation in device_observations:
            observation_id = observation["observation_id"]
            if observation_id in evidence_ids:
                raise CapabilityProfileError(f"duplicate observation_id: {observation_id}")
            evidence_ids.add(observation_id)

    capabilities = root.get("capabilities")
    if not isinstance(capabilities, list):
        raise CapabilityProfileError("profile.capabilities must be an array")
    workload_ids = set()
    recommendation_refs = []
    for index, capability_value in enumerate(capabilities):
        field = f"profile.capabilities[{index}]"
        capability = _require_mapping(capability_value, field)
        _reject_extra(capability, {"workload_id", "kind", "result", "parameters", "observations", "artifacts"}, field)
        workload_id = _require_text(capability.get("workload_id"), f"{field}.workload_id")
        if workload_id in workload_ids:
            raise CapabilityProfileError(f"duplicate workload_id: {workload_id}")
        workload_ids.add(workload_id)
        _require_text(capability.get("kind"), f"{field}.kind")
        if capability.get("result") not in {"PASS", "FAIL", "UNKNOWN"}:
            raise CapabilityProfileError(f"{field}.result must be PASS, FAIL, or UNKNOWN")
        _require_mapping(capability.get("parameters"), f"{field}.parameters")
        observations = _observations(capability.get("observations"), f"{field}.observations", require_one=True)
        outcomes = [observation for observation in observations if observation.get("metric") == "outcome"]
        if not outcomes:
            raise CapabilityProfileError(f"{field} needs an outcome observation with provenance")
        if len(outcomes) != 1:
            raise CapabilityProfileError(f"{field} must contain exactly one outcome observation")
        outcome = outcomes[0]
        if outcome.get("status") == "OBSERVED" and outcome.get("value") != capability["result"]:
            raise CapabilityProfileError(f"{field}.result must match its observed outcome")
        if outcome.get("status") == "UNKNOWN" and capability["result"] != "UNKNOWN":
            raise CapabilityProfileError(f"{field}.result must be UNKNOWN when its outcome is UNKNOWN")
        for observation in observations:
            observation_id = observation["observation_id"]
            if observation_id in evidence_ids:
                raise CapabilityProfileError(f"duplicate observation_id: {observation_id}")
            evidence_ids.add(observation_id)

        artifacts = capability.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise CapabilityProfileError(f"{field}.artifacts must be an array")
        for artifact_index, artifact_value in enumerate(artifacts):
            artifact_field = f"{field}.artifacts[{artifact_index}]"
            artifact = _require_mapping(artifact_value, artifact_field)
            _reject_extra(artifact, {"kind", "sha256", "media_type"}, artifact_field)
            _require_text(artifact.get("kind"), f"{artifact_field}.kind")
            checksum = _require_text(artifact.get("sha256"), f"{artifact_field}.sha256")
            if not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
                raise CapabilityProfileError(f"{artifact_field}.sha256 must be a 64-character SHA-256 hex digest")
            if "media_type" in artifact and not isinstance(artifact["media_type"], str):
                raise CapabilityProfileError(f"{artifact_field}.media_type must be a string")

    recommendations = root.get("recommendations", [])
    if not isinstance(recommendations, list):
        raise CapabilityProfileError("profile.recommendations must be an array")
    for index, item_value in enumerate(recommendations):
        item = _require_mapping(item_value, f"profile.recommendations[{index}]")
        _reject_extra(item, {"workload_id", "decision", "evidence_ids", "reason"}, f"profile.recommendations[{index}]")
        workload_id = _require_text(item.get("workload_id"), f"profile.recommendations[{index}].workload_id")
        if workload_id not in workload_ids:
            raise CapabilityProfileError(f"recommendation references unknown workload_id: {workload_id}")
        if item.get("decision") not in {"ROUTE", "CONSTRAIN", "AVOID", "UNKNOWN"}:
            raise CapabilityProfileError(f"profile.recommendations[{index}].decision is invalid")
        if "reason" in item and not isinstance(item["reason"], str):
            raise CapabilityProfileError(f"profile.recommendations[{index}].reason must be a string")
        referenced_ids = item.get("evidence_ids")
        if not isinstance(referenced_ids, list) or not referenced_ids or not all(isinstance(value, str) and value for value in referenced_ids):
            raise CapabilityProfileError(f"profile.recommendations[{index}].evidence_ids must be a non-empty string array")
        recommendation_refs.extend(referenced_ids)
    unknown_refs = sorted(set(recommendation_refs) - evidence_ids)
    if unknown_refs:
        raise CapabilityProfileError(f"recommendations reference missing evidence: {', '.join(unknown_refs)}")
    return root


def observation_state(observation: Mapping[str, Any], as_of: datetime) -> str:
    """Resolve evidence freshness without carrying old values forward."""
    if observation.get("status") != "OBSERVED":
        return "UNKNOWN"
    observed_at = _parse_timestamp(observation.get("observed_at"), "observation.observed_at")
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    now = as_of.astimezone(timezone.utc)
    if observed_at > now:
        return "UNKNOWN"
    expires_at = observed_at + timedelta(seconds=float(observation["freshness_ttl_seconds"]))
    return "FRESH" if now <= expires_at else "UNKNOWN"


def _resolved_observation(observation: Mapping[str, Any], as_of: datetime) -> Dict[str, Any]:
    fresh = observation_state(observation, as_of) == "FRESH"
    resolved = {
        "observation_id": observation["observation_id"],
        "metric": observation["metric"],
        "value": observation["value"] if fresh else None,
        "status": "OBSERVED" if fresh else "UNKNOWN",
        "observed_at": observation["observed_at"],
        "source": dict(observation["source"]),
        "freshness_ttl_seconds": observation["freshness_ttl_seconds"],
    }
    if "unit" in observation:
        resolved["unit"] = observation["unit"]
    if not fresh:
        resolved["unknown_reason"] = observation.get("unknown_reason", "evidence is stale or dated after evaluation time")
    return resolved


def capability_summary(profile: Mapping[str, Any], as_of: Optional[datetime] = None) -> Dict[str, Any]:
    """Return a deterministic scheduler view; stale or unknown outcomes resolve to UNKNOWN."""
    validated = validate_profile(profile)
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    now = now.astimezone(timezone.utc)
    summary = []
    recommendations = []
    for capability in validated["capabilities"]:
        outcome = next(item for item in capability["observations"] if item["metric"] == "outcome")
        fresh = observation_state(outcome, now) == "FRESH"
        resolved = capability["result"] if fresh else "UNKNOWN"
        if outcome["status"] == "UNKNOWN":
            resolved = "UNKNOWN"
        summary.append({
            "workload_id": capability["workload_id"],
            "kind": capability["kind"],
            "declared_result": capability["result"],
            "effective_result": resolved,
            "freshness": "FRESH" if fresh else "UNKNOWN",
            "observations": [_resolved_observation(item, now) for item in capability["observations"]],
        })
    all_observations = {
        observation["observation_id"]: observation
        for collection in [validated["worker"]["observations"]]
        + [device["observations"] for device in validated["devices"]]
        + [capability["observations"] for capability in validated["capabilities"]]
        for observation in collection
    }
    for recommendation in validated.get("recommendations", []):
        fresh = all(observation_state(all_observations[item], now) == "FRESH" for item in recommendation["evidence_ids"])
        recommendations.append({
            "workload_id": recommendation["workload_id"],
            "declared_decision": recommendation["decision"],
            "effective_decision": recommendation["decision"] if fresh else "UNKNOWN",
            "evidence_ids": recommendation["evidence_ids"],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": validated["profile_id"],
        "worker_id": validated["worker"]["worker_id"],
        "as_of": now.isoformat(),
        "worker_observations": [_resolved_observation(item, now) for item in validated["worker"]["observations"]],
        "devices": [{
            "device_id": device["device_id"],
            "kind": device["kind"],
            "observations": [_resolved_observation(item, now) for item in device["observations"]],
        } for device in validated["devices"]],
        "capabilities": summary,
        "recommendations": recommendations,
    }


def load_profile(path: Path) -> Mapping[str, Any]:
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityProfileError(f"cannot read profile JSON: {exc}") from exc
    return validate_profile(profile)
