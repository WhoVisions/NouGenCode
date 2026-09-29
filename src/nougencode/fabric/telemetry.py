"""OpenTelemetry telemetry adapters with separate general (1.44.0) and GenAI (1.42.0-dev) SemConv pinning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
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
        self,
        mission_id: str,
        task_name: str,
        trace_id: Optional[str] = None,
    ) -> Tuple[str, str, float]:
        """Start mission root span. Returns (trace_id, span_id, start_perf)."""
        t_id = trace_id or uuid.uuid4().hex
        s_id = uuid.uuid4().hex[:16]
        return (t_id, s_id, time.perf_counter())

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
        now_iso = datetime.now(timezone.utc).isoformat()
        dur_ms = (time.perf_counter() - start_perf) * 1000.0
        attrs = {
            "service.name": self.service_name,
            "mission.id": mission_id,
            "mission.task_name": task_name,
            **(attributes or {}),
        }
        span = TelemetrySpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            name=f"mission.{task_name}",
            kind="INTERNAL",
            start_time_iso=now_iso,
            end_time_iso=now_iso,
            duration_ms=round(dur_ms, 3),
            attributes=attrs,
            status_code="OK" if success else "ERROR",
            status_message=error_msg,
            semconv_version=OTEL_GENERAL_SEMCONV_VERSION,
        )
        self._spans.append(span)
        return span

    def record_tool_span(
        self,
        trace_id: str,
        parent_span_id: str,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> TelemetrySpan:
        s_id = uuid.uuid4().hex[:16]
        now_iso = datetime.now(timezone.utc).isoformat()
        attrs = {
            "service.name": self.service_name,
            "tool.name": tool_name,
            "tool.execution.success": success,
            **(attributes or {}),
        }
        span = TelemetrySpan(
            trace_id=trace_id,
            span_id=s_id,
            parent_span_id=parent_span_id,
            name=f"tool.{tool_name}",
            kind="INTERNAL",
            start_time_iso=now_iso,
            end_time_iso=now_iso,
            duration_ms=round(duration_ms, 3),
            attributes=attrs,
            status_code="OK" if success else "ERROR",
            semconv_version=OTEL_GENERAL_SEMCONV_VERSION,
        )
        self._spans.append(span)
        return span

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
        s_id = uuid.uuid4().hex[:16]
        now_iso = datetime.now(timezone.utc).isoformat()
        attrs = {
            "gen_ai.system": system_name,
            "gen_ai.request.model": model_name,
            "gen_ai.request.temperature": temperature,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.response.finish_reasons": [finish_reason],
        }
        span = TelemetrySpan(
            trace_id=trace_id,
            span_id=s_id,
            parent_span_id=parent_span_id,
            name=f"gen_ai.chat {model_name}",
            kind="CLIENT",
            start_time_iso=now_iso,
            end_time_iso=now_iso,
            duration_ms=round(duration_ms, 3),
            attributes=attrs,
            status_code="OK",
            semconv_version=OTEL_GENAI_SEMCONV_VERSION,
        )
        self._spans.append(span)
        return span

    def record_test_span(
        self,
        trace_id: str,
        parent_span_id: str,
        test_id: str,
        duration_ms: float,
        passed: bool,
        error_output: Optional[str] = None,
    ) -> TelemetrySpan:
        s_id = uuid.uuid4().hex[:16]
        now_iso = datetime.now(timezone.utc).isoformat()
        attrs = {
            "test.suite": "pytest",
            "test.id": test_id,
            "test.passed": passed,
        }
        span = TelemetrySpan(
            trace_id=trace_id,
            span_id=s_id,
            parent_span_id=parent_span_id,
            name=f"test.{test_id}",
            kind="INTERNAL",
            start_time_iso=now_iso,
            end_time_iso=now_iso,
            duration_ms=round(duration_ms, 3),
            attributes=attrs,
            status_code="OK" if passed else "ERROR",
            status_message=error_output,
            semconv_version=OTEL_GENERAL_SEMCONV_VERSION,
        )
        self._spans.append(span)
        return span

    def get_spans(self) -> Sequence[TelemetrySpan]:
        return tuple(self._spans)

    def clear(self) -> None:
        self._spans.clear()
