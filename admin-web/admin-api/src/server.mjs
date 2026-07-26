import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import {
  authenticateAdmin,
  clearSessionCookie,
  createSession,
  deleteSession,
  getSession,
  sessionCookie,
} from "./auth.mjs";
import { config } from "./config.mjs";
import { getResource, performAction } from "./routes/admin.mjs";

const root = fileURLToPath(new URL("../../standalone/dist", import.meta.url));
const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

function parseCookies(request) {
  return Object.fromEntries(
    (request.headers.cookie || "")
      .split(";")
      .map((part) => part.trim().split("="))
      .filter(([key, value]) => key && value)
      .map(([key, ...value]) => [key, value.join("=")]),
  );
}

function sendJson(response, status, body, headers = {}) {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    ...headers,
  });
  response.end(JSON.stringify(body));
}

function sendError(response, status, message) {
  sendJson(response, status, { ok: false, error: message });
}

async function bodyJson(request) {
  let text = "";
  for await (const chunk of request) {
    text += chunk;
    if (text.length > 1024 * 1024) throw new Error("Request too large");
  }
  if (!text) return {};
  return JSON.parse(text);
}

function requireSession(request, response) {
  const session = getSession(parseCookies(request).admin_session);
  if (!session) {
    sendError(response, 401, "Admin login required");
    return null;
  }
  return session;
}

function serveStatic(request, response) {
  const pathname = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  const requested = pathname === "/" ? "/neko-control.html" : pathname;
  const file = normalize(join(root, requested));
  if (!file.startsWith(root) || !existsSync(file) || !statSync(file).isFile()) {
    sendError(response, 404, "Not found");
    return;
  }
  response.writeHead(200, {
    "Content-Type": contentTypes[extname(file)] || "application/octet-stream",
    "Cache-Control": "no-store",
  });
  createReadStream(file).pipe(response);
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${config.host}:${config.port}`);
    if (request.method === "GET" && url.pathname === "/api/health") {
      return sendJson(response, 200, { ok: true, host: config.host, port: config.port });
    }
    if (request.method === "POST" && url.pathname === "/api/login") {
      const body = await bodyJson(request);
      if (typeof body.email !== "string" || typeof body.password !== "string") {
        return sendError(response, 400, "Email and password are required");
      }
      try {
        const viewer = await authenticateAdmin(body.email.trim(), body.password);
        return sendJson(response, 200, { ok: true, viewer }, {
          "Set-Cookie": sessionCookie(createSession(viewer)),
        });
      } catch (error) {
        return sendError(response, error.status || 502, error.message || "Login failed");
      }
    }
    if (request.method === "POST" && url.pathname === "/api/logout") {
      deleteSession(parseCookies(request).admin_session);
      return sendJson(response, 200, { ok: true }, { "Set-Cookie": clearSessionCookie() });
    }
    if (url.pathname === "/api/admin") {
      const session = requireSession(request, response);
      if (!session) return;
      if (request.method === "GET") {
        const resource = url.searchParams.get("resource") || "overview";
        const data = await getResource(resource);
        return sendJson(response, 200, { ok: true, resource, data });
      }
      if (request.method === "POST") {
        const result = await performAction(await bodyJson(request), session.viewer);
        return sendJson(response, 200, { ok: true, ...result });
      }
      return sendError(response, 405, "Method not allowed");
    }
    if (request.method === "GET") return serveStatic(request, response);
    return sendError(response, 404, "Not found");
  } catch (error) {
    console.error(error);
    sendError(response, 500, error instanceof Error ? error.message : "Server error");
  }
});

server.listen(config.port, config.host, () => {
  console.log(`Neko Control local server: http://${config.host}:${config.port}/`);
});

process.on("SIGINT", () => server.close(() => process.exit(0)));
process.on("SIGTERM", () => server.close(() => process.exit(0)));
