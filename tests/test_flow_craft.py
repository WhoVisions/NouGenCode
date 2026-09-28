from nougencode.flow_craft import FlowCraftEngine, estimate_syllables


def test_estimate_syllables():
    assert estimate_syllables("terminal") >= 3
    assert estimate_syllables("code") == 1
    assert estimate_syllables("subdivision") >= 4
    assert estimate_syllables("rap") == 1


def test_flow_craft_analysis():
    engine = FlowCraftEngine(default_bpm=90)
    lyrics = """
    PX13 edge terminal, clocking sub-fifty millisecond latency,
    Three hundred ten thousand shards, pure database agency.
    Zero token waste, no hallucinations in the buffer zone,
    Tactical operator snapping kernel patches on my own.
    """
    res = engine.analyze_bars(lyrics, bpm=92)
    assert res.total_bars == 4
    assert res.bpm == 92
    assert res.pocket_score > 0.0
    assert res.breath_viability > 0.0
    assert len(res.bars) == 4
    assert res.multisyllabic_density > 0


def test_delivery_markup():
    engine = FlowCraftEngine(default_bpm=90)
    lyrics = "Zero token waste, no hallucinations in the buffer zone"
    marked = engine.suggest_delivery_markup(lyrics)
    assert "[" in marked
    assert "]" in marked
