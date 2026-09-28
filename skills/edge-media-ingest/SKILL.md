---
name: edge-media-ingest
description: Film theory, script formatting, and video storyboard breakdown asset ingestion engine.
author: NouGenCode
version: 1.0.0
primary_verb: evaluate
tags: ["edge", "autonomous", "evaluate"]
---

# edge-media-ingest

Film theory, script formatting, and video storyboard breakdown asset ingestion engine.

## Architecture & Logic
- Primary Verb: `evaluate`
- Standalone execution module located in [scripts/edge_media_ingest.py](scripts/edge_media_ingest.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run via Python or integrate into the NouGenCode REPL:
```bash
python scripts/edge_media_ingest.py --help
```
