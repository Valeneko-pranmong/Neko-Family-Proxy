import type { IdentityClaims } from "./identity.ts";

export type IdentityLink = {
  userId: string;
  identityLinkId: string;
  email: string;
};

export type BridgeSession = {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  authSessionId: string;
};

export type BridgeDependencies = {
  verifyIdentityToken: (token: string) => Promise<IdentityClaims>;
  consumeJti: (claims: IdentityClaims) => Promise<boolean>;
  resolveIdentity: (claims: IdentityClaims) => Promise<IdentityLink>;
  mintSession: (link: IdentityLink) => Promise<BridgeSession>;
  recordWebSession: (
    link: IdentityLink,
    session: BridgeSession,
  ) => Promise<boolean>;
  log?: (message: string) => void;
};

export class IdentityResolutionError extends Error {
  readonly code: string;

  constructor(code: string) {
    super("identity resolution failed");
    this.name = "IdentityResolutionError";
    this.code = code;
  }
}

const MAX_BODY_BYTES = 1_024;
const MAX_TOKEN_CHARS = 8_192;
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function json(
  status: number,
  body: Record<string, unknown>,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
    },
  });
}

function bearerToken(request: Request): string | null {
  const header = request.headers.get("authorization");
  if (!header) return null;
  const match = /^Bearer ([A-Za-z0-9._-]+)$/.exec(header);
  if (!match || match[1].length < 20 || match[1].length > MAX_TOKEN_CHARS) {
    return null;
  }
  return match[1];
}

async function hasOnlyEmptyBody(request: Request): Promise<boolean> {
  let raw: string;
  try {
    raw = await request.text();
  } catch {
    return false;
  }
  if (raw.length > MAX_BODY_BYTES) return false;
  if (!raw.trim()) return true;
  try {
    const body = JSON.parse(raw);
    return !!body && typeof body === "object" && !Array.isArray(body) &&
      Object.keys(body).length === 0;
  } catch {
    return false;
  }
}

function validSession(session: BridgeSession): boolean {
  return (
    typeof session.accessToken === "string" &&
    session.accessToken.length > 0 &&
    session.accessToken.length <= MAX_TOKEN_CHARS &&
    typeof session.refreshToken === "string" &&
    session.refreshToken.length > 0 &&
    session.refreshToken.length <= MAX_TOKEN_CHARS &&
    Number.isSafeInteger(session.expiresIn) &&
    session.expiresIn >= 0 &&
    session.expiresIn <= 3_600 &&
    typeof session.authSessionId === "string" &&
    UUID.test(session.authSessionId)
  );
}

function validLink(link: IdentityLink): boolean {
  return (
    typeof link.userId === "string" &&
    UUID.test(link.userId) &&
    typeof link.identityLinkId === "string" &&
    UUID.test(link.identityLinkId) &&
    typeof link.email === "string" &&
    link.email.length > 0 &&
    link.email.length <= 254
  );
}

export function createLauncherBridgeHandler(
  deps: BridgeDependencies,
): (request: Request) => Promise<Response> {
  return async (request: Request): Promise<Response> => {
    if (request.method !== "POST") {
      return json(405, { error: "MethodNotAllowed" });
    }

    const token = bearerToken(request);
    if (!token) {
      return json(401, { error: "invalid_token" });
    }
    if (!(await hasOnlyEmptyBody(request))) {
      return json(400, { error: "invalid_request" });
    }

    let claims: IdentityClaims;
    try {
      claims = await deps.verifyIdentityToken(token);
    } catch {
      deps.log?.("bridge_identity_token_rejected");
      return json(401, { error: "invalid_token" });
    }

    let jtiAccepted: boolean;
    try {
      jtiAccepted = await deps.consumeJti(claims);
    } catch {
      deps.log?.("bridge_jti_store_unavailable");
      return json(503, { error: "upstream_unavailable" });
    }
    if (!jtiAccepted) {
      return json(409, { error: "token_replayed" });
    }

    let link: IdentityLink;
    try {
      link = await deps.resolveIdentity(claims);
    } catch (error) {
      const code = error instanceof IdentityResolutionError
        ? error.code
        : "identity_not_linked";
      deps.log?.(`bridge_identity_resolution_failed:${code}`);
      if (
        code === "identity_lookup_failed" ||
        code === "identity_create_failed" ||
        code === "identity_user_unavailable" ||
        code === "identity_link_failed"
      ) {
        return json(503, { error: "upstream_unavailable" });
      }
      return json(409, { error: "identity_not_linked" });
    }
    if (!validLink(link)) {
      deps.log?.("bridge_identity_link_invalid");
      return json(409, { error: "identity_not_linked" });
    }

    let session: BridgeSession;
    try {
      session = await deps.mintSession(link);
    } catch {
      deps.log?.("bridge_session_mint_failed");
      return json(503, { error: "upstream_unavailable" });
    }
    if (!validSession(session)) {
      deps.log?.("bridge_session_invalid");
      return json(503, { error: "upstream_unavailable" });
    }

    let recorded: boolean;
    try {
      recorded = await deps.recordWebSession(link, session);
    } catch {
      deps.log?.("bridge_web_session_store_failed");
      return json(503, { error: "upstream_unavailable" });
    }
    if (!recorded) {
      deps.log?.("bridge_web_session_rejected");
      return json(503, { error: "upstream_unavailable" });
    }

    return json(200, {
      token_type: "Bearer",
      access_token: session.accessToken,
      refresh_token: session.refreshToken,
      expires_in: session.expiresIn,
    });
  };
}
