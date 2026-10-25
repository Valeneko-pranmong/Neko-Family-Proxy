export type IdentityClaims = {
  iss: string;
  aud: string | string[];
  sub: string;
  username: string;
  scope: string;
  jti: string;
  iat: number;
  nbf: number;
  exp: number;
};

export class IdentityTokenError extends Error {
  readonly code: string;

  constructor(code: string) {
    super("invalid identity token");
    this.name = "IdentityTokenError";
    this.code = code;
  }
}

export type IdentityVerifierOptions = {
  jwksUrl: string;
  issuer: string;
  audience: string;
  fetchImpl?: typeof fetch;
  nowSeconds?: () => number;
  cacheTtlSeconds?: number;
  timeoutMs?: number;
  maxJwksBytes?: number;
};

const MAX_KEY_COUNT = 20;
const MAX_CLOCK_SKEW_SECONDS = 5;
const MAX_TOKEN_LIFETIME_SECONDS = 600;
const MAX_UNKNOWN_KID_REFRESH_SECONDS = 5;

function base64UrlBytes(value: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new IdentityTokenError("malformed_token");
  }
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  let binary: string;
  try {
    binary = globalThis.atob(padded);
  } catch {
    throw new IdentityTokenError("malformed_token");
  }
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function decodeJsonPart(value: string): Record<string, unknown> {
  try {
    const decoded = new TextDecoder().decode(base64UrlBytes(value));
    const parsed = JSON.parse(decoded);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("not an object");
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof IdentityTokenError) throw error;
    throw new IdentityTokenError("malformed_token");
  }
}

function asStringArray(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value;
  }
  return [];
}

function validateClaims(
  payload: Record<string, unknown>,
  issuer: string,
  audience: string,
  now: number,
): IdentityClaims {
  const iss = payload.iss;
  const sub = payload.sub;
  const username = payload.username;
  const scope = payload.scope;
  const jti = payload.jti;
  const iat = payload.iat;
  const nbf = payload.nbf;
  const exp = payload.exp;

  if (typeof iss !== "string" || iss !== issuer) {
    throw new IdentityTokenError("invalid_issuer");
  }
  if (!asStringArray(payload.aud).includes(audience)) {
    throw new IdentityTokenError("invalid_audience");
  }
  if (
    typeof sub !== "string" ||
    sub.length < 1 ||
    sub.length > 255 ||
    typeof username !== "string" ||
    username.length < 1 ||
    username.length > 64 ||
    typeof scope !== "string" ||
    !scope.split(/\s+/).includes("launcher:login") ||
    typeof jti !== "string" ||
    jti.length < 1 ||
    jti.length > 200
  ) {
    throw new IdentityTokenError("invalid_claims");
  }
  if (
    !Number.isSafeInteger(iat) ||
    !Number.isSafeInteger(nbf) ||
    !Number.isSafeInteger(exp) ||
    exp <= now ||
    nbf > now + MAX_CLOCK_SKEW_SECONDS ||
    iat > now + MAX_CLOCK_SKEW_SECONDS ||
    exp <= iat ||
    exp - iat > MAX_TOKEN_LIFETIME_SECONDS
  ) {
    throw new IdentityTokenError("invalid_time_claims");
  }

  return {
    iss,
    aud: payload.aud as string | string[],
    sub,
    username,
    scope,
    jti,
    iat,
    nbf,
    exp,
  };
}

