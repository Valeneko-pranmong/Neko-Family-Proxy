import assert from "node:assert/strict";
import test from "node:test";

import {
  type AuthorizationState,
  createIssueLaunchPermitHandler,
  type Dependencies,
} from "./service.ts";
import { verifyLocalPermit } from "./local_verifier.ts";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const AUTH_SESSION_ID = "22222222-2222-4222-8222-222222222222";
const LAUNCHER_SESSION_ID = "33333333-3333-4333-8333-333333333333";
const INSTALLATION_ID = "44444444-4444-4444-8444-444444444444";
const LICENSE_ID = "55555555-5555-4555-8555-555555555555";
const CHALLENGE = "A".repeat(43);
const CFG = "b".repeat(64);
const CORRELATION_ID = "c".repeat(32);
const ACCESS_TOKEN = "access-token-sentinel";
const PRIVATE_KEY_SENTINEL = "private-key-sentinel";

const validBody = {
  version: 1,
  contractRevision: "s0-rc1",
  correlationId: CORRELATION_ID,
  challenge: CHALLENGE,
  configurationDigest: CFG,
  processName: "pso2.exe",
  targetPid: 4242,
  mode: "ProcessMode",
  product: "neko-family-proxy",
  scope: "proxy:start",
};

const activeState: AuthorizationState = {
  userId: USER_ID,
  authSessionId: AUTH_SESSION_ID,
  launcherSessionId: LAUNCHER_SESSION_ID,
  installationId: INSTALLATION_ID,
  licenseId: LICENSE_ID,
  product: "neko-family-proxy",
};

async function testKeyPair(): Promise<
  { privateKeyPem: string; publicKey: CryptoKey }
> {
  const pair = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  );
  const der = new Uint8Array(
    await crypto.subtle.exportKey("pkcs8", pair.privateKey),
  );
  const base64 = Buffer.from(der).toString("base64").match(/.{1,64}/g)!.join(
    "\n",
  );
  return {
    privateKeyPem:
      `-----BEGIN PRIVATE KEY-----\n${base64}\n-----END PRIVATE KEY-----`,
    publicKey: pair.publicKey,
  };
}

function request(
  body: unknown = validBody,
  authorization = `Bearer ${ACCESS_TOKEN}`,
): Request {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (authorization) headers.authorization = authorization;
  return new Request("http://localhost/issue_launch_permit", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}

async function harness(overrides: Partial<Dependencies> = {}) {
  const keyPair = await testKeyPair();
  const logs: string[] = [];
  const deps: Dependencies = {
    authenticate: async (token) =>
      token === ACCESS_TOKEN
        ? { userId: USER_ID, authSessionId: AUTH_SESSION_ID }
        : null,
    authorize: async () => activeState,
    privateKeyPem: keyPair.privateKeyPem,
    kid: "neko-prod-key-2",
    nowSeconds: () => 2_000_000_000,
    randomUUID: () => crypto.randomUUID(),
    log: (message) => logs.push(message),
    ...overrides,
  };
  return { handler: createIssueLaunchPermitHandler(deps), keyPair, logs };
}

async function response(
  overrides: Partial<Dependencies> = {},
  body: unknown = validBody,
  authorization?: string,
) {
  const h = await harness(overrides);
  const result = await h.handler(
    request(
      body,
      authorization === undefined ? `Bearer ${ACCESS_TOKEN}` : authorization,
    ),
  );
  return { ...h, result, json: await result.json() as Record<string, unknown> };
}

function decodePart(part: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(part, "base64url").toString("utf8"));
}

async function verifyPermit(
  permit: string,
  publicKey: CryptoKey,
): Promise<boolean> {
  const [header, payload, signature] = permit.split(".");
  return crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    publicKey,
    Buffer.from(signature, "base64url"),
    new TextEncoder().encode(`${header}.${payload}`),
  );
}

