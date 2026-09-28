---
name: edge-scan-guard
description: Pre-tool execution guard that prevents context-killing recursive directory tree scans and massive file dumps.
author: NouGenCode
version: 1.0.0
primary_verb: harden
tags: ["nougen", "telemetry", "governance", "harden"]
---

# edge-scan-guard

Pre-tool execution guard that prevents context-killing recursive directory tree scans and massive file dumps.

## Cognitive Instruction & Logic
- Primary Verb: `harden`
- Executable core module in [scripts/edge_scan_guard.py](scripts/edge_scan_guard.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run directly or invoke through the NouGenCode REPL:
```bash
python scripts/edge_scan_guard.py --help
```
