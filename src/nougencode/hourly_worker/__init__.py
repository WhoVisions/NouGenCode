"""NouGenCode Hourly Worker Kernel package.

Durable, event-driven control plane kernel with robust TTL, material DeltaEngine,
Cloudflare adapter stack, stateless MCP gateway, and independent verification receipts.
"""

from .cadence import CadenceScheduler, CadenceState, CadenceTick, RobustCadenceTTL
from .cloudflare import (
    DeadLetterQueue,
    DLQRecord,
    QueueIngressAdapter,
    QueueMessage,
    TenantDOCoordinator,
    WorkflowDurableExecutor,
    WorkflowStep,
)
from .delta import DeltaEngine, MaterialDelta
from .kernel import HourlyCycleResult, HourlyWorkerKernel
from .mcp_gateway import (
    A2APeerMessage,
    GenAIAdapterSpec,
    MCPGatewayAdapter,
    MCPRequest,
    OTelContext,
)
from .receipt import VerificationEngine, VerificationReceipt

__all__ = [
    "A2APeerMessage",
    "CadenceScheduler",
    "CadenceState",
    "CadenceTick",
    "DeadLetterQueue",
    "DeltaEngine",
    "DLQRecord",
    "GenAIAdapterSpec",
    "HourlyCycleResult",
    "HourlyWorkerKernel",
    "MaterialDelta",
    "MCPGatewayAdapter",
    "MCPRequest",
    "OTelContext",
    "QueueIngressAdapter",
    "QueueMessage",
    "RobustCadenceTTL",
    "TenantDOCoordinator",
    "VerificationEngine",
    "VerificationReceipt",
    "WorkflowDurableExecutor",
    "WorkflowStep",
]
