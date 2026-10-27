---
name: edge-repo-verify-ladder
description: Verification ladder for a JS/TS repo someone handed you — finds the code the green run never checked and the host traps that make tests lie.
author: NouGenCode
version: 1.0.0
primary_verb: verify
tags: ["nougen", "verification", "typescript", "intake"]
---

# edge-repo-verify-ladder

Run this before claiming a received repo is healthy, and before building on it.

## Usage
```bash
python scripts/repo_verify_ladder.py <repo> [--no-tests] [--json]
```
Exit code 1 means at least one step failed.

## What it checks, and why each one exists
Learned on a first-pass repair of a Next.js + Prisma + Vitest repo (3,155 tests, 2026-10-26):

1. **Disk.** A build hit ENOSPC copying node_modules into standalone output, and a
   later edit truncated a source file to 0 bytes. Below ~2 GB, write edits to a
   temp file and `os.replace` it in; restore from git if a file shrinks to 0.
2. **Prisma client.** An ungenerated client failed every test importing it. Run
   `npx prisma generate` before reading any test numbers.
3. **Node 25 Web Storage.** One host flag caused 179 of 183 failures: Node's global
   `localStorage` shadows jsdom's. Fix: `test.execArgv: ["--no-experimental-webstorage"]`.
   Vitest 4 silently ignores the old `poolOptions.forks.execArgv`.
4. **Directories tsconfig excludes.** Lint, tests and `tsc --noEmit` all passed while
   `scripts/` held 50 type errors, several of them real runtime bugs: undefined identifiers,
   a method that was called but never defined, a Prisma `orderBy` on a column that does
   not exist, and a `create` missing a required field. The ladder typechecks each excluded dir.
5. **Syntax errors mask semantic ones.** A TS1xxx error in a file hides its type
   errors. Call arguments with no call head mean a botched splice: rebuild the call
   (or the missing helper) rather than deleting the arguments.
6. **Tests at capped workers.** Full parallelism crashed forks and timed out heavy
   dynamic imports. That was load, not code: cap workers (`maxWorkers: 4`) and raise
   `testTimeout`, then judge the code.

## Repair rules that held up
- When a component changes, its spec drifts. Update the spec to the new behavior
  (lazy chart → `findBy*`, moved button → click its tab first); never weaken the component.
- On Windows, `execFileSync("npx")` needs `shell: true`, and temp-dir cleanup after
  sqlite tests can hit EPERM, so make that cleanup best-effort.
- A model reviewer is a second opinion, not a verdict: apply only findings you can
  confirm against the code.
