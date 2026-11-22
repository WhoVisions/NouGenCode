"""NouGenCode in the NouGen mesh: its own identity, no owner names, Open first, a loadable manifest."""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

from nougencode import lanes, nougen_mesh, siblings
from nougencode import model_runner as mr
from nougencode import recurse_engine, shards_bridge
from nougencode import sweep as sw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "nougencode"
MESH_ENV = ("NOUGEN_ROOT", "NOUGEN_MESH_FILE", "NOUGEN_MACHINE", "NOUGEN_AGENT", "NOUGEN_FLEET_NODE",
            "NOUGEN_NODE_NAME", "NOUGEN_NODE", "NOUGEN_TENANT", "NOUGEN_FLEET_HOSTS_FILE", "NOUGEN_ENDPOINTS_FILE",
            "NOUGEN_INGRESS_URL", "NOUGEN_SHARDS_DIR", "NOUGEN_SHARDS_SOURCE", "NOUGEN_RELAY_DIR", "NOUGEN_OPEN_DIR",
            "NOUGEN_OPEN_URL", "NOUGEN_OPEN_PORT", "NOUGEN_REPOS_DIR", "NOUGEN_CLI", "NOUGEN_VAULT_DIR",
            "NOUGEN_MODEL", "NOUGEN_CODE_MODEL", "NOUGEN_CODE_OPEN_MODEL", "NOUGEN_CODE_VIA_OPEN", "OLLAMA_HOST",
            "NOUGEN_OLLAMA_URL", "NOUGEN_OLLAMA_PORT", "NOUGEN_LMSTUDIO_URL", "NOUGEN_LMSTUDIO_PORT",
            "EDGE_AI_DIR", "YUKI_AI_DIR")


@pytest.fixture
def fresh_box(monkeypatch, tmp_path):
    """A tester's box: empty runtime home, no siblings, its own hostname."""
    for var in MESH_ENV:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NOUGEN_ROOT", str(tmp_path / "home"))
    monkeypatch.setattr(nougen_mesh, "_git_config", lambda key: "")
    monkeypatch.setattr(nougen_mesh, "_hostname", lambda: "tester-laptop")
    real = nougen_mesh.repo_dir

    def only_env_or_mesh(name, near=None):
        return real(name, near=str(tmp_path / "lonely" / "x.py"))
    monkeypatch.setattr(nougen_mesh, "repo_dir", only_env_or_mesh)
    return tmp_path


def _mesh(tmp_path, data):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "mesh.json").write_text(json.dumps(data), encoding="utf-8")


# ------------------------------------------------------------------ identity
def test_fresh_box_is_standalone_and_names_itself(fresh_box):
    assert nougen_mesh.identity()["node"] == "standalone"
    assert nougen_mesh.machine() == "tester-laptop"
    assert shards_bridge.detect_node_name() == "tester-laptop"
    assert sw.hydrate_context(cli="").machine == "tester-laptop"
    assert siblings.known_node_names() == ["tester-laptop"]


def test_shard_vault_lives_under_the_runtime_home(fresh_box, monkeypatch):
    assert shards_bridge.resolve_canonical_shards_dir() == (fresh_box / "home" / "shards").resolve()
    checkout = fresh_box / "NouGenShards"
    checkout.mkdir()
    monkeypatch.setenv("NOUGEN_SHARDS_DIR", str(checkout))        # the mesh's meaning: a checkout
    assert shards_bridge.resolve_canonical_shards_dir() == (fresh_box / "home" / "shards").resolve()
    (checkout / "nougen_shards_1.db").write_bytes(b"")               # an older box pointing it at a vault
    assert shards_bridge.resolve_canonical_shards_dir() == checkout.resolve()


