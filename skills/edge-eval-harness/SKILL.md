---
name: edge-eval-harness
description: Multi-model latency, accuracy, and output quality benchmark evaluation harness.
author: NouGenCode
version: 1.0.0
primary_verb: benchmark
tags: ["edge", "autonomous", "benchmark"]
---

# edge-eval-harness

Multi-model latency, accuracy, and output quality benchmark evaluation harness.

## Architecture & Logic
- Primary Verb: `benchmark`
- Standalone execution module located in [scripts/edge_eval_harness.py](scripts/edge_eval_harness.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run via Python or integrate into the NouGenCode REPL:
```bash
python scripts/edge_eval_harness.py --help
```
