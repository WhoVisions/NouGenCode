# NouGenCode Cloudflare adapter stack

The deployable edge counterpart to the Python control-plane kernel
(`src/nougencode/core/`). The Python side defines the rules; this package
enforces them on Cloudflare with the same bytes on the wire.

```
Producer ─► Queue (nougen-code-ingest) ─► queue() consumer
                 │  max_retries exhausted            │ per message
                 ▼                                   ▼
        DLQ (nougen-code-ingest-dlq) ◄── poison   TenantCoordinator (Durable Object, one per tenant)
                                                     │  ingest(): record once per event_id
                                                     ▼
                                          IngestWorkflow (durable steps)
                                            lease-and-apply ─► receipt
```

| Piece | File | Job |
|---|---|---|
| Canonical JSON v1 | `src/canonical.ts` | Byte-identical to `nougencode.canonical`; runs the shared vectors in `tests/fixtures/canonical-json-v1.json` |
| Envelope | `src/envelope.ts` | Same validation and `event_id` (SHA-256 of canonical body) as Python `EventEnvelope`; pinned against Python-computed ids |
| Coordinator | `src/coordinator.ts` | SQLite-backed Durable Object: lease + monotonic fence issuer, idempotency-keyed fenced mutations, dedup'd event ingest |
| Queue ingress | `src/queue.ts` | At-least-once safe consumer: ack / retry with backoff / dead-letter poison |
| Workflow | `src/workflow.ts` | Durable "event processed" transition with retryable steps |

## Semantics

- **Fence.** Only `acquireLease` issues fences, and every grant bumps the epoch
  (the same holder renewing included). A mutation must carry the *current*
  epoch: older → `STALE_FENCE` (zombie), newer → `FUTURE_FENCE` (never issued),
  lapsed lease → `LEASE_EXPIRED`. Several mutations may share one epoch.
  This differs on purpose from the in-process `MutationLedger`, which has no
  issuer and so uses strict increase per mutation as a stand-in.
- **Idempotency.** Same key + same canonical content → no-op replay (checked
  *before* the fence, so a late retry of finished work is harmless). Same key +
  different content → `IDEMPOTENCY_CONFLICT`.
- **Ingest** is an observation, not a mutation: deduped by `event_id`, not fenced.
  A tampered envelope (`event_id` ≠ hash of content) is refused.
- **Results, not exceptions.** The coordinator returns `{ ok: false, code }`
  because error subclasses do not survive Durable Object RPC; the queue and
  workflow use the code to decide retry vs give up.

## Dead-lettering

Two paths into `nougen-code-ingest-dlq`:

1. **Poison** (bad shape, bad `tenant_id`, tampered/invalid envelope): written
   explicitly as `{ kind: "poison", reason, message_id, attempts, body }` and
   acked, so retries are not wasted. If that DLQ write fails the message is
   retried, never dropped.
2. **Exhausted retries** (`max_retries: 5` in `wrangler.jsonc`): moved by the
   platform with its original body.

The workflow is started on **every** delivery, duplicates included (instance id
= `event_id`), so a crash between "recorded" and "workflow started" cannot
strand an event.

## Develop

```bash
cd adapters/cloudflare
npm install
npm test          # wrangler types + vitest in the Workers runtime (59 tests)
npm run typecheck
```

`compatibility_date` must not be newer than the bundled `workerd`; if tests fail
at startup with "newest date supported by this server binary", lower it.
`worker-configuration.d.ts` is generated (`wrangler types`) and git-ignored.

Test note: the three tests that run the real Workflows engine print a
`code had hung` warning from workerd when the finished instance is torn down.
It is engine noise; the assertions after `waitForStatus("complete")` hold.

## Deploy (not done by CI; needs the Cloudflare account)

```bash
npx wrangler queues create nougen-code-ingest
npx wrangler queues create nougen-code-ingest-dlq
npx wrangler deploy
```
