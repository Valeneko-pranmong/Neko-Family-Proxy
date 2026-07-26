import { config } from "./config.mjs";

function headersFor(schema) {
  const headers = {
    apikey: config.supabaseSecretKey,
    Authorization: `Bearer ${config.supabaseSecretKey}`,
    "Content-Type": "application/json",
  };
  if (schema) {
    headers["Accept-Profile"] = schema;
    headers["Content-Profile"] = schema;
  }
  return headers;
}

async function requestJson(path, options = {}) {
  const { schema, ...init } = options;
  const response = await fetch(`${config.supabaseUrl}${path}`, {
    cache: "no-store",
    ...init,
    headers: { ...headersFor(schema), ...(init.headers || {}) },
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "message" in body ? body.message : "";
    throw new Error(`Supabase request failed (${response.status})${detail ? `: ${detail}` : ""}`);
  }
  return body;
}

function queryString(query) {
  const params = new URLSearchParams(query);
  return params.toString() ? `?${params}` : "";
}

export const tableGet = (table, query = {}) =>
  requestJson(`/rest/v1/${table}${queryString(query)}`);

export const tablePost = (table, payload) =>
  requestJson(`/rest/v1/${table}`, {
    method: "POST",
    headers: { Prefer: "return=representation" },
    body: JSON.stringify(payload),
  });

export const tablePatch = (table, query, payload) =>
  requestJson(`/rest/v1/${table}${queryString(query)}`, {
    method: "PATCH",
    headers: { Prefer: "return=representation" },
    body: JSON.stringify(payload),
  });

export const tableCount = async (table, query = {}) => {
  const response = await fetch(
    `${config.supabaseUrl}/rest/v1/${table}${queryString({
      select: "id",
      ...query,
    })}`,
    {
      method: "HEAD",
      headers: { ...headersFor(), Prefer: "count=exact" },
    },
  );
  if (!response.ok) throw new Error(`Supabase count failed (${response.status})`);
  const range = response.headers.get("content-range") || "";
  const count = range.split("/")[1];
  return count && count !== "*" ? Number(count) : 0;
};

export const authAdminGet = (path, query = {}) =>
  requestJson(`/auth/v1/admin/${path}${queryString(query)}`);
