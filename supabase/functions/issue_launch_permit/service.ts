export type AuthenticatedCaller = {
  userId: string;
  authSessionId: string;
  accessToken?: string;
};

export type AuthorizationState = {
  userId: string;
  authSessionId: string;
  launcherSessionId: string;
  product: string;
  error?:
    | "SessionInactive"
    | "SessionMismatch"
    | "EntitlementInactive"
    | "HeartbeatStale";
};

export type Dependencies = {
  authenticate: (accessToken: string) => Promise<AuthenticatedCaller | null>;
  authorize: (
    caller: AuthenticatedCaller,
    challenge: string,
  ) => Promise<AuthorizationState | null>;
  privateKeyPem?: string;
  kid?: string;
  nowSeconds?: () => number;
  randomUUID?: () => string;
  log?: (message: string) => void;
};

const REQUEST_FIELDS = new Set([
  "version",
  "contractRevision",
  "correlationId",
  "challenge",
]);
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CORRELATION = /^[0-9a-f]{32}$/;
const CHALLENGE = /^[A-Za-z0-9_-]{43}$/;
const PERMIT_SECONDS = 30;
const PRODUCTION_KID = "neko-prod-key-2";

function json(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function parseRequest(value: unknown): Record<string, unknown> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const body = value as Record<string, unknown>;
  if (
    Object.keys(body).some((key) => !REQUEST_FIELDS.has(key)) ||
    Object.keys(body).length !== REQUEST_FIELDS.size
  ) return null;
  if (body.version !== 1 || body.contractRevision !== "lite-v1") return null;
  if (
    typeof body.correlationId !== "string" ||
    !CORRELATION.test(body.correlationId)
  ) return null;
  if (typeof body.challenge !== "string" || !CHALLENGE.test(body.challenge)) {
    return null;
  }
  return body;
}

function base64Url(data: Uint8Array | string): string {
  const bytes = typeof data === "string"
    ? new TextEncoder().encode(data)
    : data;
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(
    /=+$/g,
    "",
  );
}

async function importPrivateKey(pem: string): Promise<CryptoKey> {
  const match =
    /^-----BEGIN PRIVATE KEY-----\s+([A-Za-z0-9+/=\s]+)\s+-----END PRIVATE KEY-----$/
      .exec(pem.trim());
  if (!match) throw new Error("invalid signing configuration");
  const binary = atob(match[1].replace(/\s/g, ""));
  const der = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return crypto.subtle.importKey(
    "pkcs8",
    der,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

async function signPermit(
  body: Record<string, unknown>,
  state: AuthorizationState,
  deps: Dependencies,
): Promise<string> {
  if (!deps.privateKeyPem || deps.kid !== PRODUCTION_KID) {
    throw new Error("missing signing configuration");
  }
  const key = await importPrivateKey(deps.privateKeyPem);
  const now = (deps.nowSeconds ?? (() => Math.floor(Date.now() / 1000)))();
  const jti = (deps.randomUUID ?? (() => crypto.randomUUID()))();
  const header = { alg: "RS256", typ: "neko-launch+jwt", kid: deps.kid };
  const payload = {
    iss: "neko-backend",
    aud: "neko-proxy-core",
    sub: state.userId,
    product: state.product,
    scope: "proxy:start",
    challenge: body.challenge,
    iat: now,
    nbf: now,
    exp: now + PERMIT_SECONDS,
    jti,
  };
  const signingInput = `${base64Url(JSON.stringify(header))}.${
    base64Url(JSON.stringify(payload))
  }`;
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(signingInput),
  );
  return `${signingInput}.${base64Url(new Uint8Array(signature))}`;
}

export function createIssueLaunchPermitHandler(deps: Dependencies) {
  return async (request: Request): Promise<Response> => {
    if (request.method !== "POST") {
      return json(405, { error: "MethodNotAllowed" });
    }
    const header = request.headers.get("authorization");
    const bearer = header?.match(/^Bearer ([^\s]+)$/);
    if (!bearer) return json(401, { error: "AuthorizationRequired" });

    let caller: AuthenticatedCaller | null;
    try {
      caller = await deps.authenticate(bearer[1]);
    } catch {
      return json(503, { error: "AuthorizationUnavailable" });
    }
    if (
      !caller || !UUID.test(caller.userId) || !UUID.test(caller.authSessionId)
    ) {
      return json(401, { error: "AuthorizationInvalid" });
    }

    let body: Record<string, unknown> | null;
    try {
      body = parseRequest(await request.json());
    } catch {
      body = null;
    }
    if (!body) return json(400, { error: "ProtocolInvalid" });

    let state: AuthorizationState | null;
    try {
      state = await deps.authorize(
        caller,
        body.challenge as string,
      );
    } catch {
      return json(503, { error: "AuthorizationUnavailable" });
    }
    if (state?.error) return json(403, { error: state.error });
    if (
      !state || state.userId !== caller.userId ||
      state.authSessionId !== caller.authSessionId ||
      state.product !== "neko-family-proxy"
    ) {
      return json(403, { error: "SessionMismatch" });
    }

    try {
      const permit = await signPermit(body, state, deps);
      return json(200, {
        version: 1,
        contractRevision: "lite-v1",
        correlationId: body.correlationId,
        succeeded: true,
        permit,
        expiresInSeconds: PERMIT_SECONDS,
      });
    } catch {
      deps.log?.("issue_launch_permit signing configuration unavailable");
      return json(500, { error: "AuthorizationUnavailable" });
    }
  };
}
