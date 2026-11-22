"""Sibling NouGen repos, found through the NouGen mesh instead of path guesses.

NouGenCode runs alone. When NouGenShards or NouGenRelay is installed beside it
(or named in ``~/.nougen/mesh.json`` / ``NOUGEN_<REPO>_DIR``), these helpers
reach it; otherwise they return None and callers degrade to local-only.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Optional

from . import nougen_mesh


def repo_dir(name: str) -> Optional[Path]:
    return nougen_mesh.repo_dir(name, near=__file__)


def shards_source_dirs() -> List[Path]:
    """Source roots that may hold the ``nougen_shards`` package, best first."""
    out: List[Path] = []
    raw = os.environ.get("NOUGEN_SHARDS_SOURCE", "").strip()
    roots = [Path(raw).expanduser()] if raw else []
    found = repo_dir("shards")
    if found is not None:
        roots.append(found)
    for root in roots:
        for cand in (root / "src", root):
            if (cand / "nougen_shards").is_dir() and cand not in out:
                out.append(cand)
    return out


def import_shards(module: str = "nougen_shards.core") -> ModuleType:
    """Import a NouGenShards module: installed package first, then the checkout the mesh finds."""
    try:
        return importlib.import_module(module)
    except ImportError:
        pass
    for cand in shards_source_dirs():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        try:
            return importlib.import_module(module)
        except ImportError:
            continue
    raise ImportError(f"{module}: NouGenShards is not installed and no checkout was found "
                      "(set NOUGEN_SHARDS_DIR or repos.shards in mesh.json)")


def relay_dir() -> Optional[Path]:
    """NOUGEN_RELAY_DIR if set (kept for existing deployments), else the mesh's relay checkout."""
    raw = os.environ.get("NOUGEN_RELAY_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    found = repo_dir("relay")
    return found.resolve() if found is not None else None


def nougen_cli() -> Optional[str]:
    """The ``nougen`` CLI: NOUGEN_CLI, then the NouGenShards checkout's venv, then PATH."""
    env = os.environ.get("NOUGEN_CLI", "").strip()
    if env and Path(env).exists():
        return env
    shards = repo_dir("shards")
    if shards is not None:
        for rel in (".venv/bin/nougen", ".venv/Scripts/nougen.exe", "venv/bin/nougen"):
            cand = shards / rel
            if cand.exists():
                return str(cand)
    return shutil.which("nougen")


def known_node_names() -> List[str]:
    """Node and machine names this box knows (mesh nodes, its own identity), longest first.

    Used to scrub them out of code before it is shared. A fresh box knows only
    its own machine name.
    """
    names = set(nougen_mesh.nodes())
    for cfg in nougen_mesh.nodes().values():
        for pat in (cfg.get("host_patterns") or []) if isinstance(cfg, dict) else []:
            names.add(str(pat))
    ident = nougen_mesh.identity()
    for key in ("node", "machine"):
        v = str(ident.get(key) or "")
        if v and v not in ("standalone", "unknown-machine"):
            names.add(v)
    return sorted((n for n in names if len(n) >= 3), key=lambda n: (-len(n), n))
