import { createClient } from "npm:@supabase/supabase-js@2";
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";

import {
  type AuthenticatedCaller,
  type AuthorizationState,
  createIssueLaunchPermitHandler,
  type RuntimeProxyConfigRecord,
} from "./service.ts";

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const publishableKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

function decodeValidatedSessionId(accessToken: string): string | null {
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

function clientFor(accessToken: string) {
  if (!supabaseUrl || !publishableKey) {
    throw new Error("backend dependency unavailable");
  }
  return createClient(supabaseUrl, publishableKey, {
    global: { headers: { Authorization: `Bearer ${accessToken}` } },
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

function adminClient() {
  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error("backend dependency unavailable");
  }
  return createClient(supabaseUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

function parseRuntimeConfigRpcResult(data: unknown): RuntimeProxyConfigRecord {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("backend dependency unavailable");
  }
  const row = data as Record<string, unknown>;
  if (
    typeof row.config_version !== "number" ||
    typeof row.endpoint_id !== "string" ||
    typeof row.host !== "string" ||
    typeof row.port !== "number" ||
    typeof row.protocol !== "string" ||
    typeof row.cipher !== "string" ||
    typeof row.credential !== "string"
  ) {
    throw new Error("backend dependency unavailable");
  }
  return {
    config_version: row.config_version,
    endpoint_id: row.endpoint_id,
    host: row.host,
    port: row.port,
    protocol: row.protocol,
    cipher: row.cipher,
    credential: row.credential,
    ...(typeof row.published_at === "string"
      ? { published_at: row.published_at }
      : {}),
  };
}

async function loadRuntimeConfig(): Promise<RuntimeProxyConfigRecord> {
  const client = adminClient();
  const { data, error } = await client
    .schema("launcher")
    .rpc("get_active_runtime_proxy_config");
  if (error) {
    throw new Error("backend dependency unavailable");
  }
  return parseRuntimeConfigRpcResult(data);
}

const handler = createIssueLaunchPermitHandler({
  authenticate: async (accessToken): Promise<AuthenticatedCaller | null> => {
    const client = clientFor(accessToken);
    const { data, error } = await client.auth.getUser(accessToken);
    if (error || !data.user || data.user.is_anonymous === true) return null;
    const authSessionId = decodeValidatedSessionId(accessToken);
    if (!authSessionId) return null;
    return { userId: data.user.id, authSessionId, accessToken };
  },
  authorize: async (
    caller,
    body,
  ): Promise<AuthorizationState | null> => {
    const accessToken = caller.accessToken;
    if (!accessToken) throw new Error("authenticated context unavailable");
    const client = clientFor(accessToken);
    const challenge = typeof body.challenge === "string" ? body.challenge : "";

    if (body.contractRevision === "runtime-config-v1" && body.machineProof) {
      const proof = body.machineProof as Record<string, unknown>;
      const pubB64 = typeof proof.publicKeyB64 === "string" ? proof.publicKeyB64 : "";
      const sigB64 = typeof proof.signatureB64 === "string" ? proof.signatureB64 : "";
      if (!pubB64 || !sigB64) return null;

      const paddedPub = pubB64 + "=".repeat((4 - (pubB64.length % 4)) % 4);
      const paddedSig = sigB64 + "=".repeat((4 - (sigB64.length % 4)) % 4);

      const rawPub = new Uint8Array(atob(paddedPub.replace(/-/g, "+").replace(/_/g, "/")).split("").map(c => c.charCodeAt(0)));
      const rawSig = new Uint8Array(atob(paddedSig.replace(/-/g, "+").replace(/_/g, "/")).split("").map(c => c.charCodeAt(0)));
      const msgBytes = new TextEncoder().encode(challenge);

      try {
        const cryptoKey = await crypto.subtle.importKey(
          "raw",
          rawPub,
          { name: "Ed25519" },
          false,
          ["verify"]
        );
        const isValid = await crypto.subtle.verify(
          "Ed25519",
          cryptoKey,
          rawSig,
          msgBytes
        );
        if (!isValid) return null;
      } catch (e) {
        return null;
      }

      const pubHashBuf = await crypto.subtle.digest("SHA-256", rawPub);
      const pubHash = Array.from(new Uint8Array(pubHashBuf)).map(b => b.toString(16).padStart(2, "0")).join("");

      const providedHash = typeof proof.keyHash === "string" ? proof.keyHash : "";
      if (pubHash !== providedHash) return null;

      // We will check the database matches this hash after getting the state
      // by injecting it into the state so we don't do an extra query if authorization fails
      // Actually, we can just verify it below using the returned session_id!
    }

    const { data, error } = await client
      .schema("launcher")
      .rpc("authorize_launch_permit", {
        p_challenge: challenge,
      });
    if (error) throw new Error("authorization dependency unavailable");
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const row = data as Record<string, unknown>;
    const authorizationError = row.error;
    if (
      authorizationError === "SessionInactive" ||
      authorizationError === "SessionMismatch" ||
      authorizationError === "EntitlementInactive" ||
      authorizationError === "HeartbeatStale"
    ) {
      return {
        userId: caller.userId,
        authSessionId: caller.authSessionId,
        launcherSessionId: "",
        product: "",
        error: authorizationError,
      };
    }
    const state: AuthorizationState = {
      userId: String(row.user_id ?? ""),
      authSessionId: String(row.auth_session_id ?? ""),
      launcherSessionId: String(row.session_id ?? ""),
      product: String(row.product_code ?? ""),
    };

    if (body.contractRevision === "runtime-config-v1" && body.machineProof) {
      const proof = body.machineProof as Record<string, unknown>;
      const providedHash = typeof proof.keyHash === "string" ? proof.keyHash : "";
      const { data: sessionData, error: sessionError } = await client
        .from("launcher_sessions")
        .select("installation_id, installations(installation_key_hash)")
        .eq("id", state.launcherSessionId)
        .single();
      if (sessionError || !sessionData || !sessionData.installations) return null;
      // @ts-ignore
      const dbHash = sessionData.installations.installation_key_hash;
      if (providedHash !== dbHash) return null;
    }

    return state.userId === caller.userId &&
        state.authSessionId === caller.authSessionId
      ? state
      : null;
  },
  loadRuntimeConfig,
  privateKeyPem: Deno.env.get("RS256_PRIVATE_KEY"),
  kid: Deno.env.get("RS256_KID"),
  log: (message) => console.error(message),
});

serve(handler);
