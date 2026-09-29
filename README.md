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

Tracker and Shards/Relay integrations are injected through adapter interfaces. If no
adapter is configured, the proof reports that status as not configured; it does
not claim a receipt was published.

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

## Development

Install the package in editable mode, then run focused tests with the source tree
available on PYTHONPATH:

    python -m pip install -e .
    PYTHONPATH=src python -m pytest tests/test_nougencode_control_plane.py
