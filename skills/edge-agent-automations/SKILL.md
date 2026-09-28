---
name: edge-agent-automations
description: Autonomous background pipeline trigger, schedule runner, and event-driven worker orchestration.
author: NouGenCode
version: 1.0.0
primary_verb: deploy
tags: ["edge", "autonomous", "deploy"]
---

# edge-agent-automations

Autonomous background pipeline trigger, schedule runner, and event-driven worker orchestration.

## Architecture & Logic
- Primary Verb: `deploy`
- Standalone execution module located in [scripts/edge_agent_automations.py](scripts/edge_agent_automations.py).
- Sanitized for cross-platform zero-hardcode deployment.

## Usage
Run via Python or integrate into the NouGenCode REPL:
```bash
python scripts/edge_agent_automations.py --help
```
