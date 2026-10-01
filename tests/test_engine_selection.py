"""Constraint-aware engine selection (MEDEM / Torch-PIM morph): placement = f(workload, observed state)."""
import pytest

from nougencode.fabric import ContextualProviderUCB, WorkloadSpec


def fleet():
    r = ContextualProviderUCB()
    r.register_arm("node_a_ollama", "qwen-7b", is_local=True, capabilities={"code", "chat"}, memory_mb=5200, host="node-a")
    r.register_arm("node_b_ollama", "qwen-7b", is_local=True, capabilities={"code", "chat"}, memory_mb=5200, host="node-b")
    r.register_arm("cloud", "frontier", is_local=False, cost_per_1k_tokens=0.015, capabilities={"code", "chat", "vision"})
    return r


def reasons(d):
    return dict(d.rejected)


def test_memory_constraint_moves_work_off_a_starved_host():
    d = fleet().select_engine(WorkloadSpec("code_edit", frozenset({"code"})), host_free_mb={"node-a": 1200, "node-b": 9000})
    assert "node_a_ollama:qwen-7b" in reasons(d)
    assert "1200MB free" in reasons(d)["node_a_ollama:qwen-7b"]
    assert d.selected_provider_id != "node_a_ollama"


def test_unknown_host_memory_is_not_a_veto():
    d = fleet().select_engine(WorkloadSpec("code_edit", frozenset({"code"})), host_free_mb={"node-b": 9000})
    assert "node_a_ollama:qwen-7b" not in reasons(d)


def test_capability_constraint_and_its_reason():
    d = fleet().select_engine(WorkloadSpec("screenshot", frozenset({"vision"})))
    assert d.selected_provider_id == "cloud"
    assert reasons(d)["node_b_ollama:qwen-7b"] == "missing capabilities: vision"


def test_unavailable_engine_is_skipped():
    r = fleet()
    r.set_available("cloud", "frontier", False)
    d = r.select_engine(WorkloadSpec("screenshot", frozenset({"vision"})))
    assert d.selected_provider_id is None and d.objective is None
    assert reasons(d)["cloud:frontier"] == "unavailable"


def test_learns_per_workload_class_which_engine_is_good_at_what():
    r = fleet()
    for _ in range(6):
        r.observe("node_b_ollama", "qwen-7b", "code_edit", quality=0.9, latency_ms=900)
        r.observe("cloud", "frontier", "code_edit", quality=0.6, latency_ms=900, cost_usd=0.02)
        r.observe("node_b_ollama", "qwen-7b", "summarize", quality=0.3, latency_ms=900)
        r.observe("cloud", "frontier", "summarize", quality=0.95, latency_ms=900, cost_usd=0.02)
    free = {"node-a": 0, "node-b": 9000}
    assert r.select_engine(WorkloadSpec("code_edit", frozenset({"code"})), free).selected_provider_id == "node_b_ollama"
    assert r.select_engine(WorkloadSpec("summarize", frozenset({"chat"})), free).selected_provider_id == "cloud"


def test_latency_ceiling_uses_observed_class_latency():
    r = fleet()
    for _ in range(3):
        r.observe("node_b_ollama", "qwen-7b", "voice_turn", quality=0.9, latency_ms=4000)
    d = r.select_engine(WorkloadSpec("voice_turn", frozenset({"chat"}), max_latency_ms=1500), {"node-a": 0, "node-b": 9000})
    assert reasons(d)["node_b_ollama:qwen-7b"].startswith("latency 4000ms > max 1500ms")


def test_critical_work_requires_proven_quality_not_optimism():
    r = fleet()
    w = WorkloadSpec("deploy", frozenset({"code"}), min_quality=0.5, critical=True)
    d0 = r.select_engine(w)
    assert d0.selected_provider_id is None  # nothing has a track record yet
    for _ in range(25):
        r.observe("node_b_ollama", "qwen-7b", "deploy", quality=0.95, latency_ms=800)
    assert r.select_engine(w).selected_provider_id == "node_b_ollama"


def test_critical_bound_is_hoeffding_and_tightens_with_evidence():
    r = fleet()
    w = WorkloadSpec("deploy", frozenset({"code"}), min_quality=0.8, critical=True)
    for _ in range(5):
        r.observe("node_b_ollama", "qwen-7b", "deploy", quality=0.95, latency_ms=800)
    assert r.select_engine(w).selected_provider_id is None  # 0.95 - sqrt(ln20/10) = 0.40 < 0.8
    for _ in range(95):
        r.observe("node_b_ollama", "qwen-7b", "deploy", quality=0.95, latency_ms=800)
    assert r.select_engine(w).selected_provider_id == "node_b_ollama"  # n=100: 0.95 - 0.12 = 0.83


def test_ewma_update_matches_the_formula():
    r = fleet()
    r.observe("cloud", "frontier", "x", quality=1, latency_ms=1000, cost_usd=0.10, ewma_lambda=0.25)
    r.observe("cloud", "frontier", "x", quality=1, latency_ms=2000, cost_usd=0.30, ewma_lambda=0.25)
    st = r.workload_stats("cloud", "frontier", "x")
    assert st.ewma_latency_ms == pytest.approx(0.75 * 1000 + 0.25 * 2000)
    assert st.ewma_cost_usd == pytest.approx(0.75 * 0.10 + 0.25 * 0.30)
    with pytest.raises(ValueError):
        r.observe("cloud", "frontier", "x", quality=1, latency_ms=1, ewma_lambda=0)


def test_update_preserves_engine_metadata():
    r = fleet()
    r.update("node_a_ollama", "qwen-7b", reward=0.5, latency_ms=100)
    d = r.select_engine(WorkloadSpec("code_edit", frozenset({"code"})), {"node-a": 1, "node-b": 9000})
    assert "node_a_ollama:qwen-7b" in reasons(d)  # memory_mb/host survived the rebuild in update()


def test_ties_break_deterministically():
    a = [fleet().select_engine(WorkloadSpec("t", frozenset({"code"}))).selected_provider_id for _ in range(5)]
    assert len(set(a)) == 1


def test_select_route_is_unchanged_for_existing_callers():
    r = fleet()
    assert r.select_route(task_complexity="medium").selected_provider_id == "node_a_ollama"  # first untried local arm
