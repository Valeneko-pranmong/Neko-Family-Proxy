import assert from "node:assert/strict";
import test from "node:test";

import {
  type AuthorizationState,
  createIssueLaunchPermitHandler,
  type Dependencies,
  type RuntimeProxyConfigRecord,
} from "./service.ts";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const AUTH_SESSION_ID = "22222222-2222-4222-8222-222222222222";
const CHALLENGE = "A".repeat(43);
const CORRELATION_ID = "c".repeat(32);
const ACCESS_TOKEN = "access-token-sentinel";
const SENTINEL_SECRET = "SENTINEL_PROXY_SECRET_42";

const activeConfigRecord: RuntimeProxyConfigRecord = {
  config_version: 18,
  endpoint_id: "japan-vps-1",
  host: "127.0.0.1",
  port: 8389,
  protocol: "shadowsocks",
  cipher: "aes-256-gcm",
  credential: SENTINEL_SECRET,
};

const validBody = {
  version: 1,
  contractRevision: "runtime-config-v1",
  correlationId: CORRELATION_ID,
  challenge: CHALLENGE,
};

const validLiteBody = {
  ...validBody,
  contractRevision: "lite-v1",
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

async function handler(
  overrides: Partial<Dependencies> = {},
  logs: string[] = [],
) {
  const keys = await keyPair();
  return createIssueLaunchPermitHandler({
    authenticate: async (token) =>
      token === ACCESS_TOKEN
        ? { userId: USER_ID, authSessionId: AUTH_SESSION_ID }
        : null,
    authorize: async () => activeState,
    loadRuntimeConfig: async () => ({ ...activeConfigRecord }),
    privateKeyPem: keys.privateKeyPem,
    kid: "neko-prod-key-2",
    nowSeconds: () => 1000,
    randomUUID: () => "33333333-3333-4333-8333-333333333333",
    log: (msg) => logs.push(msg),
    ...overrides,
  });
}

async function request(
  body: unknown = validBody,
  authorization = `Bearer ${ACCESS_TOKEN}`,
  overrides: Partial<Dependencies> = {},
  logs: string[] = [],
) {
  const invoke = await handler(overrides, logs);
  const result = await invoke(
    new Request("http://localhost/issue_launch_permit", {
      method: "POST",
      headers: { "content-type": "application/json", authorization },
      body: JSON.stringify(body),
    }),
  );
  return { result, body: await result.json() as Record<string, unknown>, logs };
}

function jwtPart(permit: string, index: number): Record<string, unknown> {
  return JSON.parse(
    Buffer.from(permit.split(".")[index], "base64url").toString("utf8"),
  );
}

function payload(permit: string): Record<string, unknown> {
  return jwtPart(permit, 1);
}

async function verifyPermit(
  publicKey: CryptoKey,
  permit: string,
): Promise<boolean> {
  const [header, claims, encodedSignature] = permit.split(".");
  const signature = Buffer.from(encodedSignature, "base64url");
  return crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    publicKey,
    signature,
    new TextEncoder().encode(`${header}.${claims}`),
  );
}

test("Valid request produces exact success response with runtime-config-v1, 120s expiry, signed claims, and no logged secret", async () => {
  const logs: string[] = [];
  const { result, body } = await request(
    validBody,
    undefined,
    undefined,
    logs,
  );
  assert.equal(result.status, 200);
  assert.deepEqual(Object.keys(body).sort(), [
    "contractRevision",
    "correlationId",
    "expiresInSeconds",
    "permit",
    "runtimeConfig",
    "succeeded",
    "version",
  ]);
  assert.equal(body.version, 1);
  assert.equal(body.contractRevision, "runtime-config-v1");
  assert.equal(body.correlationId, CORRELATION_ID);
  assert.equal(body.succeeded, true);
  assert.equal(body.expiresInSeconds, 30);

  const runtimeConfig = body.runtimeConfig as Record<string, unknown>;
  assert.deepEqual(Object.keys(runtimeConfig).sort(), [
    "cipher",
    "configVersion",
    "credential",
    "endpointId",
    "expiresAt",
    "host",
    "issuedAt",
    "port",
    "protocol",
    "schemaVersion",
  ]);
  assert.equal(runtimeConfig.schemaVersion, 1);
  assert.equal(runtimeConfig.configVersion, 18);
  assert.equal(runtimeConfig.endpointId, "japan-vps-1");
  assert.equal(runtimeConfig.host, "127.0.0.1");
  assert.equal(runtimeConfig.port, 8389);
  assert.equal(runtimeConfig.protocol, "shadowsocks");
  assert.equal(runtimeConfig.cipher, "aes-256-gcm");
  assert.equal(runtimeConfig.credential, SENTINEL_SECRET);
  assert.equal(runtimeConfig.issuedAt, 1000);
  assert.equal(runtimeConfig.expiresAt, 1120);
  assert.equal(
    (runtimeConfig.expiresAt as number) - (runtimeConfig.issuedAt as number),
    120,
  );

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
    "runtime_config_sha256",
    "runtime_config_version",
    "scope",
    "sub",
  ]);
  assert.equal(claims.iss, "neko-backend");
  assert.equal(claims.aud, "neko-proxy-core");
  assert.equal(claims.sub, USER_ID);
  assert.equal(claims.challenge, CHALLENGE);
  assert.equal((claims.exp as number) - (claims.iat as number), 30);
  assert.equal(claims.runtime_config_version, 18);
  assert.match(
    claims.runtime_config_sha256 as string,
    /^[0-9a-f]{64}$/,
  );
  assert.equal(
    claims.runtime_config_sha256,
    "02060535a1e3c4db74edffc8d0b1f5bfd6feee948980669ff06acab9afdecf4d",
  );

  assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
});

