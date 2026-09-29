import { describe, expect, it } from "vitest";
import fixture from "../../../tests/fixtures/canonical-json-v1.json";
import { CANONICAL_JSON_VERSION, canonicalJson, canonicalSha256, normalizeTimestamp } from "../src/canonical";

describe("canonical JSON v1 (shared cross-runtime vectors)", () => {
  it("is the version the Python side pins", () => {
    expect(fixture.canonical_version).toBe(CANONICAL_JSON_VERSION);
  });

  for (const vector of fixture.vectors) {
    it(`matches bytes and sha256 for ${vector.id}`, async () => {
      expect(canonicalJson(vector.value)).toBe(vector.canonical_json);
      expect(await canonicalSha256(vector.value)).toBe(vector.sha256);
    });
  }

  for (const vector of fixture.timestamps) {
    it(`normalises ${vector.input}`, () => {
      expect(normalizeTimestamp(vector.input)).toBe(vector.canonical);
    });
  }
});

describe("canonical JSON edge cases", () => {
  it("orders keys by code point, not UTF-16 unit (astral vs U+FFFF)", () => {
    // Python sorts U+FFFF (0xFFFF) before U+10000; UTF-16 unit order would flip them.
    expect(canonicalJson({ "\u{10000}": 1, "￿": 2 })).toBe('{"￿":2,"\u{10000}":1}');
  });

  it("uses shortest round-trip floats with fixed/scientific thresholds", () => {
    expect(canonicalJson([1e-6, 1e-7, 1e20, 1e21, 0.1, -0, 1.0])).toBe(
      "[0.000001,1e-7,100000000000000000000,1e+21,0.1,0,1]",
    );
  });

  it("rejects non-finite numbers, unsafe bigint, and non-plain values", () => {
    expect(() => canonicalJson(Number.NaN)).toThrow(/Out of range float/);
    expect(() => canonicalJson(Number.POSITIVE_INFINITY)).toThrow(/Out of range float/);
    expect(() => canonicalJson(9_007_199_254_740_992n)).toThrow(/safe range/);
    expect(canonicalJson(9_007_199_254_740_991n)).toBe("9007199254740991");
    expect(() => canonicalJson(new Date())).toThrow(/unsupported/);
    expect(() => canonicalJson(undefined)).toThrow(/unsupported/);
  });

  it("rejects timestamps without a zone or with impossible dates", () => {
    expect(() => normalizeTimestamp("2026-09-29T13:00:01")).toThrow(/timezone-qualified/);
    expect(() => normalizeTimestamp("2026-02-30T00:00:00Z")).toThrow(/valid calendar/);
    expect(() => normalizeTimestamp("2026-09-29T13:00:01+25:00")).toThrow(/offset/);
  });
});
