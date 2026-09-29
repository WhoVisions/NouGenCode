import { DurableObject } from "cloudflare:workers";
import { canonicalJson, sha256Hex } from "./canonical";
import { EnvelopeError, verifyEnvelope } from "./envelope";

/** A lease longer than this is almost certainly a bug; the Python default is 60 s. */
export const MAX_LEASE_TTL_MS = 3_600_000;

export type Rejection =
  | "BAD_REQUEST"
  | "BAD_ENVELOPE"
  | "STALE_FENCE"
  | "FUTURE_FENCE"
  | "LEASE_EXPIRED"
  | "IDEMPOTENCY_CONFLICT";

export interface Rejected {
  ok: false;
  code: Rejection;
  message: string;
  /** Current epoch, when the rejection is about the fence. */
  fence?: number;
}

export type LeaseResult =
  | { ok: true; acquired: boolean; fence: number; owner: string | null; lease_until_ms: number }
  | Rejected;

export type MutationResult =
  | { ok: true; applied: boolean; replay: boolean; fence: number }
  | Rejected;

export type IngestResult = { ok: true; duplicate: boolean; event_id: string } | Rejected;

export interface MutationRequest {
  idempotency_key: string;
  fence: number;
  mutation: Record<string, unknown>;
}

export interface CoordinatorState {
  fence: number;
  owner: string | null;
  lease_until_ms: number;
  mutations: number;
  events: number;
}

const reject = (code: Rejection, message: string, fence?: number): Rejected =>
  fence === undefined ? { ok: false, code, message } : { ok: false, code, message, fence };

/**
 * One instance per tenant (`env.TENANT.getByName(tenantId)`): the single
 * serialisation point for that tenant's writes.
 *
 * Fencing: `acquireLease` is the only thing that issues fences, and it bumps
 * the epoch on every grant. A mutation must carry the *current* epoch, so a
 * zombie holder (superseded, or lease lapsed) is refused. Mutations are
 * idempotency-keyed: same key + same content is a no-op replay, same key +
 * different content is a conflict. Compare `MutationLedger` in
 * `nougencode.core.golden_slice`, which has no issuer and therefore uses
 * strict-increase as its stand-in; here the DO is the issuer, so several
 * mutations may share one epoch.
 *
 * Every method computes its hashes *before* touching storage and then runs one
 * synchronous transaction, so no `await` can interleave between related writes.
 */
