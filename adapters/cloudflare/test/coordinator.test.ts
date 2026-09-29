import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { buildEnvelope } from "../src/envelope";

const coordinator = (tenant: string) => env.TENANT.getByName(tenant);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function lease(tenant: string, node = "node-a", ttlMs = 30_000) {
  const result = await coordinator(tenant).acquireLease(node, ttlMs);
  if (!result.ok || !result.acquired) throw new Error(`lease not acquired: ${JSON.stringify(result)}`);
  return result.fence;
}

describe("TenantCoordinator lease + fence", () => {
  it("issues a strictly increasing fence on every grant", async () => {
    const t = "fence-monotonic";
    expect(await lease(t, "a")).toBe(1);
    expect(await lease(t, "a")).toBe(2); // same owner renewing still bumps the epoch
    expect(await lease(t, "a")).toBe(3);
  });

  it("refuses a second node while the lease is live, and reports the holder", async () => {
    const t = "lease-held";
    const fence = await lease(t, "a");
    const other = await coordinator(t).acquireLease("b", 30_000);
    expect(other).toMatchObject({ ok: true, acquired: false, fence, owner: "a" });
  });

  it("lets another node take over after expiry, with a newer fence", async () => {
    const t = "lease-expiry";
    const first = await lease(t, "a", 20);
    await sleep(60);
    const second = await lease(t, "b", 30_000);
    expect(second).toBeGreaterThan(first);
  });

  it.each([
    ["blank node", "  ", 1000],
    ["zero ttl", "a", 0],
    ["negative ttl", "a", -5],
    ["NaN ttl", "a", Number.NaN],
    ["ttl over the cap", "a", 3_600_001],
  ])("rejects bad lease request: %s", async (_name, node, ttl) => {
    const result = await coordinator("lease-bad").acquireLease(node, ttl);
    expect(result).toMatchObject({ ok: false, code: "BAD_REQUEST" });
  });
});

