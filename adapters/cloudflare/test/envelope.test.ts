import { describe, expect, it } from "vitest";
import { buildEnvelope, EnvelopeError, verifyEnvelope } from "../src/envelope";

// Reference ids computed by the Python kernel (nougencode.core.golden_slice.EventEnvelope).
const PYTHON_EVENT_ID_MINIMAL = "15d8c55987a346d1bdd15f2c009c992d20a7fff0d522d474edab348f3d18619a";
const PYTHON_EVENT_ID_RICH = "f744647eb7ebb25feaf880074a5e0a19125b6c2d993863bf7cfd632634717aab";

const minimal = {
  mission_id: "mission",
  sequence: 1,
  event_type: "probe",
  observed_at: "2026-09-29T17:00:00Z",
  source_id: "source",
  payload: {},
};

const rich = {
  mission_id: "m-é",
  sequence: 7,
  event_type: "ev.type",
  observed_at: "2026-09-29T13:00:01.000020-04:00",
  source_id: "src/β",
  payload: { z: -0, b: 1e-7, n: [1, 2.5, null, true], t: "café" },
};

describe("EventEnvelope parity with Python", () => {
  it("derives the same event_id for a minimal envelope", async () => {
    expect((await buildEnvelope(minimal)).event_id).toBe(PYTHON_EVENT_ID_MINIMAL);
  });

  it("derives the same event_id with unicode, offsets, floats and nesting", async () => {
    const envelope = await buildEnvelope(rich);
    expect(envelope.event_id).toBe(PYTHON_EVENT_ID_RICH);
    expect(envelope.observed_at).toBe("2026-09-29T17:00:01.000020Z");
  });

  it("gives equivalent timestamp offsets the same identity", async () => {
    const utc = await buildEnvelope(minimal);
    const offset = await buildEnvelope({ ...minimal, observed_at: "2026-09-29T13:00:00-04:00" });
    expect(offset.event_id).toBe(utc.event_id);
  });
});

describe("envelope validation", () => {
  it.each([
    ["blank mission_id", { ...minimal, mission_id: "  " }, /mission_id is required/],
    ["fractional sequence", { ...minimal, sequence: 1.5 }, /non-negative integer/],
    ["negative sequence", { ...minimal, sequence: -1 }, /non-negative integer/],
    ["array payload", { ...minimal, payload: [] }, /payload must be an object/],
    ["null payload", { ...minimal, payload: null }, /payload must be an object/],
    ["zone-less timestamp", { ...minimal, observed_at: "2026-09-29T17:00:00" }, /timezone-qualified/],
    ["unknown schema", { ...minimal, schema_version: "9.9.9" }, /unsupported envelope schema/],
    ["non-canonical payload", { ...minimal, payload: { bad: Number.NaN } }, /not canonical JSON/],
  ])("rejects %s", async (_name, input, message) => {
    await expect(buildEnvelope(input)).rejects.toThrow(message);
    await expect(buildEnvelope(input)).rejects.toBeInstanceOf(EnvelopeError);
  });

  it("verifyEnvelope accepts a self-consistent envelope and rejects a tampered one", async () => {
    const good = await buildEnvelope(rich);
    await expect(verifyEnvelope(good)).resolves.toEqual(good);
    await expect(verifyEnvelope({ ...good, sequence: 8 })).rejects.toThrow(/does not match envelope content/);
    await expect(verifyEnvelope({ ...good, event_id: "" })).rejects.toThrow(/event_id is required/);
    await expect(verifyEnvelope(minimal)).rejects.toThrow(/event_id is required/);
  });
});
