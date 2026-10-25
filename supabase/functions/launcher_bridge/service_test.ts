import assert from "node:assert/strict";
import test from "node:test";

import {
  type BridgeDependencies,
  type BridgeSession,
  createLauncherBridgeHandler,
  IdentityResolutionError,
  type IdentityLink,
} from "./service.ts";

const USER_ID = "11111111-1111-4111-8111-111111111111";
const LINK_ID = "22222222-2222-4222-8222-222222222222";
const AUTH_SESSION_ID = "33333333-3333-4333-8333-333333333333";
const TOKEN = "a".repeat(48);

const claims = {
  iss: "https://identity.test",
  aud: "neko-launcher-bridge",
  sub: "discord-sub-1",
  username: "neko_user",
  scope: "launcher:login",
  jti: "jti-1",
  iat: 1_700_000_000,
  nbf: 1_700_000_000,
  exp: 1_700_000_300,
};

const link: IdentityLink = {
  userId: USER_ID,
  identityLinkId: LINK_ID,
  email: "launcher@example.invalid",
};

const session: BridgeSession = {
  accessToken: "access-token",
  refreshToken: "refresh-token",
  expiresIn: 3600,
  authSessionId: AUTH_SESSION_ID,
};

function request(
  options: {
    method?: string;
    authorization?: string | null;
    body?: string;
  } = {},
): Request {
  const headers = new Headers();
  if (options.authorization !== null) {
    headers.set("authorization", options.authorization ?? `Bearer ${TOKEN}`);
  }
  const method = options.method ?? "POST";
  return new Request("https://bridge.test/auth/launcher/exchange", {
    method,
    headers,
    body: method === "GET" || method === "HEAD"
      ? undefined
      : options.body ?? "{}",
  });
}

function dependencies(
  overrides: Partial<BridgeDependencies> = {},
): BridgeDependencies {
  return {
    verifyIdentityToken: async () => claims,
    consumeJti: async () => true,
    resolveIdentity: async () => link,
    mintSession: async () => session,
    recordWebSession: async () => true,
    ...overrides,
  };
}

test("exchanges a verified identity token for a session", async () => {
  const response = await createLauncherBridgeHandler(dependencies())(
    request(),
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.deepEqual(await response.json(), {
    token_type: "Bearer",
    access_token: "access-token",
    refresh_token: "refresh-token",
    expires_in: 3600,
  });
});

test("does not log the identity token or session tokens", async () => {
  const logs: string[] = [];
  await createLauncherBridgeHandler(
    dependencies({ log: (message) => logs.push(message) }),
  )(request());

  const joined = logs.join("\n");
  assert.equal(joined.includes(TOKEN), false);
  assert.equal(joined.includes(session.accessToken), false);
  assert.equal(joined.includes(session.refreshToken), false);
});

test("rejects missing or malformed authorization", async () => {
  const handler = createLauncherBridgeHandler(dependencies());

  assert.equal((await handler(request({ authorization: null }))).status, 401);
  assert.equal(
    (await handler(request({ authorization: "Bearer short" }))).status,
    401,
  );
});

test("rejects non-POST methods and non-empty request bodies", async () => {
  const handler = createLauncherBridgeHandler(dependencies());

  assert.equal((await handler(request({ method: "GET" }))).status, 405);
  assert.equal(
    (await handler(request({ body: '{"unexpected":true}' }))).status,
    400,
  );
});

test("rejects a replayed identity token", async () => {
  const response = await createLauncherBridgeHandler(
    dependencies({ consumeJti: async () => false }),
  )(request());

  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { error: "token_replayed" });
});

test("maps identity link failures without leaking details", async () => {
  const response = await createLauncherBridgeHandler(
    dependencies({
      resolveIdentity: async () => {
        throw new IdentityResolutionError("identity_link_conflict");
      },
    }),
  )(request());

  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { error: "identity_not_linked" });
});

test("maps operational identity failures to upstream unavailable", async () => {
  const response = await createLauncherBridgeHandler(
    dependencies({
      resolveIdentity: async () => {
        throw new IdentityResolutionError("identity_create_failed");
      },
    }),
  )(request());

  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: "upstream_unavailable" });
});

test("fails closed when minting or recording the session fails", async () => {
  const mintFailure = await createLauncherBridgeHandler(
    dependencies({
      mintSession: async () => {
        throw new Error("mint failed");
      },
    }),
  )(request());
  assert.equal(mintFailure.status, 503);

  const recordFailure = await createLauncherBridgeHandler(
    dependencies({ recordWebSession: async () => false }),
  )(request());
  assert.equal(recordFailure.status, 503);
});

test("rejects malformed session material", async () => {
  const response = await createLauncherBridgeHandler(
    dependencies({
      mintSession: async () => ({ ...session, authSessionId: "not-a-uuid" }),
    }),
  )(request());

  assert.equal(response.status, 503);
});