describe("TenantCoordinator.applyMutation", () => {
  it("applies once, and replays an identical retry as a no-op", async () => {
    const t = "mut-idempotent";
    const fence = await lease(t);
    const request = { idempotency_key: "k1", fence, mutation: { file: "a.py", lines: 3 } };
    expect(await coordinator(t).applyMutation(request)).toEqual({ ok: true, applied: true, replay: false, fence });
    expect(await coordinator(t).applyMutation(request)).toEqual({ ok: true, applied: false, replay: true, fence });
    expect((await coordinator(t).getState()).mutations).toBe(1);
  });

  it("treats key order inside the mutation as the same content", async () => {
    const t = "mut-canonical";
    const fence = await lease(t);
    await coordinator(t).applyMutation({ idempotency_key: "k", fence, mutation: { a: 1, b: 2 } });
    const again = await coordinator(t).applyMutation({ idempotency_key: "k", fence, mutation: { b: 2, a: 1 } });
    expect(again).toMatchObject({ ok: true, applied: false, replay: true });
  });

  it("rejects reusing a key for different content", async () => {
    const t = "mut-conflict";
    const fence = await lease(t);
    await coordinator(t).applyMutation({ idempotency_key: "k", fence, mutation: { v: 1 } });
    const conflict = await coordinator(t).applyMutation({ idempotency_key: "k", fence, mutation: { v: 2 } });
    expect(conflict).toMatchObject({ ok: false, code: "IDEMPOTENCY_CONFLICT" });
  });

  it("allows several distinct mutations within one epoch", async () => {
    const t = "mut-same-epoch";
    const fence = await lease(t);
    for (const key of ["k1", "k2", "k3"]) {
      expect(await coordinator(t).applyMutation({ idempotency_key: key, fence, mutation: { key } })).toMatchObject({
        ok: true,
        applied: true,
      });
    }
    expect((await coordinator(t).getState()).mutations).toBe(3);
  });

  it("refuses a zombie: an older fence after the epoch moved on", async () => {
    const t = "mut-zombie";
    const old = await lease(t, "a", 20);
    await sleep(60);
    const current = await lease(t, "b");
    expect(current).toBeGreaterThan(old);
    const stale = await coordinator(t).applyMutation({ idempotency_key: "z", fence: old, mutation: { v: 1 } });
    expect(stale).toEqual({
      ok: false,
      code: "STALE_FENCE",
      message: "mutation fence is older than the current epoch",
      fence: current,
    });
    expect((await coordinator(t).getState()).mutations).toBe(0);
  });

  it("refuses a fence this coordinator never issued", async () => {
    const t = "mut-future";
    const fence = await lease(t);
    const result = await coordinator(t).applyMutation({ idempotency_key: "f", fence: fence + 5, mutation: {} });
    expect(result).toMatchObject({ ok: false, code: "FUTURE_FENCE", fence });
  });

  it("refuses to mutate once the lease has lapsed, even at the current epoch", async () => {
    const t = "mut-lapsed";
    const fence = await lease(t, "a", 20);
    await sleep(60);
    const result = await coordinator(t).applyMutation({ idempotency_key: "l", fence, mutation: {} });
    expect(result).toMatchObject({ ok: false, code: "LEASE_EXPIRED", fence });
  });

  it("still replays an already-applied mutation after the epoch moved on", async () => {
    const t = "mut-replay-late";
    const first = await lease(t, "a", 20);
    const request = { idempotency_key: "done", fence: first, mutation: { v: 1 } };
    await coordinator(t).applyMutation(request);
    await sleep(60);
    await lease(t, "b");
    expect(await coordinator(t).applyMutation(request)).toMatchObject({ ok: true, applied: false, replay: true });
  });

  it.each([
    ["blank key", { idempotency_key: " ", fence: 1, mutation: {} }],
    ["zero fence", { idempotency_key: "k", fence: 0, mutation: {} }],
    ["fractional fence", { idempotency_key: "k", fence: 1.5, mutation: {} }],
    ["array mutation", { idempotency_key: "k", fence: 1, mutation: [] }],
    ["non-canonical mutation", { idempotency_key: "k", fence: 1, mutation: { x: Number.NaN } }],
  ])("rejects malformed request: %s", async (_name, request) => {
    const result = await coordinator("mut-bad").applyMutation(request as never);
    expect(result).toMatchObject({ ok: false, code: "BAD_REQUEST" });
  });

  it("keeps tenants isolated: fences and mutations do not cross", async () => {
    const a = await lease("tenant-a");
    const b = await lease("tenant-b");
    expect(a).toBe(1);
    expect(b).toBe(1);
    await coordinator("tenant-a").applyMutation({ idempotency_key: "k", fence: a, mutation: { v: 1 } });
    expect((await coordinator("tenant-b").getState()).mutations).toBe(0);
  });
});

describe("TenantCoordinator.ingest", () => {
  const raw = {
    mission_id: "m1",
    sequence: 1,
    event_type: "probe",
    observed_at: "2026-09-29T17:00:00Z",
    source_id: "s",
    payload: { a: 1 },
  };

  it("records once per event_id and reports duplicates", async () => {
    const event = await buildEnvelope(raw);
    const t = "ingest-dedupe";
    expect(await coordinator(t).ingest(event)).toEqual({ ok: true, duplicate: false, event_id: event.event_id });
    expect(await coordinator(t).ingest(event)).toEqual({ ok: true, duplicate: true, event_id: event.event_id });
    expect((await coordinator(t).getState()).events).toBe(1);
  });

  it("refuses a tampered envelope and stores nothing", async () => {
    const event = await buildEnvelope(raw);
    const t = "ingest-tamper";
    const result = await coordinator(t).ingest({ ...event, sequence: 2 });
    expect(result).toMatchObject({ ok: false, code: "BAD_ENVELOPE" });
    expect((await coordinator(t).getState()).events).toBe(0);
  });

  it("persists across eviction of the Durable Object instance", async () => {
    const t = "ingest-durable";
    const fence = await lease(t);
    await coordinator(t).applyMutation({ idempotency_key: "k", fence, mutation: { v: 1 } });
    // A brand-new stub for the same name reads the same SQLite-backed state.
    const state = await env.TENANT.getByName(t).getState();
    expect(state).toMatchObject({ fence, owner: "node-a", mutations: 1 });
  });
});
