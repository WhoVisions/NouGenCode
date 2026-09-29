"""Universal Hook ABI adapters with deterministic dispatch and error isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


class HookPhase(str, Enum):
    PREFLIGHT = "preflight"
    BEFORE_TOOL_EXECUTION = "before_tool_execution"
    AFTER_TOOL_EXECUTION = "after_tool_execution"
    BEFORE_MODEL_CALL = "before_model_call"
    AFTER_MODEL_CALL = "after_model_call"
    POSTFLIGHT = "postflight"
    LOOP_STOPPING = "loop_stopping"


@dataclass(frozen=True)
class HookContext:
    phase: HookPhase
    session_id: str
    task_id: str
    timestamp: str
    payload: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookExecutionResult:
    hook_name: str
    phase: HookPhase
    success: bool
    duration_ms: float
    mutated_payload: Optional[Mapping[str, Any]]
    error: Optional[str] = None
    abort_execution: bool = False


HookHandler = Callable[[HookContext], Tuple[bool, Optional[Mapping[str, Any]], Optional[str], bool]]


class HookABIAdapter:
    """Universal Hook ABI registry executing hooks safely across agent lifecycle phases."""

    def __init__(self) -> None:
        self._hooks: Dict[HookPhase, List[Tuple[str, HookHandler, int]]] = {
            phase: [] for phase in HookPhase
        }

    def register(
        self,
        phase: HookPhase,
        name: str,
        handler: HookHandler,
        priority: int = 100,
    ) -> None:
        """Register a hook handler. Lower priority values execute first."""
        hooks_list = self._hooks[phase]
        # Avoid duplicate registration
        self._hooks[phase] = [(n, h, p) for n, h, p in hooks_list if n != name]
        self._hooks[phase].append((name, handler, priority))
        self._hooks[phase].sort(key=lambda x: x[2])

    def unregister(self, phase: HookPhase, name: str) -> bool:
        initial_len = len(self._hooks[phase])
        self._hooks[phase] = [(n, h, p) for n, h, p in self._hooks[phase] if n != name]
        return len(self._hooks[phase]) < initial_len

    def dispatch(
        self,
        phase: HookPhase,
        session_id: str,
        task_id: str,
        payload: Mapping[str, Any],
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Tuple[Mapping[str, Any], Sequence[HookExecutionResult]]:
        """Dispatch lifecycle event to all registered handlers for the phase."""
        results: List[HookExecutionResult] = []
        current_payload = dict(payload)
        now_str = datetime.now(timezone.utc).isoformat()

        for name, handler, _ in self._hooks[phase]:
            ctx = HookContext(
                phase=phase,
                session_id=session_id,
                task_id=task_id,
                timestamp=now_str,
                payload=current_payload,
                metadata=metadata or {},
            )
            t0 = time.perf_counter()
            try:
                success, mut_payload, err, abort = handler(ctx)
                dur_ms = (time.perf_counter() - t0) * 1000.0
                if success and mut_payload is not None:
                    current_payload.update(mut_payload)

                res = HookExecutionResult(
                    hook_name=name,
                    phase=phase,
                    success=success,
                    duration_ms=round(dur_ms, 3),
                    mutated_payload=mut_payload,
                    error=err,
                    abort_execution=abort,
                )
                results.append(res)
                if abort:
                    break
            except Exception as exc:
                dur_ms = (time.perf_counter() - t0) * 1000.0
                res = HookExecutionResult(
                    hook_name=name,
                    phase=phase,
                    success=False,
                    duration_ms=round(dur_ms, 3),
                    mutated_payload=None,
                    error=str(exc),
                    abort_execution=False,
                )
                results.append(res)

        return (current_payload, tuple(results))
