"""Fleet sweep: NouGen Context Mode gate + dirty-repo hygiene + skills recursion.

    nougencode sweep [ROOT ...] [--apply] [--push] [--json] [--no-persist]

Context Mode is enforced, not advisory: the sweep reads the relay board and the
shard substrate FIRST and stamps every report with context_state = full | degraded
| local_only and the sources it actually reached. A sweep that could not reach
both never reports `full`, and a "clean" verdict is always qualified by it.

"Clean dirty" is deliberately non-destructive. Nothing is checked out, reset,
deleted, stashed or force-pushed, ever:

* default        read-only inventory and plan.
* --apply        preserve each dirty repo's work as a local branch
                 ``hygiene/snapshot-<UTC>`` built with git plumbing (temporary
                 index -> write-tree -> commit-tree -> update-ref). The checked-out
                 branch, HEAD, the real index and the working tree are untouched,
                 so a lane working in that checkout never notices.
* --push         also push those snapshot branches, ONLY for repos verified
                 PRIVATE. Unknown visibility is treated as public (fail closed).

Files classed SECRET_RISK (by name or by ConcentricSecurityGate content scan) are
never put into a snapshot.

Skills recursion walks every SKILL.md under the roots and reports invalid
frontmatter, name/folder mismatch, referenced scripts that don't exist, and the
same skill name with diverging content across repos (drift). It reports; it
never merges skills.
"""
from __future__ import annotations

import dataclasses as dc
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .security.invariants import ConcentricSecurityGate

Runner = Callable[[Sequence[str], Optional[Path], float], Tuple[int, str]]


def _run(cmd: Sequence[str], cwd: Optional[Path] = None, timeout: float = 30.0, env: Optional[dict] = None) -> Tuple[int, str]:
    try:
        p = subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 124, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- context mode

@dc.dataclass
class ContextReport:
    state: str  # full | degraded | local_only
    machine: str
    sources: Dict[str, str]  # source -> "ok" | reason it is degraded/unreachable
    relay_waiting: Optional[int] = None
    shard_hits: Optional[int] = None


def _nougen_cli() -> Optional[str]:
    env = os.environ.get("NOUGEN_CLI")
    if env and Path(env).exists():
        return env
    for base in (Path.home() / "The Observatory" / "NouGen" / "nougenshards", Path(__file__).resolve().parents[3] / "nougenshards"):
        cand = base / ".venv" / "bin" / "nougen"
        if cand.exists():
            return str(cand)
    return shutil.which("nougen")


def hydrate_context(topic: str = "repo hygiene dirty working tree", run: Runner = _run, cli: Optional[str] = None) -> ContextReport:
    """Steps 1-3 of NouGen Context Mode: lane, task-scoped shard recall, relay state."""
    machine = os.environ.get("NOUGEN_MACHINE") or os.uname().nodename
    cli = cli if cli is not None else _nougen_cli()
    sources: Dict[str, str] = {}
    if not cli:
        return ContextReport("local_only", machine, {"relay": "nougen CLI not found", "shards": "nougen CLI not found"})
    cwd = Path(cli).resolve().parents[2] if Path(cli).exists() else None

    rc, out = run([cli, "relay", "open"], cwd, 60.0)
    waiting = None
    m = re.search(r"(\d+)\s+leg\(s\) waiting", out)
    # `nougen relay open` exits 3 when legs are WAITING: that is a successful read of
    # the board, not a failure. Judge by what was read, never by the exit code alone.
    if m:
        waiting, sources["relay"] = int(m.group(1)), "ok"
    elif rc == 0:
        waiting, sources["relay"] = 0, "ok"
    else:
        tail = [l for l in out.strip().splitlines() if not l.startswith(("INFO", "WARNING"))]
        sources["relay"] = f"exit {rc}: {(tail[-1] if tail else 'no board output')[:120]}"

    rc, out = run([cli, "search", topic], cwd, 120.0)
    hits = len(re.findall(r"^\[\d+\]", out, re.M))
    if rc != 0:
        sources["shards"] = f"exit {rc}"
    elif re.search(r"keyword-only|held its lock|timed? ?out|unreachable", out, re.I):
        # A partial recall cannot prove absence; Context Mode forbids calling it full.
        sources["shards"] = "partial: vector lanes degraded to keyword-only"
    else:
        sources["shards"] = "ok"

    ok = [k for k, v in sources.items() if v == "ok"]
    state = "full" if len(ok) == 2 else ("local_only" if not ok and not hits else "degraded")
    return ContextReport(state, machine, sources, waiting, hits)


# ---------------------------------------------------------------- repo hygiene

SECRET_NAME = re.compile(
    r"(^|/)(\.env(\..*)?|.*credential.*|.*secret.*|.*\.pem|.*\.key|.*\.p12|id_rsa.*|.*token.*\.json"
    r"|tenants\.json|\.?keyring.*|.*\.keychain.*|\.mcp\.json)$", re.I)
