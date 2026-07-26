import { randomBytes } from "node:crypto";
import { createClient } from "@supabase/supabase-js";
import { config } from "./config.mjs";
import { tableGet } from "./supabase.mjs";

const sessions = new Map();

function authError(message, status) {
  const error = new Error(message);
  error.status = status;
  return error;
}

export async function authenticateAdmin(email, password) {
  const authClient = createClient(config.supabaseUrl, config.supabaseSecretKey, {
    auth: {
      autoRefreshToken: false,
      detectSessionInUrl: false,
      persistSession: false,
    },
  });
  let result;
  try {
    result = await authClient.auth.signInWithPassword({ email, password });
  } catch {
    throw authError("ไม่สามารถเชื่อมต่อ Supabase Auth ได้", 502);
  }
  if (result.error || !result.data.user) {
    throw authError("อีเมลหรือรหัสผ่านไม่ถูกต้อง", 401);
  }
  const profiles = await tableGet("profiles", {
    select: "id,display_name,role",
    id: `eq.${result.data.user.id}`,
    limit: "1",
  });
  const profile = profiles[0];
  if (!profile || profile.role !== "admin") {
    throw authError("บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ", 403);
  }
  return {
    userId: result.data.user.id,
    email: result.data.user.email || email,
    name: profile.display_name || result.data.user.email || email,
    role: profile.role,
  };
}

export function createSession(viewer) {
  const token = randomBytes(32).toString("base64url");
  sessions.set(token, { expiresAt: Date.now() + config.sessionTtlMs, viewer });
  return token;
}

export function getSession(token) {
  if (!token) return null;
  const session = sessions.get(token);
  if (!session) return null;
  if (session.expiresAt <= Date.now()) {
    sessions.delete(token);
    return null;
  }
  return session;
}

export function deleteSession(token) {
  if (token) sessions.delete(token);
}

export function sessionCookie(token) {
  return `admin_session=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${Math.floor(
    config.sessionTtlMs / 1000,
  )}`;
}

export function clearSessionCookie() {
  return "admin_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0";
}
