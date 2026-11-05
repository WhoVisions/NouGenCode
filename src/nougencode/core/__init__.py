"""Core exports for nougencode."""

import importlib

_MODULES = {
    "mission": ("Capability", "CodeMission", "Intent", "MissionState", "MutationBudget", "RuntimeIdentity", "TaskNode"),
    "directives": ("DirectiveCompiler", "DirectiveConstraint", "DirectiveOrchestrator", "DirectivePlan", "DirectiveReceipt", "DirectiveType"),
    "coordinator": ("AuthorityArbitrationResult", "AuthorityArbitrator", "MonotonicFenceToken", "QueueItem", "ResolutionState", "TenantCoordinator", "WorkflowPhase"),
}
_EXPORTS = {name: mod for mod, names in _MODULES.items() for name in names}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    val = getattr(importlib.import_module(f".{_EXPORTS[name]}", __name__), name)
    globals()[name] = val
    return val
