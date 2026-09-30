# NouGenCode

## Human-context kernels: time, digestibility, evidence

The `nougencode.time_model`, `nougencode.digestibility`, and
`nougencode.scenario_model` modules provide small, dependency-free primitives
for three recurring context failures. Their interfaces make assumptions and
unknowns visible; they do not manufacture trust or semantic understanding.

### Time model

`resolve_zone(user_iana, machine_iana)` applies explicit-user, machine-IANA,
then UTC precedence. `estimate_utc` accepts externally supplied aware samples;
it reports `verified=True` only when at least two distinct source labels agree
within the declared tolerance. A local clock by itself is always unverified.
This verifies agreement under the caller's source-independence assumption; it
does not authenticate those sources. Production callers should obtain time
samples through their configured trusted-time service and preserve source IDs.

Wall-time classification round-trips both `fold` values through `zoneinfo`.
Ambiguous fall-back times require `earlier` or `later`; nonexistent spring-gap
times raise. A recurrence should retain its IANA zone and explicit ambiguity
policy, derive each occurrence from its intended local calendar date, and use
the occurrence date plus rule identity as an idempotency key. Elapsed timers
use `Deadline` and a monotonic reading, never wall-clock subtraction.

### Digestibility model

The semantic extractor is an upstream model contract. It must return ordered
atomic `MeaningUnit`s with stable IDs, exact source references, estimated token
cost, dependencies, and claim qualifications. The deterministic partitioner
minimizes

`Σ_chunks [αN + βD + γJ + δB + λR + μ + ρ((chunk_tokens − target_tokens) / target_tokens)²]`

where N is new concepts, D unresolved dependencies, J unexplained specialist
terms, B decisions, R repeated concepts, and α/β/γ/δ/λ/μ/ρ are explicit
calibration weights. Earlier chunks count as introduced concepts; future
dependencies are charged as unresolved. The algorithm minimizes this objective
subject to the hard token budget, source order, no lost required units, and
qualification adjacency. Token costs must come from the target tokenizer (or
be labeled as an estimate); characters are not tokens. A unit larger than the
budget is rejected rather than silently cut. `verify_plan` checks structural
coverage and provenance identity only. It does not establish factual truth,
clarity, or comprehension.

`ReaderContext` counts only explicitly listed concepts and terms as known.
`comprehension_cost` exposes the proposed `αN + βD + γJ + δB` score (new
concepts, unresolved dependencies, unexplained specialist terms, and decisions)
with tunable weights. The partitioner uses that reader-specific score with
repetition, fragmentation, and chunk-balance terms. `verify_rendering`
packages semantic-verifier observations for missing units, added claims, and
certainty changes, and checks source coverage and prerequisite ordering. A
model verifier's judgment still needs calibration and human review.

Evaluate chunking with preregistered audience/task cohorts: comprehension
questions on qualifications and causal links, task completion/accuracy,
reading time, and omission or distortion rate. Compare against the original
unpartitioned presentation and a fixed-size baseline, stratified by expertise
and channel. Tune the cost model on held-out readers; do not call a token or
readability score a comprehension result.

### Evidence-bounded scenario model

`Feat` requires continuity, source, locator, observed action, conditions, and
optional measured quantity/unit. `comparable` checks only that both measured
values share a unit; callers still need to inspect continuity, equipment,
assistance, fatigue, restraint, and other conditions. `ScenarioState` separates
physical state, resources, observed knowledge, available equipment, and
constraints. `apply_preparation` charges declared costs and adds only explicit
results. `choose_action` considers only actions whose knowledge/equipment and
resource requirements are satisfied and whose outcome probabilities sum to 1.

The expectation is `Σ_outcomes P(outcome | action, evidence) × U(outcome)`.
Probabilities and utilities are inputs requiring evidence or declared
simulation assumptions. This reference layer does not infer canon, invent
measured character capabilities, or establish that a selected action will
succeed. Unknown knowledge remains unknown until an explicit preparation
result adds it.