export function createIdentityVerifier(
  options: IdentityVerifierOptions,
): (token: string) => Promise<IdentityClaims> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const nowSeconds = options.nowSeconds ??
    (() => Math.floor(Date.now() / 1000));
  const cacheTtlSeconds = options.cacheTtlSeconds ?? 300;
  const timeoutMs = options.timeoutMs ?? 5_000;
  const maxJwksBytes = options.maxJwksBytes ?? 65_536;

  let cachedKeys = new Map<string, CryptoKey>();
  let cachedAt = 0;
  let lastUnknownKidRefresh = 0;
  let inFlight: Promise<Map<string, CryptoKey>> | null = null;

  async function fetchKeys(): Promise<Map<string, CryptoKey>> {
    let response: Response;
    try {
      response = await fetchImpl(options.jwksUrl, {
        headers: { accept: "application/json" },
        redirect: "error",
        cache: "no-store",
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch {
      throw new IdentityTokenError("jwks_unavailable");
    }
    if (!response.ok) {
      throw new IdentityTokenError("jwks_unavailable");
    }

    let text: string;
    try {
      text = await response.text();
    } catch {
      throw new IdentityTokenError("jwks_unavailable");
    }
    if (text.length > maxJwksBytes) {
      throw new IdentityTokenError("jwks_too_large");
    }

    let document: unknown;
    try {
      document = JSON.parse(text);
    } catch {
      throw new IdentityTokenError("jwks_invalid");
    }
    if (!document || typeof document !== "object") {
      throw new IdentityTokenError("jwks_invalid");
    }
    const keysValue = (document as Record<string, unknown>).keys;
    if (
      !Array.isArray(keysValue) ||
      keysValue.length < 1 ||
      keysValue.length > MAX_KEY_COUNT
    ) {
      throw new IdentityTokenError("jwks_invalid");
    }

    const keys = new Map<string, CryptoKey>();
    for (const candidate of keysValue) {
      if (!candidate || typeof candidate !== "object") {
        throw new IdentityTokenError("jwks_invalid");
      }
      const jwk = candidate as Record<string, unknown>;
      if (
        jwk.kty !== "RSA" ||
        typeof jwk.kid !== "string" ||
        jwk.kid.length < 1 ||
        jwk.kid.length > 128 ||
        typeof jwk.n !== "string" ||
        typeof jwk.e !== "string" ||
        (jwk.use !== undefined && jwk.use !== "sig") ||
        (jwk.alg !== undefined && jwk.alg !== "RS256") ||
        keys.has(jwk.kid)
      ) {
        throw new IdentityTokenError("jwks_invalid");
      }
      let key: CryptoKey;
      try {
        key = await crypto.subtle.importKey(
          "jwk",
          {
            kty: "RSA",
            n: jwk.n,
            e: jwk.e,
            alg: "RS256",
            ext: true,
          },
          { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
          false,
          ["verify"],
        );
      } catch {
        throw new IdentityTokenError("jwks_invalid");
      }
      keys.set(jwk.kid, key);
    }
    return keys;
  }

  async function loadKeys(force: boolean): Promise<Map<string, CryptoKey>> {
    const now = nowSeconds();
    if (!force && cachedKeys.size > 0 && now - cachedAt < cacheTtlSeconds) {
      return cachedKeys;
    }
    if (inFlight) return await inFlight;
    inFlight = fetchKeys()
      .then((keys) => {
        cachedKeys = keys;
        cachedAt = nowSeconds();
        return keys;
      })
      .finally(() => {
        inFlight = null;
      });
    return await inFlight;
  }

  return async (token: string): Promise<IdentityClaims> => {
    if (typeof token !== "string" || token.length < 20 || token.length > 8_192) {
      throw new IdentityTokenError("malformed_token");
    }
    const parts = token.split(".");
    if (parts.length !== 3) {
      throw new IdentityTokenError("malformed_token");
    }

    const header = decodeJsonPart(parts[0]);
    if (header.alg !== "RS256" || typeof header.kid !== "string") {
      throw new IdentityTokenError("invalid_header");
    }

    let keys = await loadKeys(false);
    let key = keys.get(header.kid);
    if (!key) {
      const now = nowSeconds();
      if (now - lastUnknownKidRefresh >= MAX_UNKNOWN_KID_REFRESH_SECONDS) {
        lastUnknownKidRefresh = now;
        keys = await loadKeys(true);
        key = keys.get(header.kid);
      }
    }
    if (!key) {
      throw new IdentityTokenError("unknown_kid");
    }

    let valid = false;
    try {
      valid = await crypto.subtle.verify(
        "RSASSA-PKCS1-v1_5",
        key,
        base64UrlBytes(parts[2]),
        new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
      );
    } catch {
      valid = false;
    }
    if (!valid) {
      throw new IdentityTokenError("invalid_signature");
    }

    const payload = decodeJsonPart(parts[1]);
    return validateClaims(
      payload,
      options.issuer,
      options.audience,
      nowSeconds(),
    );
  };
}