BACKUP_NAME = re.compile(r"(\.bak([-_.].*)?$|\.orig$|_BACKUP|~$|\.swp$)", re.I)
RUNTIME_NAME = re.compile(r"(^|/)(logs?|state|inbox\w*|agy_inbox\w*|__pycache__|\.pytest_cache|node_modules|dist)(/|$)|\.lock$|\.log$|\.pyc$", re.I)
MAX_SCAN_BYTES = 512_000


@dc.dataclass
class DirtyFile:
    path: str
    status: str  # porcelain XY
    klass: str  # SECRET_RISK | RUNTIME | BACKUP | SOURCE


@dc.dataclass
class RepoReport:
    path: str
    branch: str
    remote: str
    visibility: str  # PRIVATE | PUBLIC | UNKNOWN | LOCAL
    ahead: int
    behind: int
    files: List[DirtyFile]
    snapshot: Optional[str] = None
    pushed: bool = False
    note: str = ""

    @property
    def dirty(self) -> bool:
        return bool(self.files)

    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for f in self.files:
            c[f.klass] = c.get(f.klass, 0) + 1
        return c


def classify(repo: Path, rel: str) -> str:
    if SECRET_NAME.search(rel):
        return "SECRET_RISK"
    if RUNTIME_NAME.search(rel):
        return "RUNTIME"
    if BACKUP_NAME.search(rel):
        return "BACKUP"
    p = repo / rel
    if p.is_file():
        try:
            if p.stat().st_size <= MAX_SCAN_BYTES:
                text = p.read_text(errors="replace")
                if any(v.violation_type == "CREDENTIAL_EXPOSURE" for v in ConcentricSecurityGate.audit_code(text)):
                    return "SECRET_RISK"
        except OSError:
            pass
    return "SOURCE"


def find_repos(roots: Sequence[Path], max_depth: int = 3) -> List[Path]:
    found: List[Path] = []
    for root in roots:
        root = root.expanduser().resolve()
        for dirpath, dirnames, _ in os.walk(root):
            d = Path(dirpath)
            if len(d.relative_to(root).parts) > max_depth:
                dirnames[:] = []
                continue
            if (d / ".git").exists():
                found.append(d)
            dirnames[:] = [n for n in dirnames if n not in {".git", "node_modules", ".venv", "__pycache__", "dist"} and not n.startswith(".")]
    return sorted(set(found))


def _visibility(remote: str, run: Runner) -> str:
    if not remote:
        return "LOCAL"
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", remote)
    if not m:
        return "UNKNOWN"
    rc, out = run(["gh", "repo", "view", m.group(1), "--json", "visibility", "--jq", ".visibility"], None, 30.0)
    v = out.strip().upper()
    return v if rc == 0 and v in {"PRIVATE", "PUBLIC", "INTERNAL"} else "UNKNOWN"


def inspect_repo(repo: Path, run: Runner = _run) -> RepoReport:
    g = lambda *a: run(["git", "-C", str(repo), *a], None, 30.0)
    _, branch = g("rev-parse", "--abbrev-ref", "HEAD")
    rc, remote = g("remote", "get-url", "origin")
    remote = remote.strip() if rc == 0 else ""
    ahead = behind = 0
    rc, ab = g("rev-list", "--left-right", "--count", "@{upstream}...HEAD")
    if rc == 0 and len(ab.split()) == 2:
        behind, ahead = (int(x) for x in ab.split())
    _, por = g("status", "--porcelain=v1", "--untracked-files=all")
    files = []
    for line in por.splitlines():
        if len(line) < 4:
            continue
        status, rel = line[:2], line[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        files.append(DirtyFile(rel, status, classify(repo, rel)))
    return RepoReport(str(repo), branch.strip(), remote, _visibility(remote, run), ahead, behind, files)


def snapshot(repo: RepoReport, stamp: str) -> Optional[str]:
    """Commit SOURCE/BACKUP files to refs/heads/hygiene/snapshot-<stamp> without touching
    HEAD, the real index, or the working tree (temporary GIT_INDEX_FILE)."""
    keep = [f.path for f in repo.files if f.klass in {"SOURCE", "BACKUP"} and not f.status.startswith("D") and f.status[1] != "D"]
    if not keep:
        return None
    root = Path(repo.path)
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(td) / "index"))
        # Always real git with the private index: an injected runner must never be able
        # to drop GIT_INDEX_FILE and write into the repo's real index.
        git = lambda *a: _run(["git", "-C", str(root), *a], None, 60.0, env)
        rc, head = git("rev-parse", "HEAD")
        if rc != 0:
            return None
        head = head.strip()
        for step in (("read-tree", head), ("add", "--", *keep)):
            rc, out = git(*step)
            if rc != 0:
                repo.note = f"snapshot aborted at {step[0]}: {out.strip()[:120]}"
                return None
        rc, tree = git("write-tree")
        if rc != 0:
            return None
        msg = f"hygiene: snapshot of {len(keep)} dirty file(s) on {repo.branch} ({stamp})\n\nSECRET_RISK and RUNTIME files excluded. Created by `nougencode sweep --apply`."
        rc, commit = git("commit-tree", tree.strip(), "-p", head, "-m", msg)
        if rc != 0:
            return None
        ref = f"hygiene/snapshot-{stamp}"
        rc, _ = git("update-ref", f"refs/heads/{ref}", commit.strip())
        return ref if rc == 0 else None


