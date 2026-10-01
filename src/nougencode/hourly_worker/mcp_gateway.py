"""MCP gateway adapter (2026-07-28 stateless core) with Tasks, MRTR, and OTel 1.44 baseline.

Invariants:
1. Stateless core with Tasks/MRTR and header routing.
2. A2A (Agent-to-Agent) preserved ONLY for horizontal peer agents.
3. OpenTelemetry (OTel 1.44) baseline context propagation without relay telemetry spam.
4. Versioned GenAI adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OTelContext:
    trace_id: str
    span_id: str
    trace_flags: str = "01"
    trace_state: Optional[str] = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> OTelContext:
        """Parses W3C TraceContext (traceparent header) compliant with OTel 1.44."""
        traceparent = headers.get("traceparent") or headers.get("Traceparent") or ""
        parts = traceparent.strip().split("-")
        if len(parts) == 4 and parts[0] == "00" and len(parts[1]) == 32 and len(parts[2]) == 16:
            return cls(
                trace_id=parts[1],
                span_id=parts[2],
                trace_flags=parts[3],
                trace_state=headers.get("tracestate") or headers.get("Tracestate"),
            )
        # Generate clean context if missing
        seed = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return cls(trace_id=digest[:32], span_id=digest[32:48])

    def to_traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"


@dataclass(frozen=True)
class MCPRequest:
    method: str
    params: Mapping[str, Any]
    headers: Mapping[str, str] = field(default_factory=dict)
    otel: Optional[OTelContext] = None

    def __post_init__(self) -> None:
        if self.otel is None:
            object.__setattr__(self, "otel", OTelContext.from_headers(self.headers))

    @property
    def tenant_id(self) -> str:
        return self.headers.get("x-nougen-tenant") or self.headers.get("X-NouGen-Tenant") or "default_tenant"

    @property
    def route_target(self) -> str:
        return self.headers.get("x-nougen-route") or self.headers.get("X-NouGen-Route") or "default"

    @property
    def task_id(self) -> Optional[str]:
        return self.headers.get("x-nougen-task") or self.headers.get("X-NouGen-Task")


@dataclass(frozen=True)
class A2APeerMessage:
    """Agent-to-Agent message for horizontal peer agents only."""
    sender_agent_id: str
    recipient_agent_id: str
    peer_tier: str
    payload: Mapping[str, Any]
    is_horizontal: bool = True

    def __post_init__(self) -> None:
        if not self.is_horizontal:
            raise ValueError("A2A messages are restricted exclusively to horizontal peer agents")


@dataclass(frozen=True)
class GenAIAdapterSpec:
    adapter_id: str
    version: str  # e.g., "1.0.0", "2.0.0"
    model_family: str
    capabilities: Tuple[str, ...]

    def is_compatible(self, required_version: str) -> bool:
        req_major = required_version.split(".")[0]
        cur_major = self.version.split(".")[0]
        return req_major == cur_major


class MCPGatewayAdapter:
    """Stateless MCP Gateway core (2026-07-28 standard) with Task routing and MRTR."""

    def __init__(self) -> None:
        self._genai_adapters: Dict[str, GenAIAdapterSpec] = {}
        self._horizontal_a2a_log: List[A2APeerMessage] = []

    def register_genai_adapter(self, spec: GenAIAdapterSpec) -> None:
        self._genai_adapters[spec.adapter_id] = spec

    def route_mcp_request(self, request: MCPRequest) -> Dict[str, Any]:
        """Routes request statelessly based on method, task, and headers (MRTR)."""
        method = request.method
        route = request.route_target

        if method == "tools/call":
            tool_name = str(request.params.get("name", ""))
            return {
                "status": "routed",
                "route": route,
                "tenant": request.tenant_id,
                "tool": tool_name,
                "traceparent": request.otel.to_traceparent() if request.otel else None,
            }
        elif method == "tasks/execute":
            return {
                "status": "task_dispatched",
                "task_id": request.task_id or request.params.get("task_id"),
                "tenant": request.tenant_id,
                "traceparent": request.otel.to_traceparent() if request.otel else None,
            }
        else:
            return {
                "status": "handled",
                "method": method,
                "tenant": request.tenant_id,
            }

    def send_horizontal_a2a(self, message: A2APeerMessage) -> bool:
        """Sends peer A2A message, strictly rejecting hierarchical command spoofing."""
        if not message.is_horizontal:
            raise ValueError("Non-horizontal A2A communication rejected by gateway security policy")
        self._horizontal_a2a_log.append(message)
        return True