test("valid active authenticated session returns a verifiable permit", async () => {
  const { result, json, keyPair } = await response();
  assert.equal(result.status, 200);
  assert.deepEqual(
    Object.keys(json).sort(),
    [
      "contractRevision",
      "correlationId",
      "expiresInSeconds",
      "permit",
      "succeeded",
      "version",
    ].sort(),
  );
  assert.equal(json.expiresInSeconds, 30);
  assert.equal(
    await verifyPermit(json.permit as string, keyPair.publicKey),
    true,
  );
});

test("missing Authorization is rejected", async () => {
  const { result } = await response({}, validBody, "");
  assert.equal(result.status, 401);
});

test("invalid JWT is rejected", async () => {
  const { result } = await response({}, validBody, "Bearer invalid-token");
  assert.equal(result.status, 401);
});

test("expired JWT is rejected by authentication", async () => {
  const { result } = await response({ authenticate: async () => null });
  assert.equal(result.status, 401);
});

for (
  const [name, state] of [
    ["replaced session", null],
    ["revoked session", null],
    ["inactive license", null],
    ["expired license", null],
    ["future-dated license", null],
  ] as const
) {
  test(`${name} is rejected`, async () => {
    const { result } = await response({ authorize: async () => state });
    assert.equal(result.status, 403);
  });
}

test("user/session mismatch is rejected", async () => {
  const { result } = await response({
    authorize: async () => ({
      ...activeState,
      authSessionId: crypto.randomUUID(),
    }),
  });
  assert.equal(result.status, 403);
});

const invalidFields: Array<[string, unknown]> = [
  ["product", "other-product"],
  ["scope", "proxy:admin"],
  ["mode", "TunMode"],
  ["processName", "PSO2.EXE"],
  ["targetPid", true],
  ["targetPid", 1.5],
  ["targetPid", 0],
  ["targetPid", 4_294_967_296],
  ["challenge", "A".repeat(42)],
  ["challenge", "A".repeat(42) + "="],
  ["configurationDigest", "B".repeat(64)],
  ["configurationDigest", "b".repeat(63)],
];
for (const [field, value] of invalidFields) {
  test(`invalid ${field} value is rejected`, async () => {
    const { result } = await response({}, { ...validBody, [field]: value });
    assert.equal(result.status, 400);
  });
}

test("unknown and server-owned request fields are rejected", async () => {
  for (
    const field of [
      "sub",
      "sid",
      "iid",
      "lid",
      "user_id",
      "session_id",
      "kid",
      "exp",
    ]
  ) {
    const { result } = await response({}, {
      ...validBody,
      [field]: "untrusted",
    });
    assert.equal(result.status, 400, field);
  }
});

test("missing signing configuration returns sanitized server error", async () => {
  const { result, json } = await response({ privateKeyPem: undefined });
  assert.equal(result.status, 500);
  assert.deepEqual(json, { error: "AuthorizationUnavailable" });
});

test("retired production key ID is rejected as signing misconfiguration", async () => {
  const { result, json } = await response({ kid: "neko-prod-key-1" });
  assert.equal(result.status, 500);
  assert.deepEqual(json, { error: "AuthorizationUnavailable" });
});

test("malformed signing key returns sanitized server error", async () => {
  const { result, json, logs } = await response({
    privateKeyPem: PRIVATE_KEY_SENTINEL,
  });
  assert.equal(result.status, 500);
  assert.deepEqual(json, { error: "AuthorizationUnavailable" });
  assert.equal(
    JSON.stringify({ json, logs }).includes(PRIVATE_KEY_SENTINEL),
    false,
  );
});

