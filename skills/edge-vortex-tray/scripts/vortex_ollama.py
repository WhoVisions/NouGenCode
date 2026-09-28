"""Shared Ollama control for the Vortex tray and dashboard.

Both surfaces used to carry their own "Flush VRAM" implementation. The
dashboard's was hardcoded to two model names and reported
"VRAM Freed successfully." whether or not anything was actually evicted —
verified on 2026-08-02 with NodeWorker:latest sitting at 2,808 MB straight
through a "successful" flush.

There is now one implementation, it asks the daemon what is actually
resident, and it reports what actually happened.

Stdlib only, so importing this never drags a GUI toolkit along.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_HOST = os.getenv("VORTEX_OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def _timeout(default: float) -> float:
    try:
        return float(os.getenv("VORTEX_OLLAMA_TIMEOUT", str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class FlushResult:
    """What a flush actually did. Never optimistic."""

    unloaded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    still_resident: list[str] = field(default_factory=list)
    freed_bytes: int = 0
    error: str | None = None

    @property
    def freed_mb(self) -> int:
        return self.freed_bytes // (1024 * 1024)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.failed and not self.still_resident

    def summary(self) -> str:
        if self.error:
            return f"VRAM flush failed: {self.error}"
        if not self.unloaded and not self.failed:
            return "No models resident — VRAM is already clear."
        if self.ok:
            return f"VRAM flushed — unloaded {', '.join(self.unloaded)} (~{self.freed_mb} MB)."
        parts = []
        if self.unloaded:
            parts.append(f"unloaded {', '.join(self.unloaded)} (~{self.freed_mb} MB)")
        if self.failed:
            parts.append(f"failed: {', '.join(self.failed)}")
        if self.still_resident:
            parts.append(f"STILL RESIDENT: {', '.join(self.still_resident)}")
        return "Partial VRAM flush — " + "; ".join(parts) + "."


class OllamaClient:
    """Minimal stdlib client for the local Ollama runtime."""

    def __init__(self, host: str = DEFAULT_HOST, timeout: float | None = None) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout if timeout is not None else _timeout(10.0)

    def _call(self, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        url = f"{self.host}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
            body = resp.read().decode("utf-8").strip()
        return json.loads(body) if body else {}

    def resident_models(self) -> list[dict]:
        """Models currently holding VRAM, straight from the daemon."""
        return self._call("/api/ps").get("models") or []

    def unload(self, model: str) -> None:
        """Evict one model by requesting a zero keep-alive."""
        self._call("/api/generate", {"model": model, "keep_alive": 0})

    def preload(self, model: str, timeout: float = 300.0, keep_alive: object = -1) -> None:
        """Load a model into VRAM without generating.

        Ollama treats a messages-less /api/chat call as an explicit load and
        answers with done_reason='load'. Embedding models do not serve
        /api/chat, so fall back to /api/embed for those rather than
        reporting a load failure for a model that loads perfectly well.
        """
        try:
            self._call("/api/chat", {"model": model, "keep_alive": keep_alive}, timeout=timeout)
            return
        except urllib.error.HTTPError:
            pass
        self._call(
            "/api/embed",
            {"model": model, "input": "", "keep_alive": keep_alive},
            timeout=timeout,
        )

    def flush_vram(self) -> FlushResult:
        """Unload every resident model, then verify it actually happened."""
        result = FlushResult()

        try:
            resident = self.resident_models()
        except urllib.error.URLError as exc:
            result.error = f"Ollama unreachable at {self.host}: {exc.reason}"
            return result
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        if not resident:
            return result

        sizes = {}
        for model in resident:
            name = model.get("name") or model.get("model") or "?"
            sizes[name] = int(model.get("size_vram") or 0)
            try:
                self.unload(name)
                result.unloaded.append(name)
            except Exception:
                result.failed.append(name)

        # Trust the daemon, not our own optimism.
        try:
            leftover = {m.get("name") or m.get("model") for m in self.resident_models()}
        except Exception:
            leftover = set()

        result.still_resident = sorted(n for n in leftover if n)
        result.unloaded = [n for n in result.unloaded if n not in leftover]
        result.freed_bytes = sum(sizes.get(n, 0) for n in result.unloaded)
        return result
