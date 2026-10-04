import json
import math
import textwrap

import pytest

from nougencode.cleanup import scoring as S
from nougencode.cleanup import run_cleanup_pass


def test_intelligence_density_divides_value_by_cost():
    lean = S.intelligence_density(1, 1, 1, 1, 1, 0, 0, 0, 0)
    heavy = S.intelligence_density(1, 1, 1, 1, 1, 1, 1, 1, 1)
    assert lean == 1.0
    assert heavy == pytest.approx(1 / 5)
    assert S.intelligence_density(0, 1, 1, 1, 1, 0, 0, 0, 0) == 0.0


def test_repair_priority_discounted_by_cost():
    assert S.repair_priority(1, 1, 1, 1, 1, 0) == 1.0
    assert S.repair_priority(1, 1, 1, 1, 1, 1) == 0.5


def test_inputs_are_clamped_and_nan_is_zero():
    assert S.repair_priority(5, 1, 1, 1, 1, -3) == 1.0
    assert S.trust_boundary_risk(float("nan"), 1, 1, 1, 1) == 0.0


def test_redundancy_is_weighted_mean():
    assert S.redundancy(1, 1, 1, 1, 1) == pytest.approx(1.0)
    assert S.redundancy(0, 0, 0, 0, 0) == 0.0
    assert S.redundancy(1, 0, 0, 0, 0) == pytest.approx(S.DEFAULT_WEIGHTS["w_ast"])


def test_value_formulas_match_spec():
    assert S.delete_value(1, 1, 1, 1, 1, 0, 0) == 5
    assert S.delete_value(0, 0, 0, 0, 0, 1, 1) == -2
    assert S.merge_value(1, 1, 1, 1, 1) == 0.5
    assert S.parameterization_value(1, 1, 1, 1, 1) == pytest.approx(1 / 3)


def test_dead_probability_is_sigmoid_and_dynamic_use_protects():
    w = S.DEFAULT_WEIGHTS
    z = w["a_bias"] + w["a_unreferenced"] + w["a_uncovered"] + w["a_stale"] + w["a_unreachable"] + w["a_unused_export"]
    assert S.dead_probability(1, 1, 1, 1, 1, 0) == pytest.approx(1 / (1 + math.exp(-z)))
    assert S.dead_probability(1, 1, 1, 1, 1, 1) < S.dead_probability(1, 1, 1, 1, 1, 0)
    assert S.dead_probability(0, 0, 0, 0, 0, 0) < 0.1


def test_trust_boundary_risk_is_product():
    assert S.trust_boundary_risk(1, 1, 1, 1, 1) == 1.0
    assert S.trust_boundary_risk(1, 1, 0, 1, 1) == 0.0
    assert S.trust_boundary_risk(0.5, 0.5, 1, 1, 1) == 0.25


def test_simplification_gain_sums_relative_reductions():
    assert S.simplification_gain(S.Metrics(100, 10, 4, 2), S.Metrics(50, 5, 2, 1)) == pytest.approx(2.0)
    assert S.simplification_gain(S.Metrics(10, 1, 1, 1), S.Metrics(20, 1, 1, 1)) == pytest.approx(-1.0)


def _ev(**kw):
    base = dict(capability_before=1, capability_after=1, correctness_before=1, correctness_after=1,
                before=S.Metrics(100, 10, 3, 2), after=S.Metrics(80, 8, 3, 2),
                required_tests_passed=True, attack_surface_before=0.2, attack_surface_after=0.2)
    base.update(kw)
    return S.AcceptanceEvidence(**base)


def test_refactor_acceptance_gate():
    assert S.refactor_acceptance(_ev()).accepted
    assert not S.refactor_acceptance(_ev(capability_after=0.9)).accepted
    assert not S.refactor_acceptance(_ev(correctness_after=0.9)).accepted
    assert not S.refactor_acceptance(_ev(after=S.Metrics(120, 12, 3, 2))).accepted
    assert "required tests not run" in S.refactor_acceptance(_ev(required_tests_passed=None)).reasons
    assert "new attack surface" in S.refactor_acceptance(_ev(attack_surface_after=0.5)).reasons


