import assert from "node:assert/strict";
import test from "node:test";

import {
  createIdentityVerifier,
  IdentityTokenError,
} from "./identity.ts";

const ISSUER = "https://identity.test";
const AUDIENCE = "neko-launcher-bridge";
const JWKS_URL = "https://identity.test/.well-known/jwks.json";
const NOW = 1_700_000_000;

function encode(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

async function keyMaterial(): Promise<{
  privateKey: CryptoKey;
  jwk: JsonWebKey;
  sign: (claims: Record<string, unknown>, kid?: string) => Promise<string>;
}> {
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
  const exported = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const jwk = { ...exported, kid: "kid-1", alg: "RS256", use: "sig" };

  return {
    privateKey: pair.privateKey,
    jwk,
    sign: async (claims, kid = "kid-1") => {
      const signingInput = `${encode({ alg: "RS256", typ: "JWT", kid })}.${
        encode(claims)
      }`;
      const signature = await crypto.subtle.sign(
        "RSASSA-PKCS1-v1_5",
        pair.privateKey,
        new TextEncoder().encode(signingInput),
      );
      return `${signingInput}.${
        Buffer.from(new Uint8Array(signature)).toString("base64url")
      }`;
    },
  };
}

function claims(overrides: Record<string, unknown> = {}) {
  return {
    iss: ISSUER,
    aud: AUDIENCE,
    sub: "discord-sub-1",
    username: "neko_user",
    scope: "launcher:login",
    jti: "jti-1",
    iat: NOW - 10,
    nbf: NOW - 10,
    exp: NOW + 300,
    ...overrides,
  };
}

function jwksResponse(jwk: JsonWebKey): Response {
  return new Response(JSON.stringify({ keys: [jwk] }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

async function expectCode(
  promise: Promise<unknown>,
  code: string,
): Promise<void> {
  await assert.rejects(promise, (error: unknown) => {
    assert.ok(error instanceof IdentityTokenError);
    assert.equal(error.code, code);
    return true;
  });
}

test("verifies a valid RS256 identity token", async () => {
  const material = await keyMaterial();
  const token = await material.sign(claims());
  const verifier = createIdentityVerifier({
    jwksUrl: JWKS_URL,
    issuer: ISSUER,
    audience: AUDIENCE,
    fetchImpl: (async () => jwksResponse(material.jwk)) as typeof fetch,
    nowSeconds: () => NOW,
  });

  const result = await verifier(token);
  assert.equal(result.sub, "discord-sub-1");
  assert.equal(result.jti, "jti-1");
  assert.equal(result.scope, "launcher:login");
});

test("rejects a tampered signature", async () => {
  const material = await keyMaterial();
  const token = await material.sign(claims());
  const parts = token.split(".");
  const tampered = `${parts[0]}.${encode(claims({ sub: "attacker" }))}.${
    parts[2]
  }`;
  const verifier = createIdentityVerifier({
    jwksUrl: JWKS_URL,
    issuer: ISSUER,
    audience: AUDIENCE,
    fetchImpl: (async () => jwksResponse(material.jwk)) as typeof fetch,
    nowSeconds: () => NOW,
  });

  await expectCode(verifier(tampered), "invalid_signature");
});

test("rejects wrong audience, scope, and expiry", async () => {
  const material = await keyMaterial();
  const verifier = createIdentityVerifier({
    jwksUrl: JWKS_URL,
    issuer: ISSUER,
    audience: AUDIENCE,
    fetchImpl: (async () => jwksResponse(material.jwk)) as typeof fetch,
    nowSeconds: () => NOW,
  });

  await expectCode(
    verifier(await material.sign(claims({ aud: "other-audience" }))),
    "invalid_audience",
  );
  await expectCode(
    verifier(await material.sign(claims({ scope: "openid" }))),
    "invalid_claims",
  );
  await expectCode(
    verifier(await material.sign(claims({ exp: NOW - 1 }))),
    "invalid_time_claims",
  );
});

test("rejects an unknown kid after one refresh attempt", async () => {
  const material = await keyMaterial();
  let calls = 0;
  const verifier = createIdentityVerifier({
    jwksUrl: JWKS_URL,
    issuer: ISSUER,
    audience: AUDIENCE,
    fetchImpl: (async () => {
      calls += 1;
      return jwksResponse(material.jwk);
    }) as typeof fetch,
    nowSeconds: () => NOW,
  });

  await expectCode(
    verifier(await material.sign(claims(), "unknown-kid")),
    "unknown_kid",
  );
  assert.equal(calls, 2);
});

test("rejects malformed tokens and unavailable JWKS", async () => {
  const material = await keyMaterial();
  const verifier = createIdentityVerifier({
    jwksUrl: JWKS_URL,
    issuer: ISSUER,
    audience: AUDIENCE,
    fetchImpl: (async () => jwksResponse(material.jwk)) as typeof fetch,
    nowSeconds: () => NOW,
  });

  await expectCode(verifier("not-a-jwt"), "malformed_token");
  await expectCode(
    verifier(await material.sign(claims({ iss: "https://wrong.test" }))),
    "invalid_issuer",
  );

  const unavailable = createIdentityVerifier({
    jwksUrl: JWKS_URL,
    issuer: ISSUER,
    audience: AUDIENCE,
    fetchImpl: (async () => {
      throw new Error("network unavailable");
    }) as typeof fetch,
    nowSeconds: () => NOW,
  });
  await expectCode(
    unavailable(await material.sign(claims())),
    "jwks_unavailable",
  );
});
