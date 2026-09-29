import { EnvelopeError, verifyEnvelope, type EventEnvelope } from "./envelope";
import type { IngestParams } from "./workflow";

export interface IngestMessage {
  tenant_id: string;
  event: EventEnvelope;
}

/** Exponential retry delay in seconds: 5, 10, 20 ... capped at 5 minutes. */
export function retryDelaySeconds(attempts: number): number {
  const exponent = Math.max(0, Math.min(attempts - 1, 10));
  return Math.min(300, 5 * 2 ** exponent);
}

const TENANT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

class PoisonMessage extends Error {
  override readonly name = "PoisonMessage";
}

async function parse(body: unknown): Promise<IngestMessage> {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new PoisonMessage("message body must be an object");
  }
  const { tenant_id: tenantId, event } = body as Record<string, unknown>;
  if (typeof tenantId !== "string" || !TENANT_ID.test(tenantId)) {
    throw new PoisonMessage("tenant_id is missing or malformed");
  }
  try {
    return { tenant_id: tenantId, event: await verifyEnvelope(event) };
  } catch (error) {
    if (error instanceof EnvelopeError) throw new PoisonMessage(`bad envelope: ${error.message}`);
    throw error;
  }
}

type WorkflowBinding = Pick<Workflow<IngestParams>, "create" | "get">;

/** Workflow ids are unique, so creating by event id is idempotent; a second create is not an error. */
async function ensureWorkflow(workflow: WorkflowBinding, params: IngestParams): Promise<void> {
  try {
    await workflow.create({ id: params.event.event_id, params });
  } catch (createError) {
    try {
      await workflow.get(params.event.event_id);
    } catch {
      throw createError;
    }
  }
}

/**
 * Queue ingress. Delivery is at-least-once, so everything here is idempotent.
 *
 * - malformed / tampered messages are *poison*: retrying cannot fix them, so
 *   they go straight to the DLQ with a reason and are acked (never dropped: if
 *   the DLQ write fails the message is retried instead);
 * - transient failures retry with exponential backoff; once `max_retries` in
 *   wrangler.jsonc is exhausted the platform moves the message to the same DLQ;
 * - the workflow is started on every delivery (duplicates included) so an event
 *   recorded before a crash still gets processed.
 */
export async function handleIngestBatch(
  batch: MessageBatch<unknown>,
  env: Pick<Env, "TENANT" | "DLQ" | "INGEST_WORKFLOW">,
): Promise<void> {
  for (const message of batch.messages) {
    try {
      const { tenant_id: tenantId, event } = await parse(message.body);
      const stored = await env.TENANT.getByName(tenantId).ingest(event);
      if (!stored.ok) {
        if (stored.code === "BAD_ENVELOPE") throw new PoisonMessage(stored.message);
        throw new Error(`${stored.code}: ${stored.message}`);
      }
      await ensureWorkflow(env.INGEST_WORKFLOW, { tenant_id: tenantId, event });
      message.ack();
    } catch (error) {
      if (error instanceof PoisonMessage) {
        try {
          await env.DLQ.send({
            kind: "poison",
            reason: error.message,
            message_id: message.id,
            attempts: message.attempts,
            received_at: new Date().toISOString(),
            body: message.body,
          });
          message.ack();
        } catch {
          message.retry({ delaySeconds: retryDelaySeconds(message.attempts) });
        }
        continue;
      }
      message.retry({ delaySeconds: retryDelaySeconds(message.attempts) });
    }
  }
}
