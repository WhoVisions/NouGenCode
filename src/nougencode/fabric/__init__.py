"""NouGenCode Change Fabric package."""

import importlib

_MODULES = {
    "change_contract": ("ChangeContract", "FunctionalRequirement", "ReviewConstraint"),
    "context_broker": ("ContextBroker", "ContextItem", "CoherenceReport"),
    "engine": ("ChangeFabricEngine", "ChangeFabricExecutionResult"),
    "hook_abi": ("HookABIAdapter", "HookPhase", "HookContext", "HookExecutionResult"),
    "postflight_outbox": ("PostflightOutbox", "OutboxBackend", "OutboxRecord"),
    "durable_outbox": ("SQLitePostflightOutbox",),
    "pixellab": ("pixellab",),
    "provider_ucb": ("ContextualProviderUCB", "EngineDecision", "WorkloadSpec", "WorkloadStats", "ProviderArm", "RouteDecision"),
    "shadow_policy": ("ShadowPolicyReplayer", "PolicyRule", "ExecutionTrace", "ReplayReport"),
    "telemetry": ("OTelTelemetryTracer", "TelemetrySpan", "OTEL_GENERAL_SEMCONV_VERSION", "OTEL_GENAI_SEMCONV_VERSION"),
    "selector": ("InformationGainTestSelector", "TestMetadata", "SelectedTest"),
    "syntax_guard": ("SyntaxHealer", "SyntaxHealResult", "syntax_auto_fix_tool_hook"),
}
_EXPORTS = {name: mod for mod, names in _MODULES.items() for name in names}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f".{_EXPORTS[name]}", __name__)
    val = mod if name == "pixellab" else getattr(mod, name)
    globals()[name] = val
    return val