def test_selector_respects_safety_constraints():
    # DELETE has the highest raw value but Pdead is too low -> blocked, falls to next best.
    d = S.select_action(dv=5, mv=0.1, pv=0.3, rp=0.2, pdead=0.5, red=0.9, tbr=0.0)
    assert d.action is S.CleanupAction.PARAMETERIZE
    assert any(b.startswith("DELETE") for b in d.blocked)
    # MERGE gated on redundancy.
    d = S.select_action(dv=0, mv=0.9, pv=0, rp=0, pdead=0, red=0.5, tbr=0)
    assert d.action is S.CleanupAction.KEEP
    # Destructive actions always need review.
    d = S.select_action(dv=5, mv=0, pv=0, rp=0, pdead=0.99, red=0, tbr=0)
    assert d.action is S.CleanupAction.DELETE and d.requires_review
    # High trust-boundary risk forces review even for REPAIR.
    d = S.select_action(dv=0, mv=0, pv=0, rp=0.9, pdead=0, red=0, tbr=0.9)
    assert d.action is S.CleanupAction.REPAIR and d.requires_review


def test_net_objective():
    assert S.net_objective([{"sg": 2, "capability_delta": -0.5, "tbr_after": 0.25}, {"sg": 1}]) == pytest.approx(2.25)


def test_weights_override_file(tmp_path, monkeypatch):
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"min_pdead_for_delete": 0.99}))
    monkeypatch.setenv(S.WEIGHTS_ENV, str(p))
    assert S.load_weights()["min_pdead_for_delete"] == 0.99
    p.write_text(json.dumps({"nope": 1}))
    with pytest.raises(ValueError):
        S.load_weights()


def _write(root, rel, body):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_cleanup_pass_ranks_and_never_mutates(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/core.py", """
        from pkg.util import helper
        def run(x):
            return helper(x) + 1
    """)
    _write(tmp_path, "pkg/util.py", """
        def helper(x):
            if x:
                return x * 2
            return 0
    """)
    _write(tmp_path, "pkg/orphan.py", """
        import subprocess, os
        def forgotten(cmd):
            # TODO remove
            try:
                subprocess.run(cmd, shell=True)
            except Exception:
                pass
            open(os.environ["X"], "w").write("y")
    """)
    _write(tmp_path, "tests/test_core.py", """
        from pkg.core import run
        def test_run():
            assert run(1) == 3
    """)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.py")}
    report = run_cleanup_pass(tmp_path)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.py")} == before
    assert report["mutations"] == 0
    files = {f["file"]: f for f in report["files"]}
    assert "tests/test_core.py" not in files
    orphan = files["pkg/orphan.py"]
    assert orphan["signals"]["unreachable"] == 1.0
    assert orphan["signals"]["covered"] == 0.0
    assert orphan["TBR"] > files["pkg/util.py"]["TBR"]
    assert report["rank_by"]["TBR"][0] == "pkg/orphan.py"
    assert files["pkg/util.py"]["signals"]["unreachable"] == 0.0
    for p in report["proposed"]:
        assert p["test_obligations"]
        if p["action"] in ("DELETE", "MERGE"):
            assert p["requires_review"]


def test_cleanup_pass_detects_cross_file_redundancy(tmp_path):
    body = """
        def {name}(items):
            total = 0
            for item in items:
                if item > 0:
                    total += item
            return total
    """
    _write(tmp_path, "a.py", body.format(name="sum_pos"))
    _write(tmp_path, "b.py", body.format(name="sum_positive"))
    report = run_cleanup_pass(tmp_path)
    files = {f["file"]: f for f in report["files"]}
    assert files["a.py"]["RED"] >= 0.8
    assert files["a.py"]["RED_peer"] == "b.py::sum_positive"
