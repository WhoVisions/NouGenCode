---
name: edge-paste-guard
description: Token discipline hook to flag oversized pasted inputs and enforce file-based inspection.
author: NouGenCode
version: 1.0.0
primary_verb: harden
tags: ["nougen", "telemetry", "governance", "harden"]
---

# edge-paste-guard

Token discipline hook to flag oversized pasted inputs and enforce file-based inspection.

## Cognitive Instruction & Logic
- Primary Verb: `harden`
- Executable core module in [scripts/edge_paste_guard.py](scripts/edge_paste_guard.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run directly or invoke through the NouGenCode REPL:
```bash
python scripts/edge_paste_guard.py --help
```
