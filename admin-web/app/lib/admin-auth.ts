import { getChatGPTUser, type ChatGPTUser } from "../chatgpt-auth";
import {
  isSupabaseConfigured,
  resolveAdminActor,
} from "./supabase-admin";

export type AdminViewer = {
  actorId: string | null;
  displayName: string;
  email: string;
};

export function parseAdminAllowlist(value: string | undefined): Set<string> {
  return new Set(
    (value ?? "")
      .split(/[\s,;]+/)
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean),
  );
}

export async function getAdminViewer(
  authenticatedUser?: ChatGPTUser | null,
): Promise<AdminViewer | null> {
  const user = authenticatedUser ?? (await getChatGPTUser());
  if (!user) return null;

  const email = user.email.trim().toLowerCase();
  const allowlist = parseAdminAllowlist(process.env.ADMIN_EMAIL_ALLOWLIST);
  if (!allowlist.has(email)) return null;

  if (!isSupabaseConfigured()) {
    return {
      actorId: null,
      displayName: user.displayName,
      email,
    };
  }

  const actor = await resolveAdminActor(email);
  if (!actor) return null;
  return {
    actorId: actor.id,
    displayName: user.displayName,
    email: actor.email,
  };
}
