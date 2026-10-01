"""nougencode sweep: Context Mode gate, non-destructive dirty hygiene, skills recursion."""
import datetime as dt
import subprocess
from pathlib import Path

import pytest

from nougencode import sweep as sw

FIXED = dt.datetime(2026, 10, 1, 0, 30, tzinfo=dt.timezone.utc)
FAKE_KEY = "sk-" + "a1b2c3d4e5f6g7h8i9j0k1l2m3"  # matches the gate's pattern, not a real key


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(tmp_path, name="r"):
    r = tmp_path / name
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    (r / "app.py").write_text("x = 1\n")
    git(r, "add", "app.py")
    git(r, "commit", "-q", "-m", "init")
    return r


def fake_run(gh_visibility="PRIVATE", relay="⚠️ 2 leg(s) waiting for an ack:", shards="[1] a\n[2] b\n", fail=()):
    def run(cmd, cwd=None, timeout=30.0):
        if cmd[0] == "gh":
            return 0, gh_visibility + "\n"
        if "relay" in cmd:
            return (1, "boom") if "relay" in fail else (0, relay)
        if "search" in cmd:
            return (1, "boom") if "shards" in fail else (0, shards)
        if "add" in cmd and "--tags" in cmd:
            return 0, "✅ Shard captured!"
        return sw._run(cmd, cwd, timeout)
    return run


FULL = sw.ContextReport("full", "test", {"relay": "ok", "shards": "ok"}, 0, 1)


# ---------------------------------------------------------------- context mode

def test_context_full_only_when_relay_and_shards_both_ok(tmp_path):
    cli = tmp_path / "nougen"
    cli.write_text("")
    c = sw.hydrate_context(run=fake_run(), cli=str(cli))
    assert (c.state, c.relay_waiting, c.shard_hits) == ("full", 2, 2)


def test_keyword_only_recall_is_degraded_not_full(tmp_path):
    cli = tmp_path / "nougen"
    cli.write_text("")
    c = sw.hydrate_context(run=fake_run(shards="WARNING grid DB 3: ... keyword-only for this recall\n[1] a\n"), cli=str(cli))
    assert c.state == "degraded"
    assert "keyword-only" in c.sources["shards"]


def test_relay_exit_3_with_waiting_legs_is_a_successful_read(tmp_path):
    cli = tmp_path / "nougen"
    cli.write_text("")

    def run(cmd, cwd=None, timeout=30.0):
        if "relay" in cmd:
            return 3, "INFO control_loop: x\n⚠️ 5 leg(s) waiting for an ack:\n"
        return fake_run()(cmd, cwd, timeout)

    c = sw.hydrate_context(run=run, cli=str(cli))
    assert c.sources["relay"] == "ok" and c.relay_waiting == 5


def test_relay_failure_degrades(tmp_path):
    cli = tmp_path / "nougen"
    cli.write_text("")
    c = sw.hydrate_context(run=fake_run(fail=("relay",)), cli=str(cli))
    assert c.state == "degraded" and c.sources["relay"].startswith("exit 1")


def test_no_cli_is_local_only():
    c = sw.hydrate_context(run=fake_run(), cli="")
    assert c.state == "local_only"


def test_summary_refuses_to_imply_full_context():
    rep = sw.SweepReport(sw.ContextReport("degraded", "m", {"relay": "ok", "shards": "partial"}), [], 0, [], False, "t")
    assert "cannot prove absence" in rep.summary()


# ---------------------------------------------------------------- hygiene

def test_classification(tmp_path):
    r = make_repo(tmp_path)
    (r / "leak.py").write_text(f'KEY = "{FAKE_KEY}"\n')
    assert sw.classify(r, "tenants.json") == "SECRET_RISK"
    assert sw.classify(r, ".env.local") == "SECRET_RISK"
    assert sw.classify(r, "leak.py") == "SECRET_RISK"  # by content, via ConcentricSecurityGate
    assert sw.classify(r, "logs/run.log") == "RUNTIME"
    assert sw.classify(r, "app.py.bak-20260930") == "BACKUP"
    assert sw.classify(r, "app.py") == "SOURCE"