`choose_plan` implements a normalized constrained plan score after removing
unauthorized, incapable, non-finite, or over-budget plans:
`quality − λT(seconds/max_seconds) − λC(cost/max_cost) − λF(failure_probability)`.
The estimates and policy weights must be supplied and calibrated; no defaults
make an estimate factual.

### NouGenMorph and latent requirements

The existing `NouGenMorphEngine` now requires source provenance before a donor
pattern becomes a candidate, rejects vendor names in generalized execution
rules, and advances candidates through recorded tests, independent verification,
and adoption. A free-form proof string cannot promote a candidate. These
references make the lifecycle auditable, but they do not authenticate a
verifier or execute its test suite; the verifier adapter must produce real
artifact references and authority must be checked at the mutation boundary.

`ProductJudgmentCritic` accepts requirement proposals with evidence IDs rather
than asserting empty/loading/accessibility behavior from keyword presence.
Internal NouGen evidence must support an inferred requirement; a donor claim
alone cannot. Implementation status is accepted only from a different verifier
with cited evidence. The LSC score penalizes unsupported proposals, while
implementation and assessment coverage are reported separately so a supported
but missing requirement remains visible as a gap.

`physics_model` implements the attachment's classical estimates: clipped energy
reserve balance, constant-speed lift force/work/reserve, upward flight thrust
against gravity and quadratic drag, and non-relativistic impact energy/average
force. Fictional parameters (collection area, efficiency, thrust, effective
mass, transfer fraction) stay explicit inputs. Lift feasibility checks force
and energy separately. The model excludes relativistic motion, structural
failure, biological durability, and fictional flight momentum mechanisms; its
outputs are not canon measurements.

### Mission continuity

`mission_runtime` makes objective, required outcomes, constraints, completion
evidence, and authority reference immutable in `MissionContract`. `MissionJournal`
appends content-addressed step records and resource-spend receipts. A reported
success does not count toward completion: every required outcome and every
completion-evidence reference must occur on a step with an explicitly passing
named verifier. Stable operation IDs deduplicate identical effects across worker
replacement; reuse with changed result content fails closed. `resume_packet`
transfers the intent contract/hash, verified history, unverified reports,
remaining work, and budget use to a replacement worker; the packet can be
checked against the original contract before resuming.

This is an in-process reference journal, not durable NouGenShards/Relay/Tracker
integration. An adapter must persist append-only records and enforce the same
idempotency key at the external effect boundary. Authentication of the authority
reference, stale-memory conflict policy, and independent verifier correctness
remain integration/evaluation requirements.

Run the focused checks with `python -m pytest tests/test_human_context_kernels.py`.

NouGenCode combines repository analysis tools with a provider-neutral software
engineering control plane. Persistent engineering roles describe responsibilities
and safety contracts; replaceable providers declare capabilities and are selected
by the Switchboard using capability fit and recorded competency.

## Mission lifecycle

The controller runs a bounded path from intent to a proof object:

1. Context Gate preflight records the mission and searches relevant session context.
2. Repository cartography maps the checkout and its targeted tests.
3. Task graph validation rejects missing dependencies and cycles before provider work.
4. The Switchboard chooses a capable provider for each role capability.
5. The fanout governor bounds each runnable wave; the default is one task at a time.
6. Mutation budgets check file scope and reported added/deleted line counts.
7. The test ladder runs syntax checks and explicit targeted tests, classifying timeouts as unknown.
8. Security and product critics review provider mutation evidence.
9. The Evidence Arbiter issues the verified or rejected proof with immutable, content-addressed receipts.
10. Tracker plugins and the built-in Shards/Relay adapter receive a compact postflight checkpoint without source text.

