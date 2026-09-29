"""NouGenCode Change Fabric package."""

from nougencode.fabric.change_contract import ChangeContract, FunctionalRequirement, ReviewConstraint
from nougencode.fabric.context_broker import ContextBroker, ContextItem, CoherenceReport
from nougencode.fabric.engine import ChangeFabricEngine, ChangeFabricExecutionResult
from nougencode.fabric.hook_abi import HookABIAdapter, HookPhase, HookContext, HookExecutionResult
from nougencode.fabric.postflight_outbox import PostflightOutbox, OutboxRecord
from nougencode.fabric.provider_ucb import ContextualProviderUCB, ProviderArm, RouteDecision
from nougencode.fabric.shadow_policy import ShadowPolicyReplayer, PolicyRule, ExecutionTrace, ReplayReport
from nougencode.fabric.telemetry import (
    OTelTelemetryTracer,
    TelemetrySpan,
    OTEL_GENERAL_SEMCONV_VERSION,
    OTEL_GENAI_SEMCONV_VERSION,
)
from nougencode.fabric.selector import InformationGainTestSelector, TestMetadata, SelectedTest
from nougencode.fabric.syntax_guard import SyntaxHealer, SyntaxHealResult, syntax_auto_fix_tool_hook

__all__ = [
    "ChangeContract",
    "FunctionalRequirement",
    "ReviewConstraint",
    "ContextBroker",
    "ContextItem",
    "CoherenceReport",
    "ChangeFabricEngine",
    "ChangeFabricExecutionResult",
    "HookABIAdapter",
    "HookPhase",
    "HookContext",
    "HookExecutionResult",
    "PostflightOutbox",
    "OutboxRecord",
    "ContextualProviderUCB",
    "ProviderArm",
    "RouteDecision",
    "ShadowPolicyReplayer",
    "PolicyRule",
    "ExecutionTrace",
    "ReplayReport",
    "OTelTelemetryTracer",
    "TelemetrySpan",
    "OTEL_GENERAL_SEMCONV_VERSION",
    "OTEL_GENAI_SEMCONV_VERSION",
    "InformationGainTestSelector",
    "TestMetadata",
    "SelectedTest",
    "SyntaxHealer",
    "SyntaxHealResult",
    "syntax_auto_fix_tool_hook",
]
