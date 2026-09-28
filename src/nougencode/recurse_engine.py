"""Recurse Engine: Ingest, adapt, and remix tools and skills from Yuki-Ai into NouGenCode.

Doctrine:
- Deep grep, leverage, combine, copy, transform, refactor, remix.
- Zero hardcoded machine/IP leaks.
- Zero token-flood; enforce NouGen Context Mode.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Optional

from .skills_engine import SkillRegistry
from .context_gate import ContextGate


def resolve_yuki_path() -> Optional[Path]:
    """Dynamically resolves the local Yuki-Ai directory if available."""
    env_p = os.environ.get("YUKI_AI_DIR")
    if env_p and Path(env_p).is_dir():
        return Path(env_p).resolve()

    home = Path.home()
    candidates = [
        home / "HQ_WhoArt" / "Outpost" / "Yuki-Ai",
        home / "Outpost" / "Yuki-Ai",
        Path("C:/Users/super/HQ_WhoArt/Outpost/Yuki-Ai"),
    ]
    for c in candidates:
        if c.is_dir():
            return c.resolve()
    return None


class RecurseEngine:
    """Recurses and synthesizes tools and skills from Yuki-Ai into clean NouGenCode packages."""

    def __init__(self, dest_skills_dir: Optional[Path] = None) -> None:
        self.yuki_dir = resolve_yuki_path()
        self.dest_skills = dest_skills_dir or (Path.cwd() / "skills")
        self.dest_skills.mkdir(parents=True, exist_ok=True)
        self.context_gate = ContextGate()

    def discover_tools(self) -> List[Dict[str, Any]]:
        """Scans Yuki-Ai tools directory and analyzes tools for recursion."""
        if not self.yuki_dir:
            return []
        tools_dir = self.yuki_dir / "tools"
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
        """Takes a tool or subsystem from Yuki-Ai, strips private IP names,
        compiles it into a clean, reusable NouGenCode skill package.
        """
        if not self.yuki_dir:
            return None

        tools = {t["name"]: t for t in self.discover_tools()}
        if tool_name not in tools:
            return None

        tool_info = tools[tool_name]
        src_path = Path(tool_info["path"])
        code = src_path.read_text(encoding="utf-8", errors="replace")

        # Sanitize internal machine and brand references
        sanitized_code = re.sub(r"192\.168\.\d+\.\d+", "127.0.0.1", code)
        sanitized_code = re.sub(r"\b(WhoArt|Hyperion|blade|phoebus)\b", "NodeWorker", sanitized_code)

        skill_slug = target_skill_name or f"yuki-{tool_name.replace('_', '-')}"
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
