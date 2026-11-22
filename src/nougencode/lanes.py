"""Model lanes for NouGenCode: NouGenOpen first, local runtimes as the fallback.

Free lanes (OpenRouter, Hugging Face, NVIDIA, Arli AI, Ollama Cloud) live in
NouGenOpen, with their keys, headers and model lists. NouGenCode does not
carry that provider code. When Open is installed it is reached through the
NouGen mesh: its OpenAI-compatible endpoint when ``nougen-open serve`` is up,
else its ``open.nougen_ask`` tool run in Open's own interpreter. Without
Open, chat goes to a local Ollama daemon, as before.

No model or host here names an operator. Models come from the environment or
``mesh.json`` ``models``; with none set, Open picks (``nougenopen/auto``) and
local Ollama uses the first model it has pulled.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import nougen_mesh

OPEN_AUTO_MODEL = "nougenopen/auto"
LMSTUDIO_DEFAULT_PORT = 1234


class LaneError(RuntimeError):
    pass


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _models_cfg() -> Dict[str, Any]:
    v = nougen_mesh.load().get("models")
    return v if isinstance(v, dict) else {}


def local_model() -> Optional[str]:
    """Model for the local runtime: NOUGEN_CODE_MODEL, NOUGEN_MODEL, mesh models.code, else None (auto)."""
    v = _env("NOUGEN_CODE_MODEL") or _env("NOUGEN_MODEL") or str(_models_cfg().get("code") or "")
    return v.strip() or None


def open_model() -> str:
    """Model asked of NouGenOpen: NOUGEN_CODE_OPEN_MODEL, mesh models.code_open, else Open's auto pick."""
    v = _env("NOUGEN_CODE_OPEN_MODEL") or str(_models_cfg().get("code_open") or "")
    return v.strip() or OPEN_AUTO_MODEL


def normalize_host(raw: str, default_port: int) -> str:
    """An Ollama-style host (``0.0.0.0``, ``host:port``, URL) as a dialable base URL."""
    raw = raw.strip().rstrip("/")
    if "://" not in raw:
        raw = "http://" + raw
    u = urllib.parse.urlsplit(raw)
    host = u.hostname or "127.0.0.1"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    port = u.port or default_port
    return f"{u.scheme}://{host}:{port}{u.path}"


def ollama_url() -> str:
    """OLLAMA_HOST, then the mesh's ollama endpoint (NOUGEN_OLLAMA_URL / _PORT / mesh.json), else loopback."""
    default_port = nougen_mesh.port("ollama") or 11434
    raw = _env("OLLAMA_HOST")
    if raw:
        return normalize_host(raw, default_port)
    return nougen_mesh.endpoint("ollama") or f"http://127.0.0.1:{default_port}"


def lmstudio_url() -> str:
    """NOUGEN_LMSTUDIO_URL, mesh endpoints.lmstudio, else loopback on NOUGEN_LMSTUDIO_PORT or 1234."""
    return nougen_mesh.endpoint("lmstudio") or f"http://127.0.0.1:{LMSTUDIO_DEFAULT_PORT}"


def _via_open_disabled() -> bool:
    return _env("NOUGEN_CODE_VIA_OPEN").lower() in ("0", "false", "no", "off")


def open_url() -> Optional[str]:
    """NouGenOpen's endpoint when Open is part of this box's mesh, else None.

    Open counts as present when NOUGEN_OPEN_URL or mesh.json endpoints.open is
    set, or its checkout is found (NOUGEN_OPEN_DIR, mesh.json repos.open, a
    sibling checkout). NOUGEN_CODE_VIA_OPEN=0 turns the route off.
    """
    if _via_open_disabled():
        return None
    configured = _env("NOUGEN_OPEN_URL") or str((nougen_mesh.load().get("endpoints") or {}).get("open") or "")
    if not configured and nougen_mesh.repo_dir("open", near=__file__) is None:
        return None
    return nougen_mesh.endpoint("open")


def open_tool_installed() -> bool:
    if _via_open_disabled():
        return False
    try:
        return "open.nougen_ask" in nougen_mesh.tools(near=__file__)
    except Exception:
        return False