test("lite-v1 preserves exact legacy response and JWT claim contracts without loading runtime config", async () => {
  const keys = await keyPair();
  let loaderCalls = 0;
  const { result, body } = await request(validLiteBody, undefined, {
    privateKeyPem: keys.privateKeyPem,
    loadRuntimeConfig: async () => {
      loaderCalls += 1;
      throw new Error("runtime config provider unavailable");
    },
  });

  assert.equal(result.status, 200);
  assert.deepEqual(Object.keys(body).sort(), [
    "contractRevision",
    "correlationId",
    "expiresInSeconds",
    "permit",
    "succeeded",
    "version",
  ]);
  assert.deepEqual(
    Object.fromEntries(
      Object.entries(body).filter(([key]) => key !== "permit"),
    ),
    {
      version: 1,
      contractRevision: "lite-v1",
      correlationId: CORRELATION_ID,
      succeeded: true,
      expiresInSeconds: 30,
    },
  );
  assert.equal(loaderCalls, 0);

  assert.deepEqual(jwtPart(body.permit as string, 0), {
    alg: "RS256",
    typ: "neko-launch+jwt",
    kid: "neko-prod-key-2",
  });
  assert.equal(await verifyPermit(keys.publicKey, body.permit as string), true);
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
  assert.deepEqual(claims, {
    iss: "neko-backend",
    aud: "neko-proxy-core",
    sub: USER_ID,
    product: "neko-family-proxy",
    scope: "proxy:start",
    challenge: CHALLENGE,
    iat: 1000,
    nbf: 1000,
    exp: 1030,
    jti: "33333333-3333-4333-8333-333333333333",
  });
  assert.equal("runtime_config_version" in claims, false);
  assert.equal("runtime_config_sha256" in claims, false);
});

test("Runtime config loader returns null / missing active config fails closed with safe 503", async () => {
  const logs: string[] = [];
  const { result, body } = await request(
    validBody,
    undefined,
    { loadRuntimeConfig: async () => null },
    logs,
  );
  assert.equal(result.status, 503);
  assert.deepEqual(body, { error: "AuthorizationUnavailable" });
  assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
});

test("Runtime config loader throwing error fails closed with safe 503", async () => {
  const logs: string[] = [];
  const { result, body } = await request(
    validBody,
    undefined,
    {
      loadRuntimeConfig: async () => {
        throw new Error("db connection error");
      },
    },
    logs,
  );
  assert.equal(result.status, 503);
  assert.deepEqual(body, { error: "AuthorizationUnavailable" });
  assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
});

test("Invalid runtime config fields fail closed with safe 503 and never log secret", async () => {
  const invalidConfigs: Array<Partial<RuntimeProxyConfigRecord>> = [
    { config_version: 0 },
    { config_version: -1 },
    { config_version: 1.5 },
    { endpoint_id: "" },
    { endpoint_id: "a".repeat(65) },
    { endpoint_id: "japan\nvps" },
    { endpoint_id: "japan\rvps" },
    { endpoint_id: "japan\x00vps" },
    { endpoint_id: "\u0e0d\u0e35\u0e48\u0e1b\u0e38\u0e48\u0e19" },
    { host: "" },
    { host: "h".repeat(254) },
    { host: "127.0.0.1\n" },
    { host: "127.0.0.1\r" },
    { host: "host\tname" },
    { host: "\u0e42\u0e2e\u0e2a\u0e15\u0e4c.com" },
    { port: 0 },
    { port: 65536 },
    { port: -1 },
    { port: 80.5 },
    { protocol: "socks5" as unknown as "shadowsocks" },
    { protocol: "SHADOWSOCKS" as unknown as "shadowsocks" },
    { protocol: "" as unknown as "shadowsocks" },
    { cipher: "" },
    { cipher: "c".repeat(65) },
    { cipher: "aes\n256" },
    { cipher: "aes\r256" },
    { cipher: "\u0e23\u0e2b\u0e31\u0e2a" },
    { credential: "" },
    { credential: "s".repeat(257) },
    { credential: "secret\nline" },
    { credential: "secret\rline" },
    { credential: "\u0e04\u0e27\u0e32\u0e21\u0e25\u0e31\u0e1a" },
  ];

  for (const patch of invalidConfigs) {
    const logs: string[] = [];
    const { result, body } = await request(
      validBody,
      undefined,
      {
        loadRuntimeConfig: async () => ({
          ...activeConfigRecord,
          ...patch,
        }),
      },
      logs,
    );
    assert.equal(result.status, 503);
    assert.deepEqual(body, { error: "AuthorizationUnavailable" });
    assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
    assert.equal(logs.join("\n").includes("japan-vps-1"), false);
  }
});