# ------------------------------------------------------------------ siblings
def test_siblings_resolve_through_the_mesh_only(fresh_box, monkeypatch):
    assert siblings.repo_dir("shards") is None and siblings.relay_dir() is None
    assert sw._nougen_cli() in (None, __import__("shutil").which("nougen"))

    shards = fresh_box / "co" / "NouGenShards"
    (shards / "src" / "nougen_shards").mkdir(parents=True)
    (shards / "src" / "nougen_shards" / "__init__.py").write_text("", encoding="utf-8")
    (shards / "src" / "nougen_shards" / "meshprobe.py").write_text("MARK = 'from-checkout'\n", encoding="utf-8")
    (shards / ".venv" / "bin").mkdir(parents=True)
    (shards / ".venv" / "bin" / "nougen").write_text("", encoding="utf-8")
    relay = fresh_box / "co" / "NouGenRelay"
    relay.mkdir()
    _mesh(fresh_box, {"repos": {"shards": str(shards), "relay": str(relay)}})

    assert siblings.repo_dir("shards") == shards
    assert siblings.relay_dir() == relay.resolve()
    assert sw._nougen_cli() == str(shards / ".venv" / "bin" / "nougen")
    monkeypatch.setattr(sys, "path", list(sys.path))
    for mod in [m for m in sys.modules if m == "nougen_shards" or m.startswith("nougen_shards.")]:
        monkeypatch.delitem(sys.modules, mod)
    assert siblings.import_shards("nougen_shards.meshprobe").MARK == "from-checkout"


def test_import_shards_says_how_to_fix_when_absent(fresh_box, monkeypatch):
    monkeypatch.setattr(siblings.importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))
    with pytest.raises(ImportError, match="NOUGEN_SHARDS_DIR"):
        siblings.import_shards()


def test_recurse_sanitiser_names_come_from_the_mesh(fresh_box, monkeypatch):
    assert recurse_engine.resolve_edge_path() is None              # no home-directory guesses
    edge = fresh_box / "edge"
    edge.mkdir()
    _mesh(fresh_box, {"paths": {"edge_ai": str(edge)},
                      "nodes": {"alpha": {"host_patterns": ["alpha-box"]}, "beta": {}}})
    assert recurse_engine.resolve_edge_path() == edge.resolve()
    code = "host = 'alpha-box'  # 192.168.1.20 beta tester-laptop gamma"
    out = recurse_engine.scrub_private_names(code)
    assert out == "host = 'NodeWorker'  # 127.0.0.1 NodeWorker NodeWorker gamma"
    assert recurse_engine.scrub_private_names("x", names=[]) == "x"


# ------------------------------------------------------------------ lanes
class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_net(monkeypatch, routes):
    seen = []

    def fake(req, timeout=None):
        url = req.full_url
        seen.append((url, json.loads(req.data) if req.data else None))
        for prefix, body in routes.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return _Resp(json.dumps(body).encode())
        raise lanes.urllib.error.URLError("refused")
    monkeypatch.setattr(lanes.urllib.request, "urlopen", fake)
    return seen


def test_no_owner_models_or_hosts_by_default(fresh_box):
    assert lanes.local_model() is None and lanes.open_model() == lanes.OPEN_AUTO_MODEL
    assert lanes.open_url() is None and lanes.ollama_url() == "http://127.0.0.1:11434"
    assert lanes.lmstudio_url() == "http://127.0.0.1:1234"
    runner = mr.ModelRunner()
    assert runner.model_name is None and runner.host == "http://127.0.0.1:11434"
    assert runner.describe() == "Ollama Local (first pulled model)"


def test_models_and_hosts_come_from_env_or_mesh(fresh_box, monkeypatch):
    _mesh(fresh_box, {"models": {"code": "mesh-local", "code_open": "mesh-open"}})
    assert lanes.local_model() == "mesh-local" and lanes.open_model() == "mesh-open"
    monkeypatch.setenv("NOUGEN_CODE_MODEL", "env-local")
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0")
    assert lanes.local_model() == "env-local" and lanes.ollama_url() == "http://127.0.0.1:11434"
    monkeypatch.setenv("OLLAMA_HOST", "gpu-box:11500")
    assert mr.ModelRunner().host == "http://gpu-box:11500"
    monkeypatch.setenv("NOUGEN_LMSTUDIO_PORT", "4321")
    assert lanes.lmstudio_url() == "http://127.0.0.1:4321"


