/**
 * Canonical JSON v1 for the Workers runtime.
 *
 * Byte-for-byte compatible with `nougencode.canonical` (Python): the shared
 * vectors in `tests/fixtures/canonical-json-v1.json` are the contract, and
 * `test/canonical.test.ts` runs every one of them.
 *
 * JS caveat: `1.0` and `1` are the same number here, and unsafe integers cannot
 * be told apart from large floats, so integer-range rejection applies to
 * `bigint` inputs only. Python's own encoding of integral floats already
 * matches (`1.0` -> `1`, `1e20` -> `100000000000000000000`).
 */

export const CANONICAL_JSON_VERSION = "nougen.canonical-json.v1";
const MAX_SAFE_INTEGER = 9_007_199_254_740_991n;

export type CanonicalValue =
  | null
  | boolean
  | number
  | bigint
  | string
  | readonly CanonicalValue[]
  | { readonly [key: string]: CanonicalValue };

/** Compare by Unicode code point, as Python's `sorted(str)` does (not UTF-16 units). */
function compareCodePoints(a: string, b: string): number {
  const ia = a[Symbol.iterator]();
  const ib = b[Symbol.iterator]();
  for (;;) {
    const ra = ia.next();
    const rb = ib.next();
    if (ra.done || rb.done) return ra.done === rb.done ? 0 : ra.done ? -1 : 1;
    const ca = ra.value.codePointAt(0)!;
    const cb = rb.value.codePointAt(0)!;
    if (ca !== cb) return ca < cb ? -1 : 1;
  }
}

function encodeNumber(value: number): string {
  if (!Number.isFinite(value)) {
    throw new RangeError("Out of range float values are not canonical JSON compliant");
  }
  // ECMAScript Number->String is the shortest round-trip spelling with the same
  // fixed/scientific thresholds (1e-6 <= |x| < 1e21) that the Python side pins.
  // String(-0) is "0", matching the Python vectors.
  return String(value);
}

function encode(value: unknown): string {
  if (value === null) return "null";
  switch (typeof value) {
    case "boolean":
      return value ? "true" : "false";
    case "number":
      return encodeNumber(value);
    case "bigint": {
      const magnitude = value < 0n ? -value : value;
      if (magnitude > MAX_SAFE_INTEGER) {
        throw new RangeError("canonical JSON integer exceeds the interoperable safe range");
      }
      return value.toString();
    }
    case "string":
      return JSON.stringify(value);
    case "object": {
      if (Array.isArray(value)) return `[${value.map(encode).join(",")}]`;
      const proto = Object.getPrototypeOf(value);
      if (proto !== Object.prototype && proto !== null) {
        throw new TypeError("unsupported canonical JSON value: only plain objects and arrays");
      }
      const record = value as Record<string, unknown>;
      const members = Object.keys(record)
        .sort(compareCodePoints)
        .map((key) => `${JSON.stringify(key)}:${encode(record[key])}`);
      return `{${members.join(",")}}`;
    }
    default:
      throw new TypeError(`unsupported canonical JSON value: ${typeof value}`);
  }
}

export function canonicalJson(value: unknown): string {
  return encode(value);
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function canonicalSha256(value: unknown): Promise<string> {
  return sha256Hex(canonicalJson(value));
}

const TIMESTAMP =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;

/**
 * Normalise a timezone-qualified ISO timestamp to UTC RFC 3339 with fixed
 * microseconds. Rejects zone-less input, like the Python `normalize_timestamp`.
 */
export function normalizeTimestamp(value: string): string {
  if (typeof value !== "string") {
    throw new TypeError("canonical timestamps must be timezone-qualified ISO strings");
  }
  const match = TIMESTAMP.exec(value);
  if (!match) {
    throw new RangeError("canonical timestamps must be timezone-qualified ISO strings");
  }
  const [, year, month, day, hour, minute, second, fraction = "", zone] = match;
  const [y, mo, d, h, mi, s] = [year, month, day, hour, minute, second].map(Number) as [
    number, number, number, number, number, number,
  ];
  let offsetMinutes = 0;
  if (zone !== "Z") {
    const sign = zone![0] === "-" ? -1 : 1;
    const zh = Number(zone!.slice(1, 3));
    const zm = Number(zone!.slice(4, 6));
    if (zh > 23 || zm > 59) throw new RangeError("invalid timezone offset");
    offsetMinutes = sign * (zh * 60 + zm);
  }
  const wall = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  if (
    wall.getUTCFullYear() !== y || wall.getUTCMonth() !== mo - 1 || wall.getUTCDate() !== d ||
    wall.getUTCHours() !== h || wall.getUTCMinutes() !== mi || wall.getUTCSeconds() !== s
  ) {
    throw new RangeError("canonical timestamps must be valid calendar times");
  }
  const utc = new Date(wall.getTime() - offsetMinutes * 60_000);
  const micros = fraction.slice(0, 6).padEnd(6, "0");
  return `${utc.toISOString().slice(0, 19)}.${micros}Z`;
}
