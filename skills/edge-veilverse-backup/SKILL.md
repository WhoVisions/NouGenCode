---
name: edge-veilverse-backup
description: Local vector database and episodic memory backup, compression, and snapshot utility.
author: NouGenCode
version: 1.0.0
primary_verb: repair
tags: ["edge", "autonomous", "repair"]
---

# edge-veilverse-backup

Local vector database and episodic memory backup, compression, and snapshot utility.

## Architecture & Logic
- Primary Verb: `repair`
- Standalone execution module located in [scripts/edge_veilverse_backup.py](scripts/edge_veilverse_backup.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run via Python or integrate into the NouGenCode REPL:
```bash
python scripts/edge_veilverse_backup.py --help
```
