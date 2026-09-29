import { env, introspectWorkflowInstance } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { buildEnvelope } from "../src/envelope";
import { runIngestWorkflow, type StepRunner } from "../src/workflow";

const raw = (sequence: number) => ({
  mission_id: "m-wf",
  sequence,
  event_type: "probe",
  observed_at: "2026-09-29T17:00:00Z",
  source_id: "s",
  payload: {},
});

/** Runs each step once, in-process, recording names: the logic without the engine. */
const inlineStep = (): StepRunner & { names: string[] } => {
  const names: string[] = [];
  return { names, do: async (name, _config, callback) => (names.push(name), callback()) };
};

describe("runIngestWorkflow (logic)", () => {
  it("leases, applies the processed mutation once, and returns a stable receipt", async () => {
    const event = await buildEnvelope(raw(1));
    const step = inlineStep();
    const params = { tenant_id: "wf-logic", event, node_id: "wf-node" };

    const first = await runIngestWorkflow(env, params, "inst-1", step);
    expect(step.names).toEqual(["lease-and-apply", "receipt"]);
    expect(first).toMatchObject({ event_id: event.event_id, fence: 1, applied: true, replay: false });
    expect(first.receipt).toMatch(/^[0-9a-f]{64}$/);

    // Re-running the whole workflow (engine replay after a crash) must not write twice.
    const second = await runIngestWorkflow(env, params, "inst-1", inlineStep());
    expect(second).toMatchObject({ event_id: event.event_id, applied: false, replay: true });
    expect((await env.TENANT.getByName("wf-logic").getState()).mutations).toBe(1);
  });

  it("throws a retryable error when another node holds the lease", async () => {
    const event = await buildEnvelope(raw(2));
    await env.TENANT.getByName("wf-held").acquireLease("someone-else", 30_000);
    await expect(
      runIngestWorkflow(env, { tenant_id: "wf-held", event, node_id: "me" }, "inst-2", inlineStep()),
    ).rejects.toThrow(/lease held by someone-else/);
  });
});

describe("IngestWorkflow (engine)", () => {
  it("runs to completion through the real Workflows engine", async () => {
    const event = await buildEnvelope(raw(3));
    await using instance = await introspectWorkflowInstance(env.INGEST_WORKFLOW, event.event_id);
    await env.INGEST_WORKFLOW.create({ id: event.event_id, params: { tenant_id: "wf-engine", event } });
    await instance.waitForStatus("complete");
    const output = (await instance.getOutput()) as { event_id: string; applied: boolean };
    expect(output).toMatchObject({ event_id: event.event_id, applied: true });
    expect((await env.TENANT.getByName("wf-engine").getState()).mutations).toBe(1);
  });
});
