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

export type RuntimeProxyConfigRecord = {
  config_version: number;
  endpoint_id: string;
  host: string;
  port: number;
  protocol: string;
  cipher: string;
  credential: string;
  published_at?: string;
};

export type Dependencies = {
  authenticate: (accessToken: string) => Promise<AuthenticatedCaller | null>;
  authorize: (
    caller: AuthenticatedCaller,
    challenge: string,
  ) => Promise<AuthorizationState | null>;
  loadRuntimeConfig?: () => Promise<RuntimeProxyConfigRecord | null>;
  privateKeyPem?: string;
  kid?: string;
  nowSeconds?: () => number;
  randomUUID?: () => string;
  digestRuntimeConfigSha256?: (bytes: Uint8Array) => Promise<string>;
  log?: (message: string) => void;
};

type ValidatedRuntimeConfig = {
  configVersion: number;
  endpointId: string;
  host: string;
  port: number;
  protocol: "shadowsocks";
  cipher: string;
  credential: string;
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
const RUNTIME_CONFIG_SECONDS = 120;
const PRODUCTION_KID = "neko-prod-key-2";

const PRINTABLE_ASCII_64 = /^[\x20-\x7e]{1,64}$/;
const PRINTABLE_ASCII_253 = /^[\x20-\x7e]{1,253}$/;
const PRINTABLE_ASCII_256 = /^[\x20-\x7e]{1,256}$/;

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
  if (
    body.version !== 1 ||
    (body.contractRevision !== "lite-v1" &&
      body.contractRevision !== "runtime-config-v1")
  ) return null;
  if (
    typeof body.correlationId !== "string" ||
    !CORRELATION.test(body.correlationId)
  ) return null;
  if (typeof body.challenge !== "string" || !CHALLENGE.test(body.challenge)) {
    return null;
  }
  return body;
}

function parseRuntimeConfig(value: unknown): ValidatedRuntimeConfig | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const rec = value as Record<string, unknown>;
  if (
    typeof rec.config_version !== "number" ||
    !Number.isSafeInteger(rec.config_version) ||
    rec.config_version <= 0
  ) {
    return null;
  }
  if (
    typeof rec.endpoint_id !== "string" ||
    !PRINTABLE_ASCII_64.test(rec.endpoint_id)
  ) {
    return null;
  }
  if (
    typeof rec.host !== "string" ||
    !PRINTABLE_ASCII_253.test(rec.host)
  ) {
    return null;
  }
  if (
    typeof rec.port !== "number" ||
    !Number.isInteger(rec.port) ||
    rec.port < 1 ||
    rec.port > 65535
  ) {
    return null;
  }
  if (rec.protocol !== "shadowsocks") {
    return null;
  }
  if (
    typeof rec.cipher !== "string" ||
    !PRINTABLE_ASCII_64.test(rec.cipher)
  ) {
    return null;
  }
  if (
    typeof rec.credential !== "string" ||
    !PRINTABLE_ASCII_256.test(rec.credential)
  ) {
    return null;
  }
  return {
    configVersion: rec.config_version,
    endpointId: rec.endpoint_id,
    host: rec.host,
    port: rec.port,
    protocol: "shadowsocks",
    cipher: rec.cipher,
    credential: rec.credential,
  };
}

function canonicalConfigBytes(
  config: ValidatedRuntimeConfig,
  issuedAt: number,
  expiresAt: number,
): Uint8Array {
  const text = `schema_version=1\n` +
    `config_version=${config.configVersion}\n` +
    `endpoint_id=${config.endpointId}\n` +
    `host=${config.host}\n` +
    `port=${config.port}\n` +
    `protocol=shadowsocks\n` +
    `cipher=${config.cipher}\n` +
    `credential=${config.credential}\n` +
    `issued_at=${issuedAt}\n` +
    `expires_at=${expiresAt}\n`;
  return new TextEncoder().encode(text);
}

async function sha256Hex(
  bytes: Uint8Array,
  customDigest?: (bytes: Uint8Array) => Promise<string>,
): Promise<string> {
  if (customDigest) {
    return await customDigest(bytes);
  }
  const digest = await crypto.subtle.digest(
    "SHA-256",
    bytes.buffer as ArrayBuffer,
  );
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
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

async function signLegacyPermit(
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

async function signPermit(
  body: Record<string, unknown>,
  state: AuthorizationState,
  configVersion: number,
  configSha256: string,
  now: number,
  deps: Dependencies,
): Promise<string> {
  if (!deps.privateKeyPem || deps.kid !== PRODUCTION_KID) {
    throw new Error("missing signing configuration");
  }
  const key = await importPrivateKey(deps.privateKeyPem);
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
    runtime_config_version: configVersion,
    runtime_config_sha256: configSha256,
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

    if (body.contractRevision === "lite-v1") {
      try {
        const permit = await signLegacyPermit(body, state, deps);
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
    }

    let rawConfig: RuntimeProxyConfigRecord | null;
    try {
      if (!deps.loadRuntimeConfig) {
        deps.log?.("issue_launch_permit runtime config provider unavailable");
        return json(503, { error: "AuthorizationUnavailable" });
      }
      rawConfig = await deps.loadRuntimeConfig();
    } catch {
      deps.log?.("issue_launch_permit runtime config loader failed");
      return json(503, { error: "AuthorizationUnavailable" });
    }
    if (!rawConfig) {
      deps.log?.("issue_launch_permit active runtime config unavailable");
      return json(503, { error: "AuthorizationUnavailable" });
    }

    const config = parseRuntimeConfig(rawConfig);
    if (!config) {
      deps.log?.("issue_launch_permit runtime config validation failed");
      return json(503, { error: "AuthorizationUnavailable" });
    }

    let now: number;
    try {
      now = (deps.nowSeconds ?? (() => Math.floor(Date.now() / 1000)))();
    } catch {
      deps.log?.("issue_launch_permit time evaluation failed");
      return json(503, { error: "AuthorizationUnavailable" });
    }
    if (
      typeof now !== "number" ||
      !Number.isSafeInteger(now) ||
      now < 0 ||
      now > Number.MAX_SAFE_INTEGER - RUNTIME_CONFIG_SECONDS
    ) {
      deps.log?.("issue_launch_permit time evaluation out of range");
      return json(503, { error: "AuthorizationUnavailable" });
    }

    const issuedAt = now;
    const expiresAt = now + RUNTIME_CONFIG_SECONDS;
    const canonicalBytes = canonicalConfigBytes(config, issuedAt, expiresAt);
    let configSha256: string;
    try {
      configSha256 = await sha256Hex(
        canonicalBytes,
        deps.digestRuntimeConfigSha256,
      );
    } catch {
      deps.log?.("issue_launch_permit runtime config digest failed");
      return json(503, { error: "AuthorizationUnavailable" });
    }

    try {
      const permit = await signPermit(
        body,
        state,
        config.configVersion,
        configSha256,
        now,
        deps,
      );
      return json(200, {
        version: 1,
        contractRevision: "runtime-config-v1",
        correlationId: body.correlationId,
        succeeded: true,
        permit,
        expiresInSeconds: PERMIT_SECONDS,
        runtimeConfig: {
          schemaVersion: 1,
          configVersion: config.configVersion,
          endpointId: config.endpointId,
          host: config.host,
          port: config.port,
          protocol: config.protocol,
          cipher: config.cipher,
          credential: config.credential,
          issuedAt,
          expiresAt,
        },
      });
    } catch {
      deps.log?.("issue_launch_permit signing configuration unavailable");
      return json(500, { error: "AuthorizationUnavailable" });
    }
  };
}