def split_host_port(url: str, default_port: int) -> Tuple[str, int]:
    u = urllib.parse.urlsplit(url)
    return u.hostname or "127.0.0.1", u.port or default_port


def _post_json(url: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str, timeout: float) -> Dict[str, Any]:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def answers(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except Exception:
        return False


def ollama_models(host: Optional[str] = None, timeout: float = 2.0) -> List[str]:
    try:
        data = _get_json(f"{host or ollama_url()}/api/tags", timeout)
    except Exception:
        return []
    return [str(m.get("name")) for m in data.get("models") or [] if isinstance(m, dict) and m.get("name")]


def _with_system(messages: List[Dict[str, str]], system: Optional[str]) -> List[Dict[str, str]]:
    return ([{"role": "system", "content": system}] if system else []) + list(messages)


def chat_open_http(messages: List[Dict[str, str]], system: Optional[str] = None, *,
                   model: Optional[str] = None, timeout: float = 120.0) -> Dict[str, Any]:
    base = open_url()
    if not base:
        raise LaneError("NouGenOpen is not part of this mesh")
    want = model or open_model()
    data = _post_json(f"{base}/v1/chat/completions",
                      {"model": want, "messages": _with_system(messages, system)}, timeout)
    choices = data.get("choices") or []
    content = ((choices[0] or {}).get("message") or {}).get("content") if choices else None
    if content is None:
        raise LaneError(f"NouGenOpen returned no completion: {str(data)[:200]}")
    return {"content": content, "lane": "open", "model": data.get("model") or want}


def chat_open_tool(messages: List[Dict[str, str]], system: Optional[str] = None, *,
                   model: Optional[str] = None, timeout: float = 120.0) -> Dict[str, Any]:
    prompt = "\n\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
    args: Dict[str, Any] = {"prompt": prompt, "system": system}
    want = model or open_model()
    if want != OPEN_AUTO_MODEL:
        args["model"] = want
    raw = nougen_mesh.call("open.nougen_ask", args, near=__file__, timeout=timeout)
    res = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(res, dict) or not res.get("success"):
        raise LaneError(f"open.nougen_ask failed: {str(res)[:200]}")
    return {"content": res.get("content", ""), "lane": "open", "model": res.get("model") or want}


def chat_ollama(messages: List[Dict[str, str]], system: Optional[str] = None, *,
                model: Optional[str] = None, host: Optional[str] = None, timeout: float = 60.0) -> Dict[str, Any]:
    base = host or ollama_url()
    want = model or local_model()
    if not want:
        have = ollama_models(base)
        if not have:
            raise LaneError(f"no local model: set NOUGEN_CODE_MODEL or pull one into Ollama at {base}")
        want = have[0]
    data = _post_json(f"{base}/api/chat",
                      {"model": want, "messages": _with_system(messages, system), "stream": False}, timeout)
    return {"content": (data.get("message") or {}).get("content", ""), "lane": "ollama", "model": want}


def chat(messages: List[Dict[str, str]], system: Optional[str] = None, *, local_model_name: Optional[str] = None,
         ollama_host: Optional[str] = None, timeout: float = 60.0) -> Dict[str, Any]:
    """NouGenOpen (endpoint, then tool) when present, then local Ollama. Raises LaneError if all fail."""
    errors: List[str] = []
    if open_url():
        try:
            return chat_open_http(messages, system, timeout=max(timeout, 120.0))
        except (urllib.error.URLError, OSError, ValueError, LaneError) as exc:
            errors.append(f"open endpoint: {exc}")
    if open_tool_installed():
        try:
            return chat_open_tool(messages, system, timeout=max(timeout, 120.0))
        except (nougen_mesh.MeshError, ValueError, LaneError) as exc:
            errors.append(f"open tool: {exc}")
    try:
        return chat_ollama(messages, system, model=local_model_name, host=ollama_host, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, LaneError) as exc:
        errors.append(f"ollama: {exc}")
    raise LaneError("; ".join(errors))