test("config_version Number.MAX_SAFE_INTEGER + 1 is rejected", async () => {
  const logs: string[] = [];
  const { result, body } = await request(
    validBody,
    undefined,
    {
      loadRuntimeConfig: async () => ({
        ...activeConfigRecord,
        config_version: Number.MAX_SAFE_INTEGER + 1,
      }),
    },
    logs,
  );
  assert.equal(result.status, 503);
  assert.deepEqual(body, { error: "AuthorizationUnavailable" });
  assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
  assert.equal(logs.join("\n").includes("japan-vps-1"), false);
});

test("nowSeconds values 1000.5, NaN, -1, Number.MAX_SAFE_INTEGER are rejected with exact safe 503 before hash/sign", async () => {
  for (const badNow of [1000.5, NaN, -1, Number.MAX_SAFE_INTEGER]) {
    const logs: string[] = [];
    let digestCalled = false;
    const { result, body } = await request(
      validBody,
      undefined,
      {
        nowSeconds: () => badNow,
        digestRuntimeConfigSha256: async () => {
          digestCalled = true;
          return "unexpected-digest";
        },
      },
      logs,
    );
    assert.equal(result.status, 503);
    assert.deepEqual(body, { error: "AuthorizationUnavailable" });
    assert.equal(digestCalled, false);
    assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
  }
});

test("nowSeconds callback throwing is caught and returns exact safe 503", async () => {
  const logs: string[] = [];
  const { result, body } = await request(
    validBody,
    undefined,
    {
      nowSeconds: () => {
        throw new Error("time source crashed with " + SENTINEL_SECRET);
      },
    },
    logs,
  );
  assert.equal(result.status, 503);
  assert.deepEqual(body, { error: "AuthorizationUnavailable" });
  assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
});

test("SHA-256 digest failure returns exact HTTP 503 body AuthorizationUnavailable and sentinel credential is absent from response and logs", async () => {
  const logs: string[] = [];
  const { result, body } = await request(
    validBody,
    undefined,
    {
      digestRuntimeConfigSha256: async () => {
        throw new Error("crypto hardware failure leaking " + SENTINEL_SECRET);
      },
    },
    logs,
  );
  assert.equal(result.status, 503);
  assert.deepEqual(body, { error: "AuthorizationUnavailable" });
  assert.equal(JSON.stringify(body).includes(SENTINEL_SECRET), false);
  assert.equal(logs.join("\n").includes(SENTINEL_SECRET), false);
});

test("Unknown contractRevision is rejected with 400 ProtocolInvalid before authorization or runtime config access", async () => {
  let authorizeCalls = 0;
  let loaderCalls = 0;
  const { result, body } = await request(
    { ...validBody, contractRevision: "future-v2" },
    undefined,
    {
      authorize: async () => {
        authorizeCalls += 1;
        return activeState;
      },
      loadRuntimeConfig: async () => {
        loaderCalls += 1;
        return { ...activeConfigRecord };
      },
    },
  );
  assert.equal(result.status, 400);
  assert.deepEqual(body, { error: "ProtocolInvalid" });
  assert.equal(authorizeCalls, 0);
  assert.equal(loaderCalls, 0);
});

test("Lite request rejects removed S0 fields and client identity", async () => {
  for (
    const body of [
      { ...validLiteBody, configurationDigest: "b".repeat(64) },
      { ...validLiteBody, processName: "pso2.exe" },
      { ...validLiteBody, targetPid: 42 },
      { ...validLiteBody, mode: "ProcessMode" },
      { ...validLiteBody, product: "neko-family-proxy" },
      { ...validLiteBody, scope: "proxy:start" },
      { ...validLiteBody, userId: USER_ID },
      { ...validLiteBody, sessionId: AUTH_SESSION_ID },
      {
        ...validLiteBody,
        licenseId: "33333333-3333-4333-8333-333333333333",
      },
      {
        ...validLiteBody,
        installationId: "44444444-4444-4444-8444-444444444444",
      },
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