test("permit identity and transaction claims are exact and server-derived", async () => {
  const { json } = await response({}, { ...validBody });
  const [headerPart, payloadPart] = (json.permit as string).split(".");
  const header = decodePart(headerPart);
  const payload = decodePart(payloadPart);
  assert.deepEqual(header, {
    alg: "RS256",
    typ: "neko-launch+jwt",
    kid: "neko-prod-key-2",
  });
  assert.equal(payload.sub, USER_ID);
  assert.equal(payload.sid, LAUNCHER_SESSION_ID);
  assert.equal(payload.iid, INSTALLATION_ID);
  assert.equal(payload.lid, LICENSE_ID);
  assert.equal(payload.challenge, CHALLENGE);
  assert.equal(payload.cfg, CFG);
  assert.equal(payload.target_pid, 4242);
  assert.equal(payload.product, "neko-family-proxy");
  assert.equal(payload.scope, "proxy:start");
  assert.equal(payload.mode, "ProcessMode");
});

test("permit lifetime is exactly bounded", async () => {
  const { json } = await response();
  const payload = decodePart((json.permit as string).split(".")[1]);
  assert.equal(payload.nbf, payload.iat);
  assert.equal((payload.exp as number) - (payload.iat as number), 30);
});

test("jti differs between issuance calls", async () => {
  const first = decodePart(
    ((await response()).json.permit as string).split(".")[1],
  );
  const second = decodePart(
    ((await response()).json.permit as string).split(".")[1],
  );
  assert.notEqual(first.jti, second.jti);
});

test("handler denies an authorization result bound to another Auth session", async () => {
  const machineBAuthSession = crypto.randomUUID();
  const { result: denied } = await response({
    authorize: async () => ({
      ...activeState,
      authSessionId: machineBAuthSession,
    }),
  });
  assert.equal(denied.status, 403);

  const { result: accepted } = await response({
    authenticate: async () => ({
      userId: USER_ID,
      authSessionId: machineBAuthSession,
    }),
    authorize: async () => ({
      ...activeState,
      authSessionId: machineBAuthSession,
    }),
  });
  assert.equal(accepted.status, 200);
});

test("access token, permit, and private key never appear in logs or errors", async () => {
  const { result, json, logs } = await response({
    authorize: async () => {
      throw new Error(`dependency ${ACCESS_TOKEN}`);
    },
  });
  assert.equal(result.status, 503);
  const output = JSON.stringify({ json, logs });
  assert.equal(output.includes(ACCESS_TOKEN), false);
  assert.equal(output.includes(PRIVATE_KEY_SENTINEL), false);
  assert.equal(output.includes("eyJ"), false);
});

test("wrong signature, issuer, audience, binding, expiry, and kid are rejected by local verifier", async () => {
  const { json, keyPair } = await response();
  const permit = json.permit as string;
  const expected = {
    issuer: "neko-backend",
    audience: "neko-proxy-core",
    challenge: CHALLENGE,
    configurationDigest: CFG,
    targetPid: 4242,
    now: 2_000_000_000,
    kid: "neko-prod-key-2",
    publicKey: keyPair.publicKey,
  };
  assert.equal(await verifyLocalPermit(permit, expected), true);
  const [h, p, s] = permit.split(".");
  const tamperedSignature = `${s[0] === "A" ? "B" : "A"}${s.slice(1)}`;
  assert.equal(
    await verifyLocalPermit(`${h}.${p}.${tamperedSignature}`, expected),
    false,
  );
  assert.equal(
    await verifyLocalPermit(permit, { ...expected, issuer: "wrong" }),
    false,
  );
  assert.equal(
    await verifyLocalPermit(permit, { ...expected, audience: "wrong" }),
    false,
  );
  assert.equal(
    await verifyLocalPermit(permit, { ...expected, challenge: "Z".repeat(43) }),
    false,
  );
  assert.equal(
    await verifyLocalPermit(permit, {
      ...expected,
      configurationDigest: "a".repeat(64),
    }),
    false,
  );
  assert.equal(
    await verifyLocalPermit(permit, { ...expected, targetPid: 7 }),
    false,
  );
  assert.equal(
    await verifyLocalPermit(permit, { ...expected, now: 2_000_000_032 }),
    false,
  );
  assert.equal(
    await verifyLocalPermit(permit, { ...expected, kid: "unknown-key" }),
    false,
  );
});