Tracker integrations are injected through adapter interfaces or loaded from
deployment plugins. Set `NOUGENCODE_TRACKER_ADAPTER` to a Python
`module:factory` or `module:object` that provides `record_checkpoint(checkpoint)`.
Shards/Relay postflight uses the built-in adapter by default; set
`NOUGENCODE_POSTFLIGHT_ADAPTER` to override it with a Python `module:factory` or
`module:object` that provides `capture_checkpoint(checkpoint)`. The built-in
adapter calls the installed `nougen_shards` package, or resolves its source tree
from `NOUGEN_SHARDS_SOURCE`. It updates a Relay leg only when the runtime
identity includes `relay_leg_id`; the update stays `in_progress` until
independent evidence supports completion. Factories take no arguments and may
resolve credentials through the deployment's credential provider. Adapter
references contain no machine or tenant paths. A missing Shards package, Relay
directory, or active leg is reported in the proof rather than presented as a
successful capture.

## Directive dispatch receipts

`DirectiveOrchestrator` keeps routing separate from completion. With no
registered handler it records that no execution was attempted. Once a handler
runs, the receipt records the attempt but remains provisional unless the
handler supplies `completed=True`, `verification_passed=True`, a non-empty
`verification_method`, and non-empty `evidence_refs`. Accepted, queued,
dispatched, running, pending, failed, or unknown statuses cannot close the
directive. If common diagnostic or credential fields are removed from handler
evidence, the receipt stays provisional; exception text is never copied into
the receipt. These checks validate the shape of proof, not its authenticity:
adapters must provide evidence from a genuine verification step. The receipt
hash binds the plan hash, directive type, success verdict, and canonical JSON
evidence, so nested map ordering, verdict edits, or plan substitution cannot
silently reuse a receipt.
Receipt evidence is deeply immutable in memory; call `DirectiveReceipt.to_dict()`
to obtain a detached JSON-compatible copy for storage or transport, then use
`DirectiveReceipt.verify_exported_dict()` to check it after transport.

## Dynamic context paths

The NOUGEN_CONTEXT_DIR environment variable can select a context store. Otherwise
the Context Gate resolves the current user's home directory at runtime and uses its
NouGen context folder. NouGenCode does not embed a tenant, account, user folder,
machine, or repository path.

## Repository analysis CLI

The existing scanner CLI remains available:

    nougencode
    nougencode ./path/to/project
    nougencode ./scripts/worker.py
    nougencode --json
    nougencode --save-shard
    nougencode --no-deps
    nougencode --no-orphans
    nougencode --no-ast

## Scheduler capability profiles

The versioned JSON Schema at `src/nougencode/schemas/scheduler-capability-profile.schema.json`
defines a portable, time-bounded measurement snapshot for a dynamically discovered
worker. It is evidence consumed by the existing capability graph, not a second
registry. Every measured or unknown claim carries its observation time, source, and
freshness TTL. Devices remain separate entries so schedulers never add VRAM across
workers as if it were contiguous. An unknown workload stays `UNKNOWN`; stale evidence
also resolves to `UNKNOWN` at evaluation time.

Validate and resolve a profile before a scheduler consumes it:

    nougencode capability-profile validate profile.json
    nougencode capability-profile validate profile.json --as-of 2026-09-29T16:00:00Z

The second form makes freshness evaluation reproducible. The validator prints a
machine-readable summary and exits with status 2 for invalid JSON or contract errors.
The benchmark runner should write a new observation for each workload and source
probe, then pass the completed profile through this command before Relay/Shard
postflight. This keeps measurement, freshness resolution, and persistence as distinct
steps so unattended runs can stop safely on missing evidence.

The evidence-first control-plane request and result envelopes are described in
`src/nougencode/schemas/control-plane-golden-slice.schema.json`. An unattended runner
can assess a versioned request with:

    nougencode golden-slice request.json

Each request carries an explicit task capability, mutation budget, expected evidence
sources, and timestamp. The command checks source coverage and evidence TTLs, plans
through the existing `Capability` graph, and emits a content-addressed proof receipt.
Missing, stale, conflicting, or timed-out evidence yields an unknown decision; the
command does not start a provider or persist a checkpoint itself.

## Development

Install the package in editable mode, then run focused tests with the source tree
available on PYTHONPATH:

    python -m pip install -e .
    PYTHONPATH=src python -m pytest tests/test_nougencode_control_plane.py