export class TenantCoordinator extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    void ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec(
        `CREATE TABLE IF NOT EXISTS lease (
           id INTEGER PRIMARY KEY CHECK (id = 1),
           fence INTEGER NOT NULL,
           owner TEXT,
           lease_until_ms INTEGER NOT NULL
         )`,
      );
      ctx.storage.sql.exec("INSERT OR IGNORE INTO lease (id, fence, owner, lease_until_ms) VALUES (1, 0, NULL, 0)");
      ctx.storage.sql.exec(
        `CREATE TABLE IF NOT EXISTS mutations (
           idempotency_key TEXT PRIMARY KEY,
           digest TEXT NOT NULL,
           fence INTEGER NOT NULL,
           applied_at_ms INTEGER NOT NULL
         )`,
      );
      ctx.storage.sql.exec(
        `CREATE TABLE IF NOT EXISTS events (
           event_id TEXT PRIMARY KEY,
           mission_id TEXT NOT NULL,
           sequence INTEGER NOT NULL,
           received_at_ms INTEGER NOT NULL,
           body_json TEXT NOT NULL
         )`,
      );
    });
  }

  private readLease(): { fence: number; owner: string | null; lease_until_ms: number } {
    return this.ctx.storage.sql
      .exec<{ fence: number; owner: string | null; lease_until_ms: number }>(
        "SELECT fence, owner, lease_until_ms FROM lease WHERE id = 1",
      )
      .one();
  }

  async acquireLease(node: string, ttlMs: number): Promise<LeaseResult> {
    if (typeof node !== "string" || node.trim() === "") {
      return reject("BAD_REQUEST", "node must be a non-empty string");
    }
    if (typeof ttlMs !== "number" || !Number.isFinite(ttlMs) || ttlMs <= 0 || ttlMs > MAX_LEASE_TTL_MS) {
      return reject("BAD_REQUEST", `ttlMs must be a positive number up to ${MAX_LEASE_TTL_MS}`);
    }
    return this.ctx.storage.transactionSync((): LeaseResult => {
      const now = Date.now();
      const lease = this.readLease();
      if (lease.lease_until_ms > now && lease.owner !== node) {
        return { ok: true, acquired: false, fence: lease.fence, owner: lease.owner, lease_until_ms: lease.lease_until_ms };
      }
      const fence = lease.fence + 1;
      const leaseUntil = now + Math.floor(ttlMs);
      this.ctx.storage.sql.exec(
        "UPDATE lease SET fence = ?, owner = ?, lease_until_ms = ? WHERE id = 1",
        fence,
        node,
        leaseUntil,
      );
      return { ok: true, acquired: true, fence, owner: node, lease_until_ms: leaseUntil };
    });
  }

  async applyMutation(request: MutationRequest): Promise<MutationResult> {
    if (typeof request !== "object" || request === null) return reject("BAD_REQUEST", "request must be an object");
    const { idempotency_key: key, fence, mutation } = request;
    if (typeof key !== "string" || key.trim() === "") {
      return reject("BAD_REQUEST", "idempotency_key is required");
    }
    if (typeof fence !== "number" || !Number.isInteger(fence) || fence <= 0) {
      return reject("BAD_REQUEST", "fence must be a positive integer");
    }
    let digest: string;
    try {
      if (typeof mutation !== "object" || mutation === null || Array.isArray(mutation)) {
        return reject("BAD_REQUEST", "mutation must be an object");
      }
      digest = await sha256Hex(canonicalJson(mutation));
    } catch (error) {
      return reject("BAD_REQUEST", `mutation is not canonical JSON: ${(error as Error).message}`);
    }

    return this.ctx.storage.transactionSync((): MutationResult => {
      const prior = this.ctx.storage.sql
        .exec<{ digest: string; fence: number }>(
          "SELECT digest, fence FROM mutations WHERE idempotency_key = ?",
          key,
        )
        .toArray()[0];
      // A retry of something already applied is a no-op even after the epoch
      // moved on; only *new* work is fenced.
      if (prior) {
        return prior.digest === digest
          ? { ok: true, applied: false, replay: true, fence: prior.fence }
          : reject("IDEMPOTENCY_CONFLICT", "idempotency key was reused for different mutation content");
      }
      const now = Date.now();
      const lease = this.readLease();
      if (fence < lease.fence) {
        return reject("STALE_FENCE", "mutation fence is older than the current epoch", lease.fence);
      }
      if (fence > lease.fence) {
        return reject("FUTURE_FENCE", "mutation fence was never issued by this coordinator", lease.fence);
      }
      if (lease.lease_until_ms <= now) {
        return reject("LEASE_EXPIRED", "lease lapsed; re-acquire before mutating", lease.fence);
      }
      this.ctx.storage.sql.exec(
        "INSERT INTO mutations (idempotency_key, digest, fence, applied_at_ms) VALUES (?, ?, ?, ?)",
        key,
        digest,
        fence,
        now,
      );
      return { ok: true, applied: true, replay: false, fence };
    });
  }

  /** Record an observation once per `event_id`. Ingest is not a fenced mutation. */
  async ingest(event: unknown): Promise<IngestResult> {
    let envelope;
    try {
      envelope = await verifyEnvelope(event);
    } catch (error) {
      if (error instanceof EnvelopeError) return reject("BAD_ENVELOPE", error.message);
      throw error;
    }
    return this.ctx.storage.transactionSync((): IngestResult => {
      const seen = this.ctx.storage.sql
        .exec("SELECT 1 FROM events WHERE event_id = ?", envelope.event_id)
        .toArray().length;
      if (seen > 0) return { ok: true, duplicate: true, event_id: envelope.event_id };
      this.ctx.storage.sql.exec(
        "INSERT INTO events (event_id, mission_id, sequence, received_at_ms, body_json) VALUES (?, ?, ?, ?, ?)",
        envelope.event_id,
        envelope.mission_id,
        envelope.sequence,
        Date.now(),
        canonicalJson(envelope),
      );
      return { ok: true, duplicate: false, event_id: envelope.event_id };
    });
  }

  async getState(): Promise<CoordinatorState> {
    const lease = this.readLease();
    const count = (table: "mutations" | "events") =>
      this.ctx.storage.sql.exec<{ n: number }>(`SELECT COUNT(*) AS n FROM ${table}`).one().n;
    return { ...lease, mutations: count("mutations"), events: count("events") };
  }
}
