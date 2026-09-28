---
name: edge-token-tracker
description: Cross-provider LLM token usage aggregator, cache-read vs generation tracker, and cost monitor.
author: NouGenCode
version: 1.0.0
primary_verb: track
tags: ["nougen", "telemetry", "governance", "track"]
---

# edge-token-tracker

Cross-provider LLM token usage aggregator, cache-read vs generation tracker, and cost monitor.

## Cognitive Instruction & Logic
- Primary Verb: `track`
- Executable core module in [scripts/edge_token_tracker.py](scripts/edge_token_tracker.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run directly or invoke through the NouGenCode REPL:
```bash
python scripts/edge_token_tracker.py --help
```
