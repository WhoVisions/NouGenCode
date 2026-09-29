import { WorkflowEntrypoint, type WorkflowEvent, type WorkflowStep } from "cloudflare:workers";
import { NonRetryableError } from "cloudflare:workflows";
import { canonicalSha256 } from "./canonical";
import type { EventEnvelope } from "./envelope";

export interface IngestParams {
  tenant_id: string;
  event: EventEnvelope;
  /** Identity taking the lease; defaults to the workflow instance. */
  node_id?: string;
}

export interface IngestOutcome {
  event_id: string;
  fence: number;
  applied: boolean;
  replay: boolean;
  receipt: string;
}

/** The slice of `WorkflowStep` this logic needs, so it can run under a fake step in tests. */
export interface StepRunner {
  do<T>(name: string, config: StepConfig, callback: () => Promise<T>): Promise<T>;
}

export interface StepConfig {
  retries?: { limit: number; delay: string | number; backoff?: "constant" | "linear" | "exponential" };
  timeout?: string | number;
}

const LEASE_TTL_MS = 30_000;

const RETRYABLE_REJECTIONS = new Set(["STALE_FENCE", "FUTURE_FENCE", "LEASE_EXPIRED"]);

/**
 * Durable "event processed" transition.
 *
 * Lease and mutation live in ONE step on purpose: a rejection caused by a
 * moved epoch or a lapsed lease is fixed by re-acquiring, and a step retry
 * re-runs the whole callback. The mutation key is derived from the event id, so
 * a retry of an already-applied mutation is a replay, never a second write.
 */
export async function runIngestWorkflow(
  env: Pick<Env, "TENANT">,
  params: IngestParams,
  instanceId: string,
  step: StepRunner,
): Promise<IngestOutcome> {
  const { tenant_id: tenantId, event } = params;
  const node = params.node_id ?? `workflow:${instanceId}`;

  const applied = await step.do(
    "lease-and-apply",
    { retries: { limit: 6, delay: "2 seconds", backoff: "exponential" }, timeout: "1 minute" },
    async () => {
      const coordinator = env.TENANT.getByName(tenantId);
      const lease = await coordinator.acquireLease(node, LEASE_TTL_MS);
      if (!lease.ok) throw new NonRetryableError(`${lease.code}: ${lease.message}`);
      if (!lease.acquired) throw new Error(`lease held by ${lease.owner ?? "another node"}; retrying`);

      const result = await coordinator.applyMutation({
        idempotency_key: `processed:${event.event_id}`,
        fence: lease.fence,
        mutation: { kind: "event.processed", event_id: event.event_id, mission_id: event.mission_id },
      });
      if (!result.ok) {
        if (RETRYABLE_REJECTIONS.has(result.code)) throw new Error(`${result.code}: ${result.message}`);
        throw new NonRetryableError(`${result.code}: ${result.message}`);
      }
      return { fence: result.fence, applied: result.applied, replay: result.replay };
    },
  );

  const receipt = await step.do("receipt", { retries: { limit: 3, delay: "1 second" } }, () =>
    canonicalSha256({
      kind: "nougen.ingest.receipt.v1",
      tenant_id: tenantId,
      event_id: event.event_id,
      fence: applied.fence,
      applied: applied.applied,
    }),
  );

  return { event_id: event.event_id, ...applied, receipt };
}

export class IngestWorkflow extends WorkflowEntrypoint<Env, IngestParams> {
  override async run(event: WorkflowEvent<IngestParams>, step: WorkflowStep): Promise<IngestOutcome> {
    return runIngestWorkflow(this.env, event.payload, event.instanceId, step);
  }
}
