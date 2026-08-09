import { createClient } from "npm:@supabase/supabase-js@2";
import { serve } from "https://deno.land/std@0.224.0/http/server.ts";

import {
  type AuthenticatedCaller,
  type AuthorizationState,
  createIssueLaunchPermitHandler,
} from "./service.ts";

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const publishableKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";

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
    product,
    challenge,
  ): Promise<AuthorizationState | null> => {
    const accessToken = caller.accessToken;
    if (!accessToken) throw new Error("authenticated context unavailable");
    const client = clientFor(accessToken);
    const { data, error } = await client
      .schema("launcher")
      .rpc("authorize_launch_permit", {
        p_product_code: product,
        p_challenge: challenge,
      });
    if (error) throw new Error("authorization dependency unavailable");
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const row = data as Record<string, unknown>;
    const state: AuthorizationState = {
      userId: String(row.user_id ?? ""),
      authSessionId: String(row.auth_session_id ?? ""),
      launcherSessionId: String(row.session_id ?? ""),
      installationId: String(row.installation_id ?? ""),
      licenseId: String(row.license_id ?? ""),
      product: String(row.product_code ?? ""),
    };
    return state.userId === caller.userId &&
        state.authSessionId === caller.authSessionId
      ? state
      : null;
  },
  privateKeyPem: Deno.env.get("RS256_PRIVATE_KEY"),
  kid: Deno.env.get("RS256_KID"),
  log: (message) => console.error(message),
});

serve(handler);
