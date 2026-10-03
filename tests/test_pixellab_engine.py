"""PixelLab as an engine arm: capability routing, probed availability, per-call cost."""
from nougencode.fabric import ContextualProviderUCB, WorkloadSpec
from nougencode.fabric import pixellab as pl

TRIAL = {"credits": {"type": "usd", "usd": 0.0},
         "subscription": {"type": "generations", "status": "trial", "plan": None, "generations": 40.0, "total": 40.0}}


def fleet(**probe_result):
    r = ContextualProviderUCB()
    r.register_arm("node_a_ollama", "qwen-7b", capabilities={"code", "chat"})
    r.register_arm("cloud", "frontier", is_local=False, cost_per_1k_tokens=0.015, capabilities={"code", "chat", "vision"})
    detail = pl.register_pixellab(r, "SENTINEL-TOKEN-9f3a", probe_fn=lambda t: probe_result.get("result", (True, "ok")), cost_per_call=0.02)
    return r, detail


def test_sprite_work_routes_to_pixellab_and_text_engines_explain_why_not():
    r, _ = fleet()
    d = r.select_engine(WorkloadSpec("sprite_sheet", frozenset({"image.sprite"})))
    assert (d.selected_provider_id, d.selected_model_id) == ("pixellab", "pixflux")
    assert dict(d.rejected)["cloud:frontier"] == "missing capabilities: image.sprite"


def test_code_work_never_routes_to_pixellab():
    r, _ = fleet()
    d = r.select_engine(WorkloadSpec("code_edit", frozenset({"code"})))
    assert d.selected_provider_id != "pixellab" and "pixellab:pixflux" in dict(d.rejected)


def test_exhausted_account_is_unavailable_with_reason():
    r, detail = fleet(result=pl.parse_balance({"credits": {"usd": 0}, "subscription": {"generations": 0, "status": "trial"}}))
    d = r.select_engine(WorkloadSpec("sprite_sheet", frozenset({"image.sprite"})))
    assert d.selected_provider_id is None and dict(d.rejected)["pixellab:pixflux"] == "unavailable"
    assert detail.startswith("no credit")


def test_parse_balance_on_the_real_trial_shape():
    ok, detail = pl.parse_balance(TRIAL)
    assert ok and detail == "40/40 generations; subscription trial"
    assert pl.parse_balance({"credits": {"usd": 3.5}, "subscription": {}})[0] is True


def test_probe_failures_never_raise_and_never_leak_the_token():
    def boom(url, token):
        raise OSError(f"connection refused for {token}")
    ok, detail = pl.probe("secret-token-value", fetch=boom)
    assert ok is False and "secret-token-value" not in detail and detail == "balance probe failed: OSError"
    assert pl.probe(None) == (False, "no PIXELLAB_API_KEY")


def test_per_call_cost_is_used_for_generation_billed_engines():
    r, _ = fleet()
    r.register_arm("other_art", "v1", is_local=False, capabilities=pl.CAPABILITIES, cost_per_call=0.50)
    d = r.select_engine(WorkloadSpec("sprite_sheet", frozenset({"image.sprite"}), w_quality=0.0))
    assert d.selected_provider_id == "pixellab"  # $0.02/call beats $0.50/call


def test_token_is_not_stored_on_the_arm():
    r, _ = fleet()
    assert "SENTINEL-TOKEN-9f3a" not in repr(r._arms["pixellab:pixflux"])
