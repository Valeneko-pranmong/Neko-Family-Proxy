import assert from "node:assert/strict";
import test from "node:test";

import {
  type AuthorizationState,
  createIssueLaunchPermitHandler,
  type Dependencies,
} from "./service.ts";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const AUTH_SESSION_ID = "22222222-2222-4222-8222-222222222222";
const CHALLENGE = "A".repeat(43);
const CORRELATION_ID = "c".repeat(32);
const ACCESS_TOKEN = "access-token-sentinel";

const validBody = {
  version: 1,
  contractRevision: "lite-v1",
  correlationId: CORRELATION_ID,
  challenge: CHALLENGE,
};

const activeState: AuthorizationState = {
  userId: USER_ID,
  authSessionId: AUTH_SESSION_ID,
  launcherSessionId: "33333333-3333-4333-8333-333333333333",
  product: "neko-family-proxy",
};

async function keyPair(): Promise<
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
  return {
    privateKeyPem: `-----BEGIN PRIVATE KEY-----\n${
      Buffer.from(der).toString("base64")
    }\n-----END PRIVATE KEY-----`,
    publicKey: pair.publicKey,
  };
}

async function handler(overrides: Partial<Dependencies> = {}) {
  const keys = await keyPair();
  return createIssueLaunchPermitHandler({
    authenticate: async (token) =>
      token === ACCESS_TOKEN
        ? { userId: USER_ID, authSessionId: AUTH_SESSION_ID }
        : null,
    authorize: async () => activeState,
    privateKeyPem: keys.privateKeyPem,
    kid: "neko-prod-key-2",
    nowSeconds: () => 2_000_000_000,
    randomUUID: () => "33333333-3333-4333-8333-333333333333",
    ...overrides,
  });
}

async function request(
  body: unknown = validBody,
  authorization = `Bearer ${ACCESS_TOKEN}`,
  overrides: Partial<Dependencies> = {},
) {
  const invoke = await handler(overrides);
  const result = await invoke(
    new Request("http://localhost/issue_launch_permit", {
      method: "POST",
      headers: { "content-type": "application/json", authorization },
      body: JSON.stringify(body),
    }),
  );
  return { result, body: await result.json() as Record<string, unknown> };
}

function payload(permit: string): Record<string, unknown> {
  return JSON.parse(
    Buffer.from(permit.split(".")[1], "base64url").toString("utf8"),
  );
}

test("Lite request produces minimal 30-second permit", async () => {
  const { result, body } = await request();
  assert.equal(result.status, 200);
  assert.deepEqual(Object.keys(body).sort(), [
    "contractRevision",
    "correlationId",
    "expiresInSeconds",
    "permit",
    "succeeded",
    "version",
  ]);
  assert.equal(body.contractRevision, "lite-v1");
  assert.equal(body.expiresInSeconds, 30);
  const claims = payload(body.permit as string);
  assert.deepEqual(Object.keys(claims).sort(), [
    "aud",
    "challenge",
    "exp",
    "iat",
    "iss",
    "jti",
    "nbf",
    "product",
    "scope",
    "sub",
  ]);
  assert.equal(claims.iss, "neko-backend");
  assert.equal(claims.aud, "neko-proxy-core");
  assert.equal(claims.sub, USER_ID);
  assert.equal(claims.challenge, CHALLENGE);
  assert.equal((claims.exp as number) - (claims.iat as number), 30);
});

test("Lite request rejects removed S0 fields and client identity", async () => {
  for (
    const body of [
      { ...validBody, configurationDigest: "b".repeat(64) },
      { ...validBody, processName: "pso2.exe" },
      { ...validBody, targetPid: 42 },
      { ...validBody, mode: "ProcessMode" },
      { ...validBody, product: "neko-family-proxy" },
      { ...validBody, scope: "proxy:start" },
      { ...validBody, userId: USER_ID },
      { ...validBody, sessionId: AUTH_SESSION_ID },
      { ...validBody, licenseId: "33333333-3333-4333-8333-333333333333" },
      { ...validBody, installationId: "44444444-4444-4444-8444-444444444444" },
    ]
  ) {
    const { result } = await request(body);
    assert.equal(result.status, 400);
  }
});

test("Auth B cannot issue permit for Auth A session", async () => {
  const { result, body } = await request(validBody, undefined, {
    authorize: async () => ({
      ...activeState,
      authSessionId: "44444444-4444-4444-8444-444444444444",
    }),
  });
  assert.equal(result.status, 403);
  assert.deepEqual(body, { error: "SessionMismatch" });
});

test("Backend preserves sanitized authorization-state denials", async () => {
  for (
    const error of [
      "SessionInactive",
      "SessionMismatch",
      "EntitlementInactive",
      "HeartbeatStale",
    ] as const
  ) {
    const { result, body } = await request(validBody, undefined, {
      authorize: async () => ({ ...activeState, error }),
    });
    assert.equal(result.status, 403);
    assert.deepEqual(body, { error });
  }
});

test("missing bearer, invalid caller, malformed challenge, and unavailable signer fail closed", async () => {
  assert.equal((await request(validBody, "")).result.status, 401);
  assert.equal((await request(validBody, "Bearer invalid")).result.status, 401);
  assert.equal(
    (await request({ ...validBody, challenge: "bad" })).result.status,
    400,
  );
  const unavailable = await request(validBody, undefined, {
    privateKeyPem: undefined,
  });
  assert.equal(unavailable.result.status, 500);
  assert.deepEqual(unavailable.body, { error: "AuthorizationUnavailable" });
});
