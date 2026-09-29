"""Dynamic Skills Engine & Verb Registry baked from NouGenShards.

Discovers, parses, and activates SKILL.md packages across dynamic directories:
- User's ~/.gemini/config/skills/
- User's ~/.nougen/skills/
- Project local .agents/skills/ or skills/

Provides the 11-Verb cognitive instruction set across the 6 planes:
(Memory, Coordination, Observability, Intent, Execution, Learning).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

_FRONTMATTER = re.compile(r"^﻿?---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_SCALAR = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")

# Cognitive instruction verbs
VERBS: Dict[str, Dict[str, str]] = {
    "shard": {"plane": "memory", "role": "Durable memory and retrievable evidence"},
    "relay": {"plane": "coordination", "role": "Handoff and responsibility continuity"},
    "msg": {"plane": "coordination", "role": "Direct inter-agent plain-text communication"},
    "live": {"plane": "coordination", "role": "Present-tense operational machine truth"},
    "track": {"plane": "observability", "role": "Telemetry, measurement, and token tracking"},
    "destiny": {"plane": "intent", "role": "Prospective long-horizon target outcomes"},
    "wish": {"plane": "intent", "role": "Next actionable, testable deltas"},
    "build": {"plane": "execution", "role": "Candidate creation and code construction"},
    "harden": {"plane": "execution", "role": "Adversarial verification and bug-squashing"},
    "dream": {"plane": "learning", "role": "Exploration and replay consolidation"},
    "evolve": {"plane": "learning", "role": "Promotion of verified patterns into durable skills"},
}


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Parse YAML frontmatter without requiring PyYAML."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text

    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found = _SCALAR.match(line)
        if not found:
            continue
        k, v = found.group(1).lower(), found.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        meta[k] = v

    return meta, text[match.end():]


class Skill:
    def __init__(self, name: str, description: str, path: Path, body: str = "") -> None:
        self.name = name
        self.description = description
        self.path = path
        self.body = body

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
        }


class SkillRegistry:
    """Discovers and loads skills dynamically without hardcoded directories."""

    def __init__(self, extra_roots: Optional[List[Path]] = None) -> None:
        self.roots = self._resolve_roots(extra_roots or [])
        self.skills: Dict[str, Skill] = {}
        self.reload()

    def _resolve_roots(self, extra: List[Path]) -> List[Path]:
        roots: List[Path] = []
        # 1. Explicit env override
        env_dirs = os.environ.get("NOUGEN_SKILLS_DIR")
        if env_dirs:
            for p in env_dirs.split(os.pathsep):
                if p.strip() and Path(p).is_dir():
                    roots.append(Path(p).resolve())

        # 2. User home config skills
        home = Path.home()
        for cand in [
            home / ".antigravity" / "skills",
            home / ".gemini" / "config" / "skills",
            home / ".nougen" / "skills",
            Path.cwd() / "skills",
            Path.cwd() / ".agents" / "skills",
        ]:
            if cand.is_dir() and cand not in roots:
                roots.append(cand.resolve())

        for r in extra:
            if r.is_dir() and r not in roots:
                roots.append(r.resolve())

        return roots

    def reload(self) -> None:
        self.skills.clear()
        for root in self.roots:
            if not root.exists():
                continue
            for dirpath, _, filenames in os.walk(root):
                if "SKILL.md" in filenames:
                    skill_file = Path(dirpath) / "SKILL.md"
                    try:
                        content = skill_file.read_text(encoding="utf-8", errors="replace")
                        meta, body = parse_frontmatter(content)
                        name = meta.get("name") or skill_file.parent.name
                        desc = meta.get("description", "")
                        self.skills[name] = Skill(name=name, description=desc, path=skill_file, body=body)
                    except Exception:
                        continue

    def list_skills(self) -> List[Skill]:
        return sorted(self.skills.values(), key=lambda s: s.name)

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def find_skills_for_task(self, task_description: str) -> List[Skill]:
        """Simple keyword matching to suggest applicable skills."""
        tokens = set(re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", task_description.lower()))
        matched = []
        for s in self.skills.values():
            stokens = set(re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", (s.name + " " + s.description).lower()))
            if tokens & stokens:
                matched.append(s)
        return matched

    def create_skill(
        self,
        name: str,
        description: str,
        instructions: str,
        target_dir: Optional[Path] = None,
    ) -> Skill:
        """Creates a new canonical skill package with SKILL.md.
        Places it in target_dir or the primary resolved skill root dynamically.
        """
        slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower().strip()).strip("-") or "new-skill"
        dest_root = target_dir or (self.roots[0] if self.roots else (Path.home() / ".nougen" / "skills"))
        skill_folder = (dest_root / slug).resolve()
        skill_folder.mkdir(parents=True, exist_ok=True)
        skill_file = skill_folder / "SKILL.md"

        content = (
            f"---\n"
            f"name: {slug}\n"
            f"description: \"{description}\"\n"
            f"---\n\n"
            f"# 🛠️ {name}\n\n"
            f"## Overview\n{description}\n\n"
            f"## Instructions & Workflow\n{instructions}\n"
        )
        skill_file.write_text(content, encoding="utf-8")
        created_skill = Skill(name=slug, description=description, path=skill_file, body=instructions)
        self.skills[slug] = created_skill
        return created_skill
