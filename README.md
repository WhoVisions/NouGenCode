# NouGenCode

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
10. Optional Tracker and Shards/Relay adapters receive a compact postflight checkpoint without source text.

Tracker and Shards/Relay integrations are injected through adapter interfaces or
loaded from deployment plugins. Set `NOUGENCODE_TRACKER_ADAPTER` to a Python
`module:factory` or `module:object` that provides `record_checkpoint(checkpoint)`.
Set `NOUGENCODE_POSTFLIGHT_ADAPTER` to one that provides
`capture_checkpoint(checkpoint)`. Factories take no arguments; they can resolve
their own credentials through the deployment's credential provider. Adapter
references contain no machine or tenant paths. If a setting is absent, the proof
reports that integration as not configured; if a configured plugin cannot load,
controller construction fails with the configuration error instead of silently
claiming a receipt was published.

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