# ---------------------------------------------------------------- skills recursion

@dc.dataclass
class SkillIssue:
    skill: str
    path: str
    problem: str


def _frontmatter(text: str) -> Dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            out[k.strip()] = v.strip().strip("'\"")
    return out


def recurse_skills(roots: Sequence[Path]) -> Tuple[int, List[SkillIssue]]:
    issues: List[SkillIssue] = []
    by_name: Dict[str, Dict[str, List[str]]] = {}
    count = 0
    for root in roots:
        for f in Path(root).expanduser().resolve().rglob("SKILL.md"):
            if any(p in f.parts for p in (".git", "node_modules", ".venv")):
                continue
            count += 1
            text = f.read_text(errors="replace")
            fm = _frontmatter(text)
            name = fm.get("name", "")
            if not name or not fm.get("description"):
                issues.append(SkillIssue(name or f.parent.name, str(f), "frontmatter missing name or description"))
            elif name != f.parent.name:
                issues.append(SkillIssue(name, str(f), f"name '{name}' != folder '{f.parent.name}'"))
            for ref in re.findall(r"\]\(((?:scripts|references|assets)/[^)\s]+)\)", text):
                if not (f.parent / ref).exists():
                    issues.append(SkillIssue(name or f.parent.name, str(f), f"references missing file {ref}"))
            digest = hashlib.sha256(text.encode()).hexdigest()[:12]
            by_name.setdefault(name or f.parent.name, {}).setdefault(digest, []).append(str(f))
    for name, variants in by_name.items():
        if len(variants) > 1:
            paths = "; ".join(p for ps in variants.values() for p in ps)
            issues.append(SkillIssue(name, paths, f"drift: {len(variants)} different versions of the same skill"))
    return count, issues


# ---------------------------------------------------------------- orchestration

@dc.dataclass
class SweepReport:
    context: ContextReport
    repos: List[RepoReport]
    skills_found: int
    skill_issues: List[SkillIssue]
    applied: bool
    generated_at: str

    def to_dict(self) -> dict:
        d = dc.asdict(self)
        for r, rr in zip(d["repos"], self.repos):
            r["counts"] = rr.counts()
            r["files"] = r["files"][:200]
        return d

    def summary(self) -> str:
        dirty = [r for r in self.repos if r.dirty]
        risky = [r for r in dirty if r.counts().get("SECRET_RISK")]
        snaps = [r for r in self.repos if r.snapshot]
        c = self.context
        lines = [
            f"context_state={c.state} machine={c.machine} sources: " + ", ".join(f"{k}={v}" for k, v in c.sources.items()),
            f"relay legs waiting: {c.relay_waiting if c.relay_waiting is not None else 'unknown'} | shard hits: {c.shard_hits}",
            f"repos: {len(self.repos)} scanned, {len(dirty)} dirty, {len(risky)} with SECRET_RISK files, {len(snaps)} snapshotted",
            f"skills: {self.skills_found} SKILL.md, {len(self.skill_issues)} issues",
        ]
        if c.state != "full":
            lines.append("NOTE: context is not full; this report cannot prove absence of prior work or claims.")
        return "\n".join(lines)


def sweep(roots: Sequence[Path], apply: bool = False, push: bool = False, run: Runner = _run,
          context: Optional[ContextReport] = None, now: Optional[dt.datetime] = None) -> SweepReport:
    ctx = context or hydrate_context(run=run)
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    repos = [inspect_repo(r, run) for r in find_repos(roots)]
    if apply:
        for r in repos:
            if not r.dirty:
                continue
            r.snapshot = snapshot(r, stamp)
            if push and r.snapshot:
                if r.visibility == "PRIVATE":
                    rc, out = run(["git", "-C", r.path, "push", "-q", "origin", f"refs/heads/{r.snapshot}"], None, 120.0)
                    r.pushed = rc == 0
                    if rc != 0:
                        r.note = f"push failed: {out.strip()[:120]}"
                else:
                    r.note = f"not pushed: visibility {r.visibility} (only PRIVATE repos are pushed)"
    n, issues = recurse_skills(roots)
    return SweepReport(ctx, repos, n, issues, apply, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))


def persist(report: SweepReport, run: Runner = _run, cli: Optional[str] = None) -> bool:
    """Context Mode step 7: write the delta back to shards. Counts only, never file contents."""
    cli = cli if cli is not None else _nougen_cli()
    if not cli:
        return False
    rc, _ = run([cli, "add", "--tags", "nougencode,sweep,hygiene", "NouGenCode sweep " + report.generated_at + "\n" + report.summary()], None, 120.0)
    return rc == 0
