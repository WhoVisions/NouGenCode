"""Local model runner for NouGenCode using Ollama or Cloud API."""

import json
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error


class ModelRunner:
    """Invokes local Ollama models (solai, Yukiai, gemma4:e2b) or falls back smoothly."""

    def __init__(self, model_name: str = "solai:latest", host: str = "http://localhost:11434") -> None:
        self.model_name = model_name
        self.host = host

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def chat(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
        }
        if system_prompt:
            payload["messages"] = [{"role": "system", "content": system_prompt}] + messages

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("message", {}).get("content", "")
        except urllib.error.URLError as e:
            return f"(Ollama connection error: {e}. Is Ollama running on {self.host}?)"
        except Exception as e:
            return f"(Error: {e})"
