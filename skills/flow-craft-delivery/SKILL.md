---
name: flow-craft-delivery
description: Analyze rap cadence, metric subdivision, breath capacity, and multi-syllabic rhyme architecture based on Paul Edwards' 'How to Rap' doctrine.
author: NouGenCode
version: 1.0.0
primary_verb: harden
tags: ["cadence", "rhythm", "subdivision", "breath", "rap", "flow"]
---

# Flow Craft & Delivery (`flow-craft-delivery`)

Synthesizes the core principles of Paul Edwards' *How to Rap* (Volumes 1 & 2) into operational metrics for generative verse engines and emcee performance analysis.

## Core Evaluation Dimensions

1. **Metric Grid Subdivisions**:
   - `half-time`: 4–6 syllables per bar, spacious conversational cadence.
   - `eighth`: 7–10 syllables per bar, natural standard tempo pocket.
   - `triplet`: 11–14 syllables per bar, rolling 3-against-2 swing groove.
   - `sixteenth` / `double-time`: 15+ syllables per bar, high-speed rhythmic compression.

2. **Pocket Score ($0.0 - 1.0$)**:
   - Quantifies how strictly syllable counts lock to natural rhythm cells without awkward elongation or rushing.

3. **Breath Architecture ($0.0 - 1.0$)**:
   - Monitors aerodynamic lung pressure: penalizes 3+ consecutive high-speed bars that lack a structural rest.

4. **Multi-Syllabic Density**:
   - Measures compound internal and end-rhyme stacks across measures.

## CLI & REPL Usage

```bash
python -m nougencode.flow_craft "Your verse lyrics here..." --bpm 92
```

## Python Integration

```python
from nougencode.flow_craft import FlowCraftEngine

engine = FlowCraftEngine(default_bpm=92)
result = engine.analyze_bars(lyrics)

print(f"Pocket Score: {result.pocket_score}")
print(f"Breath Viability: {result.breath_viability}")
print(f"Dominant Subdivision: {result.dominant_subdivision}")
```
