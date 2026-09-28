---
name: edge-notion-sync
description: Synchronize local workspace notes, schemas, and tasks with Notion API securely with bidirectional caching.
author: NouGenCode
version: 1.0.0
primary_verb: execute
tags: ["edge", "autonomous", "execute"]
---

# edge-notion-sync

Synchronize local workspace notes, schemas, and tasks with Notion API securely with bidirectional caching.

## Architecture & Logic
- Primary Verb: `execute`
- Standalone execution module located in [scripts/edge_notion_sync.py](scripts/edge_notion_sync.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run via Python or integrate into the NouGenCode REPL:
```bash
python scripts/edge_notion_sync.py --help
```
