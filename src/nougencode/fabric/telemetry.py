"""OpenTelemetry telemetry adapters with separate general (1.44.0) and GenAI (1.42.0-dev) SemConv pinning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, List, Mapping, Optional, Sequence, Tuple
import uuid

# Pinned semantic convention versions per Shard 29893@db8 and leg 20260929T171009Z
OTEL_GENERAL_SEMCONV_VERSION = "1.44.0"
OTEL_GENAI_SEMCONV_VERSION = "1.42.0-dev"


@dataclass(frozen=True)
class TelemetrySpan:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    kind: str  # INTERNAL, CLIENT, SERVER, PRODUCER, CONSUMER
    start_time_iso: str
    end_time_iso: str
    duration_ms: float
    attributes: Mapping[str, Any]
    events: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    status_code: str = "OK"  # UNSET, OK, ERROR
    status_message: Optional[str] = None
    semconv_version: str = OTEL_GENERAL_SEMCONV_VERSION


class OTelTelemetryTracer:
    """Tracer producing standards-compliant spans across mission, tool, model, and test lifecycles."""

    def __init__(self, service_name: str = "nougencode-change-fabric") -> None:
        self.service_name = service_name
        self._spans: List[TelemetrySpan] = []

    def start_mission_span(
        self, mission_id: str, task_name: str, trace_id: Optional[str] = None
    ) -> Tuple[str, str, float]:
        """Start mission root span. Returns (trace_id, span_id, start_perf)."""
        return (trace_id or uuid.uuid4().hex, uuid.uuid4().hex[:16], time.perf_counter())

    def _append_span(
        self,
        trace_id: str,
        name: str,
        duration_ms: float,
        attributes: Mapping[str, Any],
        *,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        kind: str = "INTERNAL",
        success: bool = True,
        status_message: Optional[str] = None,
        semconv_version: str = OTEL_GENERAL_SEMCONV_VERSION,
    ) -> TelemetrySpan:
        now_iso = datetime.now(timezone.utc).isoformat()
        span = TelemetrySpan(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:16] if span_id is None else span_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
            start_time_iso=now_iso,
            end_time_iso=now_iso,
            duration_ms=round(duration_ms, 3),
            attributes=attributes,
            status_code="OK" if success else "ERROR",
            status_message=status_message,
            semconv_version=semconv_version,
        )
        self._spans.append(span)
        return span

    def record_mission_span(
        self,
        trace_id: str,
        span_id: str,
        mission_id: str,
        task_name: str,
        start_perf: float,
        success: bool = True,
        attributes: Optional[Mapping[str, Any]] = None,
        error_msg: Optional[str] = None,
    ) -> TelemetrySpan:
        attrs = {
            "service.name": self.service_name,
            "mission.id": mission_id,
            "mission.task_name": task_name,
            **(attributes or {}),
        }
        return self._append_span(
            trace_id, f"mission.{task_name}", (time.perf_counter() - start_perf) * 1000.0, attrs,
            span_id=span_id, success=success, status_message=error_msg,
        )

    def record_tool_span(
        self,
        trace_id: str,
        parent_span_id: str,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> TelemetrySpan:
        attrs = {
            "service.name": self.service_name,
            "tool.name": tool_name,
            "tool.execution.success": success,
            **(attributes or {}),
        }
        return self._append_span(
            trace_id, f"tool.{tool_name}", duration_ms, attrs,
            parent_span_id=parent_span_id, success=success,
        )

    def record_genai_span(
        self,
        trace_id: str,
        parent_span_id: str,
        system_name: str,  # e.g. "ollama", "openrouter", "google"
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        finish_reason: str = "stop",
        temperature: float = 0.0,
    ) -> TelemetrySpan:
        """Record GenAI model invocation span using GenAI SemConv 1.42.0-dev."""
        attrs = {
            "gen_ai.system": system_name,
            "gen_ai.request.model": model_name,
            "gen_ai.request.temperature": temperature,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.response.finish_reasons": [finish_reason],
        }
        return self._append_span(
            trace_id, f"gen_ai.chat {model_name}", duration_ms, attrs,
            parent_span_id=parent_span_id, kind="CLIENT", semconv_version=OTEL_GENAI_SEMCONV_VERSION,
        )

    def record_test_span(
        self,
        trace_id: str,
        parent_span_id: str,
        test_id: str,
        duration_ms: float,
        passed: bool,
        error_output: Optional[str] = None,
    ) -> TelemetrySpan:
        attrs = {"test.suite": "pytest", "test.id": test_id, "test.passed": passed}
        return self._append_span(
            trace_id, f"test.{test_id}", duration_ms, attrs,
            parent_span_id=parent_span_id, success=passed, status_message=error_output,
        )

    def get_spans(self) -> Sequence[TelemetrySpan]:
        return tuple(self._spans)

    def clear(self) -> None:
        self._spans.clear()
