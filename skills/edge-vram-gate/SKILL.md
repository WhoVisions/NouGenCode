---
name: edge-vram-gate
description: Hardware GPU VRAM admission gatekeeper and resident model checker before running local inference.
author: NouGenCode
version: 1.0.0
primary_verb: live
tags: ["nougen", "telemetry", "governance", "live"]
---

# edge-vram-gate

Hardware GPU VRAM admission gatekeeper and resident model checker before running local inference.

## Cognitive Instruction & Logic
- Primary Verb: `live`
- Executable core module in [scripts/edge_vram_gate.py](scripts/edge_vram_gate.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run directly or invoke through the NouGenCode REPL:
```bash
python scripts/edge_vram_gate.py --help
```
