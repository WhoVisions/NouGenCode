import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "edge-repo-verify-ladder" / "scripts" / "repo_verify_ladder.py"
spec = importlib.util.spec_from_file_location("repo_verify_ladder", SCRIPT)
ladder_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ladder_mod)


def test_tsconfig_globs_are_not_comments(tmp_path):
    cfg = tmp_path / "tsconfig.json"
    cfg.write_text('{\n  // comment\n  "paths": {"@/*": ["./src/*"]},\n  "exclude": ["node_modules", "scripts",],\n}\n')
    data = ladder_mod.load_json(cfg)
    assert data["paths"] == {"@/*": ["./src/*"]}
    assert data["exclude"] == ["node_modules", "scripts"]


def test_not_a_js_repo_fails_fast(tmp_path):
    findings = ladder_mod.ladder(tmp_path, run_tests=False)
    assert findings == [{"step": "package", "status": "fail",
                         "detail": "no package.json; not a JS/TS repo root"}]


def test_missing_node_modules_is_reported(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    steps = {f["step"]: f["status"] for f in ladder_mod.ladder(tmp_path, run_tests=False)}
    assert steps["install"] == "fail"
