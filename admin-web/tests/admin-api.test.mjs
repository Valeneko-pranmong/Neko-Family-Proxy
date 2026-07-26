import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import test from "node:test";

const port = 8799;
const supabasePort = 8800;
const base = `http://127.0.0.1:${port}`;

async function waitForHealth() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const response = await fetch(`${base}/api/health`);
      if (response.ok) return;
    } catch {
      // The child process may still be starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("Local Admin API did not start");
}

function createFakeSupabase() {
  return createServer(async (request, response) => {
    const url = new URL(request.url, `http://127.0.0.1:${supabasePort}`);
    if (request.method === "POST" && url.pathname === "/auth/v1/token") {
      let text = "";
      for await (const chunk of request) text += chunk;
      const body = JSON.parse(text);
      if (body.password !== "correct-pass") {
        response.writeHead(400, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ code: "invalid_credentials", msg: "Invalid login credentials" }));
        return;
      }
      const id = body.email === "admin@example.com" ? "admin-id" : "customer-id";
      const now = new Date().toISOString();
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({
        access_token: "fake-access-token",
        token_type: "bearer",
        expires_in: 3600,
        refresh_token: "fake-refresh-token",
        user: {
          id,
          aud: "authenticated",
          role: "authenticated",
          email: body.email,
          email_confirmed_at: now,
          app_metadata: { provider: "email", providers: ["email"] },
          user_metadata: {},
          identities: [],
          created_at: now,
          updated_at: now,
          is_anonymous: false,
        },
      }));
      return;
    }
    if (request.method === "GET" && url.pathname === "/rest/v1/profiles") {
      const id = (url.searchParams.get("id") || "").replace(/^eq\./, "");
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify([{
        id,
        display_name: id === "admin-id" ? "Test Admin" : "Test Customer",
        role: id === "admin-id" ? "admin" : "customer",
      }]));
      return;
    }
    response.writeHead(404, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ message: "Not found" }));
  });
}

test("local admin API accepts Supabase credentials only for role admin", async () => {
  const fakeSupabase = createFakeSupabase();
  fakeSupabase.listen(supabasePort, "127.0.0.1");
  await once(fakeSupabase, "listening");
  const child = spawn(process.execPath, ["admin-api/src/server.mjs"], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      ADMIN_HOST: "127.0.0.1",
      ADMIN_PORT: String(port),
      SUPABASE_URL: `http://127.0.0.1:${supabasePort}`,
      SUPABASE_SECRET_KEY: "test-secret",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  try {
    await waitForHealth();
    const health = await fetch(`${base}/api/health`);
    assert.equal(health.status, 200);

    const wrongLogin = await fetch(`${base}/api/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "admin@example.com", password: "wrong" }),
    });
    assert.equal(wrongLogin.status, 401);

    const customerLogin = await fetch(`${base}/api/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "customer@example.com", password: "correct-pass" }),
    });
    assert.equal(customerLogin.status, 403);

    const unauthenticated = await fetch(`${base}/api/admin?resource=overview`);
    assert.equal(unauthenticated.status, 401);

    const login = await fetch(`${base}/api/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "admin@example.com", password: "correct-pass" }),
    });
    assert.equal(login.status, 200);
    assert.match(login.headers.get("set-cookie") || "", /admin_session=/);
    const loginBody = await login.json();
    assert.equal(loginBody.viewer.role, "admin");
    assert.equal(loginBody.viewer.email, "admin@example.com");
  } finally {
    child.kill();
    await once(child, "close").catch(() => {});
    fakeSupabase.close();
    await once(fakeSupabase, "close").catch(() => {});
  }
});