def test_local_fallback_uses_the_first_pulled_model(fresh_box, monkeypatch):
    seen = _fake_net(monkeypatch, {
        "http://127.0.0.1:11434/api/tags": {"models": [{"name": "tiny:1b"}, {"name": "other"}]},
        "http://127.0.0.1:11434/api/chat": {"message": {"content": "hi from ollama"}},
    })
    runner = mr.ModelRunner()
    assert runner.chat([{"role": "user", "content": "hi"}]) == "hi from ollama"
    assert runner.last_lane == "ollama" and runner.last_model == "tiny:1b"
    assert seen[-1][1]["model"] == "tiny:1b"


def test_open_goes_first_and_ollama_catches_it_when_down(fresh_box, monkeypatch):
    monkeypatch.setenv("NOUGEN_OPEN_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(lanes, "open_tool_installed", lambda: False)
    seen = _fake_net(monkeypatch, {
        "http://127.0.0.1:8765/v1/chat/completions": {"model": "lane/x", "choices": [{"message": {"content": "free lane"}}]},
    })
    runner = mr.ModelRunner()
    assert "NouGenOpen (nougenopen/auto)" in runner.describe()
    assert runner.chat([{"role": "user", "content": "hi"}], system_prompt="be brief") == "free lane"
    assert runner.last_lane == "open" and runner.last_model == "lane/x"
    body = seen[0][1]
    assert body["model"] == "nougenopen/auto" and body["messages"][0] == {"role": "system", "content": "be brief"}

    monkeypatch.setenv("NOUGEN_CODE_MODEL", "tiny:1b")
    _fake_net(monkeypatch, {"http://127.0.0.1:11434/api/chat": {"message": {"content": "local"}}})
    assert runner.chat([{"role": "user", "content": "hi"}]) == "local"   # Open down -> Ollama
    monkeypatch.setenv("NOUGEN_CODE_VIA_OPEN", "0")
    assert lanes.open_url() is None


def test_open_tool_through_the_mesh_when_serve_is_not_up(fresh_box, monkeypatch):
    calls = []

    def fake_call(name, args, near=None, timeout=None):
        calls.append((name, args))
        return json.dumps({"success": True, "content": "via tool", "model": "lane/y"})
    monkeypatch.setattr(lanes, "open_tool_installed", lambda: True)
    monkeypatch.setattr(nougen_mesh, "call", fake_call)
    out = lanes.chat([{"role": "user", "content": "hi"}], "sys")
    assert out == {"content": "via tool", "lane": "open", "model": "lane/y"}
    assert calls[0][0] == "open.nougen_ask" and calls[0][1]["system"] == "sys" and "model" not in calls[0][1]


def test_nothing_answers_gives_a_clear_message(fresh_box, monkeypatch):
    _fake_net(monkeypatch, {})
    msg = mr.ModelRunner().chat([{"role": "user", "content": "hi"}])
    assert msg.startswith("(No model lane answered") and "NOUGEN_CODE_MODEL" in msg


def test_discovery_and_fabric_defaults_are_neutral(fresh_box, monkeypatch):
    from nougencode.discovery.waterflow import WaterflowDiscovery
    from nougencode.fabric import ChangeFabricEngine
    monkeypatch.setattr(WaterflowDiscovery, "check_daemon", classmethod(lambda cls, h, p, timeout=0.3: False))
    provs = WaterflowDiscovery.discover_providers()
    assert provs["ollama"].endpoint_url == "http://127.0.0.1:11434"
    assert provs["nougen_open"].endpoint_url is None and not provs["nougen_open"].is_available
    from nougencode.fabric import ChangeContract, FunctionalRequirement, ReviewConstraint
    contract = ChangeContract(
        contract_id="CC-MESH", title="mesh defaults",
        functional_requirements=(FunctionalRequirement(req_id="FR", description="d", target_artifacts=("a.py",),
                                                       invariants=("DETERMINISTIC_PROOF",), acceptance_tests=()),),
        review_constraints=ReviewConstraint(constraint_id="RC", max_mutation_files=5, max_mutation_lines=50,
                                            required_reviewers=("r",), forbidden_patterns=()))
    engine = ChangeFabricEngine()
    engine.execute_change_cycle(session_id="s", contract=contract, modified_files=["a.py"], lines_changed=1)
    arms = {(a.provider_id, a.model_id) for a in engine.provider_ucb._arms.values()}
    assert arms == {("local_ollama", "auto"), ("nougen_open", "nougenopen/auto")}, arms


# ------------------------------------------------------------------ no owner names
_OWNER = re.compile(r"(?i)The Observatory|Watchtower|Outpost|kushboygroup|C:\\\\Users\\\\super|/Users/super"
                    r"|nougenai\.com|\bblade\b|\bphoebus\b|\bwhoart\b|HQ_WhoArt|Hyperion|Yukiai|solai|aiwithdav3")


def test_runtime_names_no_owner_paths_hosts_or_models():
    files = sorted(SRC.rglob("*.py")) + [ROOT / "tools" / "lean_loop.sh", ROOT / "nougen.tools.json",
                                         ROOT / "adapters" / "cloudflare" / "wrangler.jsonc"]
    files += sorted((ROOT / "adapters" / "cloudflare" / "src").glob("*.ts"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not _OWNER.search(text), (str(f.relative_to(ROOT)), _OWNER.search(text))


def test_cloudflare_config_carries_no_account_or_host():
    text = (ROOT / "adapters" / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
    assert not re.search(r'"(account_id|routes?|zone_id|zone_name)"\s*:', text)
    assert not re.search(r"[\w.-]+@[\w-]+\.\w+|https?://", text.replace("node_modules/wrangler/config-schema.json", ""))


# ------------------------------------------------------------------ manifest + vendored copy
def test_vendored_mesh_matches_canonical_when_shards_is_here():
    shards = nougen_mesh.repo_dir("shards", near=__file__)
    canon = shards / "src" / "nougen_shards" / "mesh.py" if shards else None
    if canon is None or not canon.exists():
        pytest.skip("no NouGenShards checkout with the mesh module on this box")
    assert nougen_mesh.file_digest(str(SRC / "nougen_mesh.py")) == nougen_mesh.file_digest(str(canon))


def _cli_parser_choices():
    import argparse
    from nougencode import cli
    captured = {}

    class Stop(Exception):
        pass

    def grab(self, *a, **k):
        captured["parser"] = self
        raise Stop
    orig = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = grab
    try:
        cli.main()
    except Stop:
        pass
    finally:
        argparse.ArgumentParser.parse_args = orig
    sub = next(a for a in captured["parser"]._actions if isinstance(a, argparse._SubParsersAction))
    return sub.choices


def test_manifest_loads_and_matches_the_cli():
    data = nougen_mesh.manifest(ROOT)
    assert data["schema"] == nougen_mesh.MANIFEST_SCHEMA and data["repo"] == "code"
    choices = _cli_parser_choices()
    names = {t["name"] for t in data["tools"]}
    assert {"scan", "discover", "audit", "route", "git_state", "capability_profile", "golden_slice",
            "change_fabric", "sweep", "cleanup", "elevate", "bench"} == names
    for t in data["tools"]:
        argv = t["argv"]
        assert t["transport"] == "cli" and argv[0] == "nougencode"
        assert argv[1] in choices, t["name"]
        sub = choices[argv[1]]
        flags = {o for a in sub._actions for o in a.option_strings}
        assert {a for a in argv if a.startswith("--")} <= flags, t["name"]
        slots = {m.group(1) for a in argv for m in [re.fullmatch(r"\{(\w+)\??\}", a)] if m}
        assert slots == set(t["args"]["properties"]) == set(t["args"]["required"]), t["name"]
        if "--apply" in argv or "--push" in argv:
            raise AssertionError(f"{t['name']}: mesh tools stay read-only")


def test_scan_subcommand_takes_a_path(tmp_path, monkeypatch, capsys):
    from nougencode import cli
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["nougencode", "scan", str(tmp_path / "a.py"), "--json", "--no-deps"])
    assert cli.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["target_root"] == str((tmp_path / "a.py").resolve()) and out["files_scanned"] == 1
