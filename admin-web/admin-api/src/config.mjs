import process from "node:process";
import { readFileSync } from "node:fs";

function loadDotEnv() {
  const envPaths = [
    new URL("../../.env", import.meta.url),
    new URL("../.env", import.meta.url),
  ];
  for (const envPath of envPaths) {
    try {
      const text = readFileSync(envPath, "utf8");
      for (const line of text.split(/\r?\n/)) {
        const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
        if (!match || process.env[match[1]]) continue;
        process.env[match[1]] = match[2].replace(/^"(.*)"$/, "$1");
      }
    } catch {
      // Environment variables can be supplied by the shell instead.
    }
  }
}

loadDotEnv();

const required = (name) => {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing ${name} in admin-web/.env`);
  return value;
};

export const config = {
  host: process.env.ADMIN_HOST?.trim() || "127.0.0.1",
  port: Number(process.env.ADMIN_PORT || 8787),
  sessionTtlMs: Number(process.env.ADMIN_SESSION_TTL_MS || 8 * 60 * 60 * 1000),
  supabaseUrl: required("SUPABASE_URL").replace(/\/$/, ""),
  supabaseSecretKey: required("SUPABASE_SECRET_KEY"),
};
