# NouGenCode cleanup report: first self-pass

Date: 2026-10-05. Legs: `20261004T040718Z__chatgpt-app__g-whoentertains` (repair and redundancy
engine), `20261004T040859Z__chatgpt-app__g-whoentertains` (formulas). Observer: phoebus.

## State found

- The 12 formulas and a report-only cleanup pass were already on `main` (PR #34, 2026-10-04:
  `cleanup/scoring.py`, `cleanup/cleanup_pass.py`, `tests/test_cleanup_scoring.py`). Both legs
  stayed open and unacked for 30 hours after relay-watch routed them to blade; nothing new
  needed building for the formulas.
- Baseline: 268 tests passing.

## Pass over NouGenCode itself (111 Python files, tests excluded)

Before: DELETE 2, PARAMETERIZE 13, MERGE 0, REPAIR 0, KEEP 96.
After the fix below: DELETE 1, PARAMETERIZE 13, MERGE 0, REPAIR 0, KEEP 97.

## Defect repaired

Both DELETE proposals were skill scripts that their `SKILL.md` documents as the executable
core, run from the command line. The pass counted only imports and strings in Python as use,
so a documented script looked unreferenced (a false DELETE, the exact failure the leg warns
about: capability loss). Fix: markdown pages naming `<stem>.py` now count as dynamic-use
evidence (`_doc_script_stems`). `skills/edge-token-tracker/scripts/edge_token_tracker.py` is no
longer proposed for deletion. Tests: `tests/test_cleanup_doc_refs.py` (2, including a negative
control where an unmentioned script keeps `dynamic_use == 0`). Suite: 268 -> 270 passing.

## Files deleted, merged, simplified

None. The pass is report-only and nothing here met the refactor-acceptance gate yet. Net code
change: +~30 lines (the fix and its tests); complexity reduction: 0. The leg's success metric
(delta ID > 0 with capability preserved) is not yet met by any applied change; the value
delivered is removing one wrong deletion proposal.

## Remaining proposals (need review before any change)

| file | action | RED | Pdead | TBR | LOC | CC |
|---|---|---|---|---|---|---|
| `skills/edge-a2a-chat/scripts/a2a_chat.py` | DELETE | 0.00 | 0.93 | 0.00 | 527 | 133 |
| `skills/edge-agent-automations/scripts/edge_agent_automations.py` | PARAMETERIZE | 1.00 | 0.01 | 0.00 | 169 | 50 |
| `skills/edge-workspace-rules/scripts/agent_automations.py` | PARAMETERIZE | 1.00 | 0.12 | 0.00 | 169 | 50 |
| `skills/edge-eval-harness/scripts/edge_eval_harness.py` | PARAMETERIZE | 0.90 | 0.08 | 0.00 | 67 | 2 |
| `skills/edge-story-eval/scripts/eval_harness.py` | PARAMETERIZE | 0.90 | 0.63 | 0.00 | 67 | 2 |
| `src/nougencode/capability_profile.py` | PARAMETERIZE | 0.87 | 0.21 | 0.00 | 261 | 92 |
| `src/nougencode/core/golden_slice.py` | PARAMETERIZE | 0.87 | 0.00 | 0.00 | 405 | 108 |
| `src/nougencode/fabric/context_broker.py` | PARAMETERIZE | 0.73 | 0.05 | 0.00 | 156 | 29 |
| `src/nougencode/fabric/shadow_policy.py` | PARAMETERIZE | 0.73 | 0.08 | 0.00 | 127 | 23 |
| `src/nougencode/cleanup/scoring.py` | PARAMETERIZE | 0.66 | 0.07 | 0.00 | 190 | 29 |
| `src/nougencode/core/directives.py` | PARAMETERIZE | 0.66 | 0.12 | 0.00 | 470 | 61 |
| `src/nougencode/routing/switchboard.py` | PARAMETERIZE | 0.65 | 0.05 | 0.00 | 122 | 10 |
| `src/nougencode/skills_engine.py` | PARAMETERIZE | 0.65 | 0.21 | 0.00 | 143 | 31 |
| `src/nougencode/models.py` | PARAMETERIZE | 0.62 | 0.00 | 0.00 | 60 | 3 |

Notes:
- `skills/edge-a2a-chat/scripts/a2a_chat.py` (527 LOC, CC 133, no reference in any code or doc,
  network exposure) is a real orphan candidate. DELETE requires owner review: it may be an
  unfinished skill core. Not removed.
- Two PARAMETERIZE pairs are near-duplicate skill scripts that differ by 8 diff lines each:
  `edge-agent-automations/scripts/edge_agent_automations.py` vs
  `edge-workspace-rules/scripts/agent_automations.py`, and
  `edge-eval-harness/scripts/edge_eval_harness.py` vs `edge-story-eval/scripts/eval_harness.py`.
  Skills ship as self-contained folders, so merging them needs a decision on shared code
  between skills before any change.

## Not covered

- The Grant Compiler items in the first leg (spacing, funder logic, motion resolver, provider
  selection) are not in this repository; this pass did not touch them.
- Signals are static (AST and git history); no runtime coverage was measured.
