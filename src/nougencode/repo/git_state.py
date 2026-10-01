"""Tri-state git working-tree inspection: clean | dirty | unknown.

A boolean "is it dirty?" is fail-open: ``[ -n "$(git status --porcelain)" ]`` reads a
*failing* ``git status`` (index.lock held by another lane, I/O error) as the empty string,
which is also what a clean tree prints, so the gate answers "clean" exactly when it cannot
answer at all. Here the exit status is checked before any output is read, and a failure is
``unknown`` with a reason. ``unknown`` blocks ship/merge decisions the same way ``dirty`` does.

Staged, unstaged, untracked and conflicted paths are reported separately (the three trees:
HEAD vs index vs working tree, plus untracked). Dirty means any of them; Nix-style "tracked
changes only" is available as ``tracked_dirty``. Output uses ``--porcelain=v2 -z`` so paths
with spaces or unusual characters parse exactly; human output is never parsed.

Nothing here mutates the repository: no stash, reset, checkout or index refresh by name.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

CLEAN = "clean"
DIRTY = "dirty"
UNKNOWN = "unknown"

# 0 clean, 1 dirty, 3 unknown (2 is argparse's usage error).
EXIT_CODES = {CLEAN: 0, DIRTY: 1, UNKNOWN: 3}

MAX_PATHS = 50
GIT_TIMEOUT_S = 30

Runner = Callable[[Sequence[str], Path], "subprocess.CompletedProcess[bytes]"]


def _run_git(args: Sequence[str], cwd: Path) -> "subprocess.CompletedProcess[bytes]":
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=GIT_TIMEOUT_S, check=False)


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


@dataclass
class GitState:
    path: str
    state: str
    reason: str = ""
    branch: Optional[str] = None
    head_oid: Optional[str] = None
    upstream: Optional[str] = None
    ahead: Optional[int] = None
    behind: Optional[int] = None
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    conflicts: int = 0
    paths: dict = field(default_factory=lambda: {"staged": [], "unstaged": [], "untracked": [], "conflicts": []})
    truncated: bool = False
    stashes: Optional[int] = None
    worktrees: Optional[int] = None

    @property
    def tracked_dirty(self) -> bool:
        """Nix's definition: tracked-modified or staged only; untracked files do not count."""
        return bool(self.staged or self.unstaged or self.conflicts)

    @property
    def hazards(self) -> list:
        """Conditions that make a shared checkout risky, independent of dirty/clean."""
        found = []
        if self.state == UNKNOWN:
            return found
        if self.conflicts:
            found.append("unmerged paths present")
        if self.stashes:
            found.append(f"{self.stashes} stash entr{'y' if self.stashes == 1 else 'ies'}: a stash in a shared repo can capture another lane's work")
        if self.branch == "(detached)":
            found.append("detached HEAD")
        elif self.branch and self.upstream is None:
            found.append("branch has no upstream: its commits may exist only locally")
        elif self.ahead:
            found.append(f"{self.ahead} commit(s) not pushed")
        return found

    def to_dict(self) -> dict:
        return {
            "path": self.path, "state": self.state, "reason": self.reason,
            "branch": self.branch, "head": self.head_oid, "upstream": self.upstream,
            "ahead": self.ahead, "behind": self.behind,
            "staged": self.staged, "unstaged": self.unstaged,
            "untracked": self.untracked, "conflicts": self.conflicts,
            "tracked_dirty": self.tracked_dirty, "paths": self.paths, "truncated": self.truncated,
            "stashes": self.stashes, "worktrees": self.worktrees, "hazards": self.hazards,
        }


def _note(state: GitState, bucket: str, path: str) -> None:
    if len(state.paths[bucket]) < MAX_PATHS:
        state.paths[bucket].append(path)
    else:
        state.truncated = True


