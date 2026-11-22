"""Recurse Engine: Ingest, adapt, and remix tools and skills from edge-Ai into NouGenCode.

Doctrine:
- Deep grep, leverage, combine, copy, transform, refactor, remix.
- Zero hardcoded machine/IP leaks.
- Zero token-flood; enforce NouGen Context Mode.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from . import nougen_mesh, siblings
from .context_gate import ContextGate


def resolve_edge_path() -> Optional[Path]:
    """The edge-Ai tools checkout: EDGE_AI_DIR (or YUKI_AI_DIR), else mesh.json ``paths.edge_ai``.

    No home-directory guesses: a box without either has no edge source.
    """
    env_p = os.environ.get("EDGE_AI_DIR") or os.environ.get("YUKI_AI_DIR")
    if env_p and Path(env_p).expanduser().is_dir():
        return Path(env_p).expanduser().resolve()
    paths = nougen_mesh.load().get("paths")
    cfg = paths.get("edge_ai") if isinstance(paths, dict) else None
    if cfg and Path(str(cfg)).expanduser().is_dir():
        return Path(str(cfg)).expanduser().resolve()
    return None


def scrub_private_names(code: str, names: Optional[List[str]] = None) -> str:
    """Replace private LAN IPs and this mesh's node/machine names before code is shared.

    The names come from the NouGen mesh (mesh.json nodes, fleet_hosts.json,
    this box's identity), never from a list printed in code.
    """
    out = re.sub(r"192\.168\.\d+\.\d+", "127.0.0.1", code)
    names = siblings.known_node_names() if names is None else names
    if names:
        pattern = r"\b(" + "|".join(re.escape(n) for n in names) + r")\b"
        out = re.sub(pattern, "NodeWorker", out, flags=re.IGNORECASE)
    return out


class RecurseEngine:
    """Recurses and synthesizes tools and skills from edge-Ai into clean NouGenCode packages."""

    def __init__(self, dest_skills_dir: Optional[Path] = None) -> None:
        self.edge_dir = resolve_edge_path()
        self.dest_skills = dest_skills_dir or (Path.cwd() / "skills")
        self.dest_skills.mkdir(parents=True, exist_ok=True)
        self.context_gate = ContextGate()

    def discover_tools(self) -> List[Dict[str, Any]]:
        """Scans edge-Ai tools directory and analyzes tools for recursion."""
        if not self.edge_dir:
            return []
        tools_dir = self.edge_dir / "tools"
        if not tools_dir.is_dir():
            return []

        results = []
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
                doc = ""
                m = re.match(r'^(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', text, re.DOTALL)
                if m:
                    doc = m.group(1).strip()
                results.append({
                    "name": py_file.stem,
                    "file": py_file.name,
                    "path": str(py_file),
                    "doc": doc or "Autonomous utility script",
                    "lines": len(text.splitlines()),
                })
            except Exception:
                continue
        return results

    def recurse_as_skill(self, tool_name: str, target_skill_name: Optional[str] = None) -> Optional[Path]:
        """Takes a tool or subsystem from edge-Ai, strips private IP names,
        compiles it into a clean, reusable NouGenCode skill package.
        """
        if not self.edge_dir:
            return None

        tools = {t["name"]: t for t in self.discover_tools()}
        if tool_name not in tools:
            return None

        tool_info = tools[tool_name]
        src_path = Path(tool_info["path"])
        code = src_path.read_text(encoding="utf-8", errors="replace")

        # Sanitize private IPs and this mesh's node / machine names
        sanitized_code = scrub_private_names(code)

        skill_slug = target_skill_name or f"edge-{tool_name.replace('_', '-')}"
        skill_dir = self.dest_skills / skill_slug
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write SKILL.md
        skill_md = (
            f"---\n"
            f"name: {skill_slug}\n"
            f"description: \"Recursed tool from tactical edge engine: {tool_info['doc'][:120]}\"\n"
            f"---\n\n"
            f"# ⚡ {skill_slug.replace('-', ' ').title()}\n\n"
            f"## Origin & Overview\n"
            f"Synthesized from edge tool `{tool_info['file']}`.\n\n"
            f"```python\n{tool_info['doc']}\n```\n\n"
            f"## Workflow & Reference Instructions\n"
            f"Use this skill for tactical edge tasks, mesh communication, and semantic search.\n"
        )
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        # Copy sanitized python script into scripts/ directory
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / f"{tool_name}.py").write_text(sanitized_code, encoding="utf-8")

        # Log into Context DB
        self.context_gate.log_event("skill_recursed", f"Recursed {tool_name} -> {skill_slug}", {"tool": tool_name})
        return skill_dir
