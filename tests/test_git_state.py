"""Tri-state git working-tree inspection: real repos plus a failing-git shim."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nougencode import cli
from nougencode.repo.git_state import CLEAN, DIRTY, EXIT_CODES, UNKNOWN, _run_git, inspect, render

IDENT = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def git(repo: Path, *args: str, check: bool = True) -> None:
    subprocess.run(["git", *IDENT, *args], cwd=repo, check=check, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_clean(repo):
    s = inspect(repo)
    assert s.state == CLEAN and s.reason == ""
    assert (s.staged, s.unstaged, s.untracked, s.conflicts) == (0, 0, 0, 0)
    assert s.branch == "main" and s.head_oid
    assert EXIT_CODES[s.state] == 0


def test_three_trees_are_reported_separately(repo):
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")   # worktree differs from index
    (repo / "staged.txt").write_text("s\n", encoding="utf-8")
    git(repo, "add", "staged.txt")                                # index differs from HEAD
    (repo / "new file.txt").write_text("u\n", encoding="utf-8")   # untracked, name has a space
    s = inspect(repo)
    assert s.state == DIRTY and EXIT_CODES[s.state] == 1
    assert (s.staged, s.unstaged, s.untracked) == (1, 1, 1)
    assert s.paths["staged"] == ["staged.txt"]
    assert s.paths["unstaged"] == ["a.txt"]
    assert s.paths["untracked"] == ["new file.txt"]
    assert s.tracked_dirty


def test_untracked_only_is_dirty_but_not_tracked_dirty(repo):
    (repo / "scratch.txt").write_text("x\n", encoding="utf-8")
    s = inspect(repo)
    assert s.state == DIRTY
    assert not s.tracked_dirty  # Nix's definition ignores untracked files


def test_staged_and_unstaged_edit_of_one_file_counts_in_both(repo):
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    s = inspect(repo)
    assert (s.staged, s.unstaged) == (1, 1)


def test_rename_consumes_its_original_path_field(repo):
    git(repo, "mv", "a.txt", "renamed file.txt")
    (repo / "after.txt").write_text("u\n", encoding="utf-8")
    s = inspect(repo)
    assert s.staged == 1 and s.untracked == 1
    assert s.paths["staged"] == ["renamed file.txt"]
    assert s.paths["untracked"] == ["after.txt"]


def test_merge_conflict_is_reported(repo):
    git(repo, "checkout", "-q", "-b", "other")
    (repo / "a.txt").write_text("other\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "other")
    git(repo, "checkout", "-q", "main")
    (repo / "a.txt").write_text("main\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "main")
    git(repo, "merge", "other", check=False)  # conflicts by design
    s = inspect(repo)
    assert s.state == DIRTY and s.conflicts == 1
    assert "unmerged paths present" in s.hazards


def test_not_a_repo_is_unknown_not_clean(tmp_path):
    s = inspect(tmp_path)
    assert s.state == UNKNOWN and "not a git repository" in s.reason
    assert EXIT_CODES[s.state] == 3


def _failing_status(real):
    """The deterministic reproduction from gregoryfoster/skills#257: only the verdict call fails."""
    def runner(args, cwd):
        if args[0] == "status":
            return subprocess.CompletedProcess(["git", *args], 128, b"", b"fatal: Unable to read index\n")
        return real(args, cwd)
    return runner


def test_failing_git_status_is_unknown_never_clean(repo):
    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")  # genuinely dirty: a fail-open check would say clean
    s = inspect(repo, runner=_failing_status(_run_git))
    assert s.state == UNKNOWN
    assert "Unable to read index" in s.reason
    assert "unknown blocks" in render(s)


@pytest.mark.parametrize("exc", [OSError("git not found"), subprocess.TimeoutExpired("git", 30)])
def test_git_that_cannot_run_is_unknown(repo, exc):
    def runner(args, cwd):
        raise exc
    s = inspect(repo, runner=runner)
    assert s.state == UNKNOWN and s.reason


def test_advisory_probe_failure_does_not_flip_the_verdict(repo):
    def runner(args, cwd):
        if args[0] in ("stash", "worktree"):
            return subprocess.CompletedProcess(["git", *args], 1, b"", b"boom")
        return _run_git(args, cwd)
    s = inspect(repo, runner=runner)
    assert s.state == CLEAN and s.stashes is None and s.worktrees is None


def test_stash_and_missing_upstream_are_hazards(repo):
    (repo / "a.txt").write_text("stash me\n", encoding="utf-8")
    git(repo, "stash")
    s = inspect(repo)
    assert s.state == CLEAN and s.stashes == 1 and s.worktrees == 1
    joined = " ".join(s.hazards)
    assert "stash" in joined and "no upstream" in joined


def test_worktrees_counted(repo, tmp_path_factory):
    other = tmp_path_factory.mktemp("wt") / "lane"
    git(repo, "worktree", "add", "-q", "-b", "lane", str(other))
    assert inspect(repo).worktrees == 2


def test_path_buckets_truncate_instead_of_flooding(repo):
    for n in range(60):
        (repo / f"f{n}.txt").write_text("x\n", encoding="utf-8")
    s = inspect(repo)
    assert s.untracked == 60 and len(s.paths["untracked"]) == 50 and s.truncated


def test_cli_exit_codes_and_json(repo, tmp_path_factory, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["nougencode", "git-state", str(repo), "--json"])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["state"] == "clean"

    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["nougencode", "--json", "git-state", str(repo)])  # global flag first
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)["untracked"] == 1

    monkeypatch.setattr(sys, "argv", ["nougencode", "git-state", str(tmp_path_factory.mktemp("nogit"))])
    assert cli.main() == 3
    assert "UNKNOWN" in capsys.readouterr().out
