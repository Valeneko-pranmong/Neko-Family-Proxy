import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const directory = new URL("./", import.meta.url);

async function source(name: string): Promise<string> {
  return readFile(new URL(name, directory), "utf8");
}

test("runtime validates the bearer token with Supabase Auth using publishable key only", async () => {
  const index = await source("index.ts");
  assert.match(index, /auth\.getUser\(accessToken\)/);
  assert.match(index, /data\.user\.is_anonymous === true/);
  assert.match(index, /publishableKey/);
  const clientForRegex = /function clientFor\(accessToken: string\)\s*\{[\s\S]*?\n\}/;
  const clientForMatch = index.match(clientForRegex);
  assert.ok(clientForMatch, "clientFor function should exist");
  assert.match(clientForMatch[0], /publishableKey/);
  assert.doesNotMatch(clientForMatch[0], /service[_-]?role/i);
});

test("runtime uses caller-scoped authenticated RPC and server signing configuration", async () => {
  const index = await source("index.ts");
  assert.match(index, /Authorization: `Bearer \$\{accessToken\}`/);
  assert.match(index, /rpc\("authorize_launch_permit"/);
  assert.match(index, /p_challenge: challenge/);
  assert.match(index, /Deno\.env\.get\("RS256_PRIVATE_KEY"\)/);
  assert.match(index, /Deno\.env\.get\("RS256_KID"\)/);
});

test("service contract revision is runtime-config-v1", async () => {
  const service = await source("service.ts");
  assert.match(service, /runtime-config-v1/);
});

test("Supabase gateway JWT verification remains enabled", async () => {
  const config = await readFile(
    new URL("../../config.toml", import.meta.url),
    "utf8",
  );
  assert.match(
    config,
    /\[functions\.issue_launch_permit\][\s\S]*verify_jwt\s*=\s*true/,
  );
});

test("runtime uses dedicated admin client with SUPABASE_SERVICE_ROLE_KEY for active config only", async () => {
  const index = await source("index.ts");
  assert.match(index, /Deno\.env\.get\("SUPABASE_SERVICE_ROLE_KEY"\)/);
  assert.match(index, /function adminClient\(\)/);
  assert.match(index, /async function loadRuntimeConfig\(\)/);
  assert.match(index, /\.schema\("launcher"\)\s*\.rpc\("get_active_runtime_proxy_config"\)/);
  assert.match(index, /createIssueLaunchPermitHandler\(\{[\s\S]*?loadRuntimeConfig,[\s\S]*?\}\)/);
  assert.doesNotMatch(index, /console\.(log|error|warn|info)\(.*service.*role/i);
});

test("source contract proves service-role key is never leaked, logged, or returned in payloads", async () => {
  const index = await source("index.ts");
  const service = await source("service.ts");
  assert.doesNotMatch(index, /console\.[a-z]+\([^)]*serviceRoleKey[^)]*\)/);
  assert.doesNotMatch(index, /console\.[a-z]+\([^)]*SUPABASE_SERVICE_ROLE_KEY[^)]*\)/);
  assert.doesNotMatch(service, /console\.[a-z]+\([^)]*credential[^)]*\)/);
  assert.doesNotMatch(index, /throw new Error\(.*serviceRoleKey.*\)/i);
  assert.doesNotMatch(index, /throw new Error\(.*\$\{.*\}.*\)/);
  assert.doesNotMatch(index, /json\([^)]*serviceRoleKey/);
  assert.doesNotMatch(service, /service_role/i);
});

test("source contract verifies parseRuntimeConfigRpcResult logic and shape handling", async () => {
  const index = await source("index.ts");
  assert.match(index, /function parseRuntimeConfigRpcResult\(/);
  assert.match(index, /Array\.isArray\(data\)/);
  assert.match(index, /throw new Error\("backend dependency unavailable"\)/);
  assert.match(index, /typeof row\.config_version !== "number"/);
  assert.match(index, /typeof row\.endpoint_id !== "string"/);
  assert.match(index, /typeof row\.host !== "string"/);
  assert.match(index, /typeof row\.port !== "number"/);
  assert.match(index, /typeof row\.protocol !== "string"/);
  assert.match(index, /typeof row\.cipher !== "string"/);
  assert.match(index, /typeof row\.credential !== "string"/);
});

test("parseRuntimeConfigRpcResult behavioral test accepts exactly one valid object and throws generic error", async () => {
  const index = await source("index.ts");
  const funcMatch = index.match(
    /function parseRuntimeConfigRpcResult\(data: unknown\): RuntimeProxyConfigRecord \{([\s\S]*?)\n\}/
  );
  assert.ok(funcMatch, "parseRuntimeConfigRpcResult must exist in index.ts");

  const cleanBody = funcMatch[1].replace(/ as Record<string, unknown>/g, "");
  const parse = new Function("data", cleanBody);

  const validRecord = {
    config_version: 1,
    endpoint_id: "endpoint-a",
    host: "proxy.local",
    port: 8388,
    protocol: "shadowsocks",
    cipher: "aes-256-gcm",
    credential: "secret-token-value",
    published_at: "2026-09-04T00:00:00Z",
  };

  // Valid object
  assert.deepEqual(parse(validRecord), validRecord);

  // Missing / null / undefined / primitives
  assert.throws(() => parse(null), /backend dependency unavailable/);
  assert.throws(() => parse(undefined), /backend dependency unavailable/);
  assert.throws(() => parse("string"), /backend dependency unavailable/);
  assert.throws(() => parse(42), /backend dependency unavailable/);

  // Array / multiple items
  assert.throws(() => parse([]), /backend dependency unavailable/);
  assert.throws(() => parse([validRecord]), /backend dependency unavailable/);
  assert.throws(() => parse([validRecord, validRecord]), /backend dependency unavailable/);

  // Malformed objects
  assert.throws(() => parse({}), /backend dependency unavailable/);
  assert.throws(() => parse({ ...validRecord, config_version: "1" }), /backend dependency unavailable/);
  assert.throws(() => parse({ ...validRecord, host: 123 }), /backend dependency unavailable/);
  assert.throws(() => parse({ ...validRecord, credential: null }), /backend dependency unavailable/);
  assert.throws(() => parse({ ...validRecord, port: "8388" }), /backend dependency unavailable/);
});
