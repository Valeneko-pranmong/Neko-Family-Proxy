type ExpectedPermit = {
  issuer: string;
  audience: string;
  challenge: string;
  configurationDigest: string;
  targetPid: number;
  now: number;
  kid: string;
  publicKey: CryptoKey;
};

const HEADER_FIELDS = ["alg", "kid", "typ"];
const CLAIM_FIELDS = [
  "aud",
  "cfg",
  "challenge",
  "exp",
  "iat",
  "iid",
  "iss",
  "jti",
  "lid",
  "mode",
  "nbf",
  "product",
  "scope",
  "sid",
  "sub",
  "target_pid",
];

function decodeJson(segment: string): Record<string, unknown> | null {
  try {
    if (!/^[A-Za-z0-9_-]+$/.test(segment)) return null;
    const bytes = Uint8Array.from(
      atob(
        segment.replace(/-/g, "+").replace(/_/g, "/").padEnd(
          Math.ceil(segment.length / 4) * 4,
          "=",
        ),
      ),
      (c) => c.charCodeAt(0),
    );
    const value = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    );
    return value && typeof value === "object" && !Array.isArray(value)
      ? value
      : null;
  } catch {
    return null;
  }
}

function exactFields(
  value: Record<string, unknown>,
  expected: string[],
): boolean {
  return JSON.stringify(Object.keys(value).sort()) ===
    JSON.stringify([...expected].sort());
}

function boundedAscii(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.trim().length > 0 &&
    value.length <= maximum && /^[\x00-\x7f]+$/.test(value);
}

export async function verifyLocalPermit(
  permit: string,
  expected: ExpectedPermit,
): Promise<boolean> {
  if (!permit || permit.length > 4096 || !/^[\x00-\x7f]+$/.test(permit)) {
    return false;
  }
  const parts = permit.split(".");
  if (parts.length !== 3 || parts.some((part) => !part)) return false;
  const header = decodeJson(parts[0]);
  const claims = decodeJson(parts[1]);
  if (
    !header || !claims || !exactFields(header, HEADER_FIELDS) ||
    !exactFields(claims, CLAIM_FIELDS)
  ) return false;
  if (
    header.alg !== "RS256" || header.typ !== "neko-launch+jwt" ||
    header.kid !== expected.kid
  ) return false;
  if (!boundedAscii(header.kid, 128)) return false;

  const strings = [
    "iss",
    "aud",
    "sub",
    "sid",
    "iid",
    "lid",
    "product",
    "scope",
    "cfg",
    "challenge",
    "mode",
  ];
  if (
    strings.some((name) => !boundedAscii(claims[name], 128)) ||
    !boundedAscii(claims.jti, 64)
  ) return false;
  if (
    claims.iss !== expected.issuer || claims.aud !== expected.audience ||
    claims.product !== "neko-family-proxy" || claims.scope !== "proxy:start" ||
    claims.mode !== "ProcessMode"
  ) return false;
  if (
    claims.challenge !== expected.challenge ||
    claims.cfg !== expected.configurationDigest ||
    claims.target_pid !== expected.targetPid
  ) return false;
  if (
    !/^[A-Za-z0-9_-]{43}$/.test(claims.challenge as string) ||
    !/^[0-9a-f]{64}$/.test(claims.cfg as string)
  ) return false;

  const numbers = [claims.target_pid, claims.iat, claims.nbf, claims.exp];
  if (
    numbers.some((value) =>
      typeof value !== "number" || !Number.isSafeInteger(value)
    )
  ) return false;
  const iat = claims.iat as number;
  const nbf = claims.nbf as number;
  const exp = claims.exp as number;
  if (
    nbf !== iat || exp !== iat + 30 || iat > expected.now + 2 ||
    nbf > expected.now + 2 || exp <= expected.now - 2
  ) return false;

  return crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    expected.publicKey,
    Uint8Array.from(
      atob(
        parts[2].replace(/-/g, "+").replace(/_/g, "/").padEnd(
          Math.ceil(parts[2].length / 4) * 4,
          "=",
        ),
      ),
      (c) => c.charCodeAt(0),
    ),
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
  );
}
