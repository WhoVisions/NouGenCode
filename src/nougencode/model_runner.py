"""Model runner for NouGenCode: NouGenOpen through the mesh, local Ollama as fallback."""

import os
from typing import Dict, List, Optional

from . import lanes


class ModelRunner:
    """Chats through NouGenOpen's free lanes when Open is installed, else a local Ollama model.

    ``model_name`` is the local model (NOUGEN_MODEL / NOUGEN_CODE_MODEL / mesh
    models.code); None means the first model local Ollama has pulled.
    """

    def __init__(self, model_name: Optional[str] = None, host: Optional[str] = None) -> None:
        self.model_name = os.environ.get("NOUGEN_MODEL") or model_name or lanes.local_model()
        self.host = lanes.normalize_host(os.environ["OLLAMA_HOST"], 11434) if os.environ.get("OLLAMA_HOST") \
            else (host or lanes.ollama_url())
        self.last_lane: Optional[str] = None
        self.last_model: Optional[str] = None

    def describe(self) -> str:
        """One line for banners: which lane chat will try first."""
        local = self.model_name or "first pulled model"
        if lanes.open_url() or lanes.open_tool_installed():
            return f"NouGenOpen ({lanes.open_model()}), fallback Ollama ({local})"
        return f"Ollama Local ({local})"

    def is_available(self) -> bool:
        base = lanes.open_url()
        if base and lanes.answers(f"{base}/v1/models"):
            return True
        return lanes.answers(f"{self.host}/api/tags")

    def chat(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        try:
            out = lanes.chat(messages, system_prompt, local_model_name=self.model_name, ollama_host=self.host)
        except lanes.LaneError as e:
            return f"(No model lane answered: {e}. Start `nougen-open serve`, or run Ollama on {self.host}.)"
        except Exception as e:
            return f"(Error: {e})"
        self.last_lane, self.last_model = out["lane"], out["model"]
        return out["content"]
