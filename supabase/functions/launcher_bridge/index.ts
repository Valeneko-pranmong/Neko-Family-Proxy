import { createClient } from "npm:@supabase/supabase-js@2";

import { createIdentityVerifier } from "./identity.ts";
import {
  createLauncherBridgeHandler,
  IdentityResolutionError,
} from "./service.ts";
import type { BridgeSession, IdentityLink } from "./service.ts";

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const anonKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const identityBase = (
  Deno.env.get("NEKO_IDENTITY_BASE_URL") ??
  "https://neko-network-id.vercel.app"
).replace(/\/+$/, "");
const jwksUrl = Deno.env.get("NEKO_IDENTITY_JWKS_URL") ??
  `${identityBase}/.well-known/jwks.json`;
const issuer = Deno.env.get("NEKO_IDENTITY_ISSUER") ?? identityBase;
const audience = Deno.env.get("NEKO_IDENTITY_AUDIENCE") ??
  "neko-launcher-bridge";

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function noStore(status: number, body: Record<string, unknown>): Response {
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

function decodeSessionId(accessToken: string): string | null {
  try {
    const parts = accessToken.split(".");
    if (parts.length !== 3) return null;
    const normalized = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded));
    return typeof payload.session_id === "string" ? payload.session_id : null;
  } catch {
    return null;
  }
}

async function bridgeEmail(identitySub: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(identitySub),
  );
  const hex = Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return `launcher-${hex}@neko-launcher.invalid`;
}

function configured(): boolean {
  return Boolean(supabaseUrl && anonKey && serviceKey);
}

if (!configured()) {
  Deno.serve(() => noStore(503, { error: "upstream_unavailable" }));
} else {
  const admin = createClient(supabaseUrl, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });
  const anon = createClient(supabaseUrl, anonKey, {
    auth: { autoRefreshToken: false, persistSession: false, detectSessionInUrl: false },
  });

  const verifier = createIdentityVerifier({ jwksUrl, issuer, audience });

  async function consumeJti(claims: {
    jti: string;
    sub: string;
    exp: number;
  }): Promise<boolean> {
    const { data, error } = await admin
      .schema("launcher_v2")
      .rpc("consume_bridge_jti", {
        p_jti: claims.jti,
        p_identity_sub: claims.sub,
        p_expires_at: new Date(claims.exp * 1000).toISOString(),
      });
    if (error) throw new Error("jti store unavailable");
    return data === true;
  }

  async function resolveIdentity(claims: {
    sub: string;
    username: string;
  }): Promise<IdentityLink> {
    const existing = await admin
      .schema("launcher_v2")
      .from("identity_links")
      .select("id,user_id,status")
      .eq("identity_sub", claims.sub)
      .maybeSingle();
    if (existing.error) {
      throw new IdentityResolutionError("identity_lookup_failed");
    }

    let userId = existing.data?.user_id as string | undefined;
    if (!userId) {
      const email = await bridgeEmail(claims.sub);
      const username = claims.username.slice(0, 64);
      const created = await admin.auth.admin.createUser({
        email,
        email_confirm: true,
        app_metadata: {
          auth_line: "next",
          identity_sub: claims.sub,
        },
        user_metadata: {
          username,
          display_name: username,
        },
      });
      if (!created.error && created.data?.user?.id) {
        userId = created.data.user.id;
      } else {
        const found = await admin
          .schema("launcher_v2")
          .rpc("bridge_find_user_by_identity_sub", {
            p_identity_sub: claims.sub,
          });
        if (found.error || typeof found.data !== "string") {
          throw new IdentityResolutionError("identity_create_failed");
        }
        userId = found.data;
      }
    }

    if (!userId || !UUID.test(userId)) {
      throw new IdentityResolutionError("identity_invalid_user");
    }

    const linked = await admin
      .schema("launcher_v2")
      .rpc("bridge_link_identity", {
        p_identity_sub: claims.sub,
        p_user_id: userId,
      });
    if (linked.error || !linked.data || typeof linked.data !== "object") {
      throw new IdentityResolutionError("identity_link_failed");
    }
    const row = linked.data as Record<string, unknown>;
    const identityLinkId = row.identity_link_id;
    const linkedUserId = row.user_id;
    if (
      typeof identityLinkId !== "string" ||
      !UUID.test(identityLinkId) ||
      linkedUserId !== userId
    ) {
      throw new IdentityResolutionError("identity_link_invalid");
    }

    const user = await admin.auth.admin.getUserById(userId);
    const email = user.data?.user?.email;
    if (user.error || typeof email !== "string" || !email) {
      throw new IdentityResolutionError("identity_user_unavailable");
    }

    return { userId, identityLinkId, email };
  }

  async function mintSession(link: IdentityLink): Promise<BridgeSession> {
    const generated = await admin.auth.admin.generateLink({
      type: "magiclink",
      email: link.email,
    });
    const properties = generated.data?.properties as
      | Record<string, unknown>
      | undefined;
    const tokenHash = properties?.hashed_token;
    if (generated.error || typeof tokenHash !== "string" || !tokenHash) {
      throw new Error("magic link unavailable");
    }

    const verified = await anon.auth.verifyOtp({
      type: "magiclink",
      token_hash: tokenHash,
    });
    const session = verified.data?.session;
    if (verified.error || !session) {
      throw new Error("session verify failed");
    }
    if (
      typeof session.access_token !== "string" ||
      typeof session.refresh_token !== "string" ||
      typeof session.expires_in !== "number"
    ) {
      throw new Error("session invalid");
    }
    const authSessionId = decodeSessionId(session.access_token);
    if (!authSessionId || !UUID.test(authSessionId)) {
      throw new Error("session id unavailable");
    }

    return {
      accessToken: session.access_token,
      refreshToken: session.refresh_token,
      expiresIn: session.expires_in,
      authSessionId,
    };
  }

  async function recordWebSession(
    link: IdentityLink,
    session: BridgeSession,
  ): Promise<boolean> {
    const { data, error } = await admin
      .schema("launcher_v2")
      .rpc("bridge_record_web_session", {
        p_auth_session_id: session.authSessionId,
        p_user_id: link.userId,
        p_identity_link_id: link.identityLinkId,
      });
    if (error) throw new Error("web session store unavailable");
    return data === true;
  }

  const handler = createLauncherBridgeHandler({
    verifyIdentityToken: verifier,
    consumeJti,
    resolveIdentity,
    mintSession,
    recordWebSession,
    log: (message) => console.error(message),
  });

  Deno.serve(handler);
}
