"""Cleanup pass: repair/compression scoring core and the report-only pass that runs before feature work."""
from .cleanup_pass import run_cleanup_pass
from .scoring import (
    AcceptanceEvidence,
    CleanupAction,
    Metrics,
    dead_probability,
    delete_value,
    intelligence_density,
    load_weights,
    merge_value,
    net_objective,
    parameterization_value,
    redundancy,
    refactor_acceptance,
    repair_priority,
    select_action,
    simplification_gain,
    trust_boundary_risk,
)

__all__ = [
    "AcceptanceEvidence", "CleanupAction", "Metrics", "dead_probability", "delete_value",
    "intelligence_density", "load_weights", "merge_value", "net_objective", "parameterization_value",
    "redundancy", "refactor_acceptance", "repair_priority", "run_cleanup_pass", "select_action",
    "simplification_gain", "trust_boundary_risk",
]