def test_default_sweep_is_read_only(tmp_path):
    r = make_repo(tmp_path)
    (r / "app.py").write_text("x = 2\n")
    before = (git(r, "rev-parse", "HEAD"), git(r, "status", "--porcelain"), git(r, "branch", "--list"))
    rep = sw.sweep([tmp_path], run=fake_run(), context=FULL, now=FIXED)
    assert rep.repos[0].dirty and rep.repos[0].snapshot is None
    assert (git(r, "rev-parse", "HEAD"), git(r, "status", "--porcelain"), git(r, "branch", "--list")) == before


def test_apply_snapshots_without_touching_head_index_or_worktree(tmp_path):
    r = make_repo(tmp_path)
    (r / "app.py").write_text("x = 2\n")
    (r / "new_tool.py").write_text("print('hi')\n")
    (r / "tenants.json").write_text('{"t": 1}\n')
    (r / "leak.py").write_text(f'KEY = "{FAKE_KEY}"\n')
    git(r, "add", "app.py")  # a lane's real staged state must survive
    head, status, branch = git(r, "rev-parse", "HEAD"), git(r, "status", "--porcelain"), git(r, "rev-parse", "--abbrev-ref", "HEAD")

    rep = sw.sweep([tmp_path], apply=True, run=fake_run(), context=FULL, now=FIXED)
    ref = rep.repos[0].snapshot
    assert ref == "hygiene/snapshot-20261001T003000Z"
    assert (git(r, "rev-parse", "HEAD"), git(r, "status", "--porcelain"), git(r, "rev-parse", "--abbrev-ref", "HEAD")) == (head, status, branch)
    tree = git(r, "ls-tree", "-r", "--name-only", ref).split()
    assert sorted(tree) == ["app.py", "new_tool.py"]  # secrets excluded by name and by content
    assert git(r, "show", f"{ref}:app.py") == "x = 2"
    assert git(r, "rev-parse", f"{ref}^") == head


def test_push_only_for_private_and_unknown_fails_closed(tmp_path):
    r = make_repo(tmp_path)
    git(r, "remote", "add", "origin", "https://github.com/acme/thing.git")
    (r / "app.py").write_text("x = 3\n")
    for vis in ("PUBLIC", "UNKNOWN-JUNK"):
        rep = sw.sweep([tmp_path], apply=True, push=True, run=fake_run(gh_visibility=vis), context=FULL,
                       now=FIXED + dt.timedelta(seconds=len(vis)))
        assert rep.repos[0].pushed is False
        assert "not pushed" in rep.repos[0].note


def test_secret_only_dirt_produces_no_snapshot(tmp_path):
    r = make_repo(tmp_path)
    (r / ".env").write_text("A=1\n")
    rep = sw.sweep([tmp_path], apply=True, run=fake_run(), context=FULL, now=FIXED)
    assert rep.repos[0].snapshot is None
    assert rep.repos[0].counts() == {"SECRET_RISK": 1}


# ---------------------------------------------------------------- skills

def _skill(root, folder, name, desc="d", body=""):
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n")


def test_skills_recursion_reports_each_problem(tmp_path):
    a, b = tmp_path / "repoA" / "skills", tmp_path / "repoB" / "skills"
    _skill(a, "good", "good", body="[run](scripts/run.py)")
    (a / "good" / "scripts").mkdir()
    (a / "good" / "scripts" / "run.py").write_text("")
    _skill(a, "wrongname", "other")
    _skill(a, "nodesc", "nodesc", desc="")
    _skill(a, "ghost", "ghost", body="[x](scripts/missing.py)")
    _skill(a, "shared", "shared", body="v1")
    _skill(b, "shared", "shared", body="v2")
    n, issues = sw.recurse_skills([tmp_path])
    probs = {(i.skill, i.problem.split(":")[0].split(" '")[0]) for i in issues}
    assert n == 6
    assert ("other", "name") in probs
    assert ("nodesc", "frontmatter missing name or description") in probs
    assert ("ghost", "references missing file scripts/missing.py") in probs
    assert ("shared", "drift") in probs
    assert not any(i.skill == "good" for i in issues)


def test_persist_writes_counts_not_contents(tmp_path):
    seen = {}

    def run(cmd, cwd=None, timeout=30.0):
        seen["cmd"] = cmd
        return 0, ""

    rep = sw.SweepReport(FULL, [], 3, [], False, "2026-10-01T00:30:00+00:00")
    assert sw.persist(rep, run=run, cli="/x/nougen") is True
    assert "--tags" in seen["cmd"] and "context_state=full" in seen["cmd"][-1]
