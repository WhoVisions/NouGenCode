import { createExecutionContext, createMessageBatch, env, getQueueResult, introspectWorkflowInstance } from "cloudflare:test";
import { describe, expect, it, vi } from "vitest";
import { buildEnvelope } from "../src/envelope";
import worker from "../src/index";
import { retryDelaySeconds } from "../src/queue";

const raw = (sequence: number) => ({
  mission_id: "m1",
  sequence,
  event_type: "probe",
  observed_at: "2026-09-29T17:00:00Z",
  source_id: "s",
  payload: { sequence },
});

async function deliver(bodies: unknown[], overrides: Partial<Env> = {}) {
  const batch = createMessageBatch(
    "nougen-code-ingest",
    bodies.map((body, i) => ({ id: `msg-${i}`, timestamp: new Date(), attempts: 1, body })),
  );
  const ctx = createExecutionContext();
  await worker.queue(batch, { ...env, ...overrides } as Env, ctx);
  return getQueueResult(batch, ctx);
}

/** A DLQ binding stand-in that records what was sent to it. */
const fakeDlq = () => {
  const send = vi.fn(async () => undefined);
  return { send, binding: { send } as unknown as Queue };
};

describe("queue ingress", () => {
  it("acks a valid event, records it once, and starts its workflow", async () => {
    const event = await buildEnvelope(raw(1));
    const tenant = "q-happy";
    await using instance = await introspectWorkflowInstance(env.INGEST_WORKFLOW, event.event_id);
    const result = await deliver([{ tenant_id: tenant, event }]);
    expect(result.explicitAcks).toEqual(["msg-0"]);
    expect(result.retryMessages).toEqual([]);
    expect((await env.TENANT.getByName(tenant).getState()).events).toBe(1);
    await instance.waitForStatus("complete");
    expect((await env.TENANT.getByName(tenant).getState()).mutations).toBe(1);
  });

  it("is idempotent under redelivery: no duplicate row, no second workflow, still acked", async () => {
    const event = await buildEnvelope(raw(2));
    const tenant = "q-redeliver";
    const message = { tenant_id: tenant, event };
    await using instance = await introspectWorkflowInstance(env.INGEST_WORKFLOW, event.event_id);
    await deliver([message]);
    const again = await deliver([message]); // workflow id already exists: must not fail the message
    expect(again.explicitAcks).toEqual(["msg-0"]);
    await instance.waitForStatus("complete");
    const state = await env.TENANT.getByName(tenant).getState();
    expect(state).toMatchObject({ events: 1, mutations: 1 });
  });

  it("dead-letters poison messages with a reason instead of burning retries", async () => {
    const dlq = fakeDlq();
    const good = await buildEnvelope(raw(3));
    const result = await deliver(
      [
        "not an object",
        { tenant_id: "bad tenant!", event: good },
        { tenant_id: "q-poison", event: { ...good, sequence: 99 } }, // hash mismatch = tampered
        { tenant_id: "q-poison", event: { mission_id: "" } },
      ],
      { DLQ: dlq.binding },
    );
    expect(result.explicitAcks).toEqual(["msg-0", "msg-1", "msg-2", "msg-3"]);
    expect(result.retryMessages).toEqual([]);
    expect(dlq.send).toHaveBeenCalledTimes(4);
    const sent = dlq.send.mock.calls.map((call) => (call as unknown[])[0] as Record<string, unknown>);
    expect(sent.every((entry) => entry.kind === "poison" && typeof entry.reason === "string")).toBe(true);
    expect(sent[2]?.reason).toMatch(/does not match envelope content/);
    expect((await env.TENANT.getByName("q-poison").getState()).events).toBe(0);
  });

  it("never drops a poison message: if the DLQ write fails it is retried, not acked", async () => {
    const failing = { send: vi.fn(async () => { throw new Error("dlq down"); }) } as unknown as Queue;
    const result = await deliver(["garbage"], { DLQ: failing });
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((m: { msgId: string }) => m.msgId)).toEqual(["msg-0"]);
  });

  it("retries transient failures with backoff and does not ack", async () => {
    const event = await buildEnvelope(raw(4));
    const broken = {
      getByName: () => ({ ingest: async () => { throw new Error("coordinator unavailable"); } }),
    } as unknown as Env["TENANT"];
    const result = await deliver([{ tenant_id: "q-transient", event }], { TENANT: broken });
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((m: { msgId: string }) => m.msgId)).toEqual(["msg-0"]);
  });

  it("passes an escalating delay to retry() as attempts grow", async () => {
    // The Workers test harness reports *that* a message was retried but not its
    // delay, so drive the handler with plain message objects to observe it.
    const event = await buildEnvelope(raw(6));
    const broken = {
      getByName: () => ({ ingest: async () => { throw new Error("coordinator unavailable"); } }),
    } as unknown as Env["TENANT"];
    const delays: number[] = [];
    const messages = [1, 3, 9].map((attempts) => ({
      id: `m${attempts}`,
      attempts,
      body: { tenant_id: "q-delay", event },
      ack: vi.fn(),
      retry: (options?: { delaySeconds?: number }) => void delays.push(options?.delaySeconds ?? -1),
    }));
    const { handleIngestBatch } = await import("../src/queue");
    await handleIngestBatch({ messages } as unknown as MessageBatch<unknown>, { ...env, TENANT: broken });
    expect(delays).toEqual([5, 20, 300]);
    expect(messages.every((m) => m.ack.mock.calls.length === 0)).toBe(true);
  });

  it("processes a mixed batch independently", async () => {
    const dlq = fakeDlq();
    const event = await buildEnvelope(raw(5));
    await using instance = await introspectWorkflowInstance(env.INGEST_WORKFLOW, event.event_id);
    const result = await deliver([{ tenant_id: "q-mixed", event }, 42], { DLQ: dlq.binding });
    expect(result.explicitAcks).toEqual(["msg-0", "msg-1"]);
    expect(dlq.send).toHaveBeenCalledTimes(1);
    await instance.waitForStatus("complete");
  });
});

describe("retryDelaySeconds", () => {
  it("backs off exponentially and caps at five minutes", () => {
    expect([1, 2, 3, 4].map(retryDelaySeconds)).toEqual([5, 10, 20, 40]);
    expect(retryDelaySeconds(50)).toBe(300);
    expect(retryDelaySeconds(0)).toBe(5);
  });
});

describe("http surface", () => {
  it("answers /health and 404s everything else", async () => {
    const health = await worker.fetch(new Request("https://x/health"), env, createExecutionContext());
    expect(await health.json()).toEqual({ ok: true, service: "nougen-code-ingest" });
    const missing = await worker.fetch(new Request("https://x/nope"), env, createExecutionContext());
    expect(missing.status).toBe(404);
  });
});
