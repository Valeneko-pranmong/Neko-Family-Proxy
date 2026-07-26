import { API_BASE } from "./config.js";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = {};
  }
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

export const health = () => request("/api/health");

export const login = (email, password) =>
  request("/api/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const logout = () => request("/api/logout", { method: "POST" });

export const loadResource = (resource) =>
  request(`/api/admin?resource=${encodeURIComponent(resource)}`);

export const runAction = (payload) =>
  request("/api/admin", {
    method: "POST",
    body: JSON.stringify(payload),
  });
