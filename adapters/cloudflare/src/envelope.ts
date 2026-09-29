import { canonicalJson, canonicalSha256, normalizeTimestamp } from "./canonical";

/** Matches `ENVELOPE_SCHEMA_VERSION` in nougencode.core.golden_slice. */
export const ENVELOPE_SCHEMA_VERSION = "1.0.0";

export interface EventBody {
  schema_version: string;
  mission_id: string;
  sequence: number;
  event_type: string;
  observed_at: string;
  source_id: string;
  payload: Record<string, unknown>;
}

/** Wire form: the body plus its content-addressed id. */
export interface EventEnvelope extends EventBody {
  event_id: string;
}

export class EnvelopeError extends Error {
  override readonly name = "EnvelopeError";
}

function requireText(value: unknown, field: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new EnvelopeError(`${field} is required`);
  }
  return value;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/**
 * Validate an untrusted body exactly as `EventEnvelope.__post_init__` does and
 * return it normalised (timestamp to canonical UTC). Throws `EnvelopeError`.
 */
export function normalizeBody(input: unknown): EventBody {
  if (!isPlainObject(input)) throw new EnvelopeError("envelope must be an object");
  const schemaVersion = input.schema_version ?? ENVELOPE_SCHEMA_VERSION;
  if (schemaVersion !== ENVELOPE_SCHEMA_VERSION) {
    throw new EnvelopeError(`unsupported envelope schema version: ${String(schemaVersion)}`);
  }
  const sequence = input.sequence;
  if (typeof sequence !== "number" || !Number.isInteger(sequence) || sequence < 0) {
    throw new EnvelopeError("sequence must be a non-negative integer");
  }
  if (!isPlainObject(input.payload)) throw new EnvelopeError("payload must be an object");
  let observedAt: string;
  try {
    observedAt = normalizeTimestamp(requireText(input.observed_at, "observed_at"));
  } catch (error) {
    if (error instanceof EnvelopeError) throw error;
    throw new EnvelopeError((error as Error).message);
  }
  const body: EventBody = {
    schema_version: ENVELOPE_SCHEMA_VERSION,
    mission_id: requireText(input.mission_id, "mission_id"),
    sequence,
    event_type: requireText(input.event_type, "event_type"),
    observed_at: observedAt,
    source_id: requireText(input.source_id, "source_id"),
    payload: input.payload,
  };
  try {
    canonicalJson(body.payload);
  } catch (error) {
    throw new EnvelopeError(`payload is not canonical JSON: ${(error as Error).message}`);
  }
  return body;
}

export async function buildEnvelope(input: unknown): Promise<EventEnvelope> {
  const body = normalizeBody(input);
  return { event_id: await canonicalSha256(body), ...body };
}

/**
 * Verify an inbound envelope: normalise it and require its `event_id` to equal
 * the hash of its own content, so a tampered or mislabelled event is refused
 * instead of deduplicated under a false identity.
 */
export async function verifyEnvelope(input: unknown): Promise<EventEnvelope> {
  if (!isPlainObject(input)) throw new EnvelopeError("envelope must be an object");
  const claimed = requireText(input.event_id, "event_id");
  const envelope = await buildEnvelope(input);
  if (envelope.event_id !== claimed) {
    throw new EnvelopeError("event_id does not match envelope content");
  }
  return envelope;
}