def parse_status_v2(raw: bytes, state: GitState) -> None:
    """Fill ``state`` from ``git status --porcelain=v2 --branch -z`` output."""
    fields = raw.split(b"\0")
    i = 0
    while i < len(fields):
        line = _text(fields[i])
        i += 1
        if not line:
            continue
        kind = line[0]
        if kind == "#":
            if line.startswith("# branch.oid "):
                oid = line[len("# branch.oid "):]
                state.head_oid = None if oid == "(initial)" else oid
            elif line.startswith("# branch.head "):
                head = line[len("# branch.head "):]
                state.branch = "(detached)" if head == "(detached)" else head
            elif line.startswith("# branch.upstream "):
                state.upstream = line[len("# branch.upstream "):]
            elif line.startswith("# branch.ab "):
                plus, minus = line[len("# branch.ab "):].split(" ")
                state.ahead, state.behind = int(plus), abs(int(minus))
        elif kind == "1":  # ordinary changed entry: 1 XY sub mH mI mW hH hI path
            xy, path = line.split(" ", 8)[1], line.split(" ", 8)[8]
            _classify(state, xy, path)
        elif kind == "2":  # renamed/copied: 2 XY sub mH mI mW hH hI Xscore path, then origPath
            xy, path = line.split(" ", 9)[1], line.split(" ", 9)[9]
            _classify(state, xy, path)
            i += 1  # the original path is its own NUL-separated field
        elif kind == "u":  # unmerged: u XY sub m1 m2 m3 mW h1 h2 h3 path
            state.conflicts += 1
            _note(state, "conflicts", line.split(" ", 10)[10])
        elif kind == "?":
            state.untracked += 1
            _note(state, "untracked", line[2:])
        # "!" (ignored) is deliberately not counted.


def _classify(state: GitState, xy: str, path: str) -> None:
    if xy[0] != ".":
        state.staged += 1
        _note(state, "staged", path)
    if xy[1] != ".":
        state.unstaged += 1
        _note(state, "unstaged", path)


def _count(runner: Runner, args: Sequence[str], root: Path, prefix: str = "") -> Optional[int]:
    """Advisory counts only: a failure here never changes clean/dirty, it just reports None."""
    try:
        proc = runner(args, root)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return sum(1 for ln in _text(proc.stdout).splitlines() if ln.startswith(prefix) and ln.strip())


def inspect(path: str | Path = ".", runner: Runner = _run_git) -> GitState:
    """Classify ``path`` as clean, dirty or unknown. Never raises for git failures."""
    root = Path(path)
    state = GitState(path=str(root), state=UNKNOWN)
    try:
        proc = runner(["status", "--porcelain=v2", "--branch", "-z"], root)
    except subprocess.TimeoutExpired:
        state.reason = f"git status timed out after {GIT_TIMEOUT_S}s"
        return state
    except (OSError, subprocess.SubprocessError) as exc:
        state.reason = f"git could not run: {exc}"
        return state

    if proc.returncode != 0:
        err = _text(proc.stderr).strip().splitlines()
        first = err[0] if err else f"git status exited {proc.returncode}"
        state.reason = "not a git repository" if "not a git repository" in first.lower() else first
        return state

    try:
        parse_status_v2(proc.stdout, state)
    except (ValueError, IndexError) as exc:
        state.state, state.reason = UNKNOWN, f"unparseable git status output: {exc}"
        return state

    state.state = DIRTY if (state.staged or state.unstaged or state.untracked or state.conflicts) else CLEAN
    state.stashes = _count(runner, ["stash", "list"], root)
    state.worktrees = _count(runner, ["worktree", "list", "--porcelain"], root, prefix="worktree ")
    return state


def render(state: GitState) -> str:
    """Human summary; the JSON form is the machine contract."""
    head = f"{state.state.upper()}: {state.path}"
    if state.state == UNKNOWN:
        return f"{head}\n  reason: {state.reason}\n  (unknown blocks ship/merge exactly like dirty)"
    lines = [head]
    where = state.branch or "?"
    if state.upstream:
        where += f" -> {state.upstream} (ahead {state.ahead}, behind {state.behind})"
    lines.append(f"  branch: {where}")
    lines.append(f"  staged {state.staged} | unstaged {state.unstaged} | untracked {state.untracked} | conflicts {state.conflicts}")
    for bucket in ("conflicts", "staged", "unstaged", "untracked"):
        for p in state.paths[bucket]:
            lines.append(f"    [{bucket}] {p}")
    if state.truncated:
        lines.append(f"    ... first {MAX_PATHS} per bucket shown")
    if state.worktrees is not None:
        lines.append(f"  worktrees: {state.worktrees}")
    for h in state.hazards:
        lines.append(f"  ! {h}")
    return "\n".join(lines)
