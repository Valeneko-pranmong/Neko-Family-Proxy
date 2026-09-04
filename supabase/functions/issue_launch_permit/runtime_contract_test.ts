import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const directory = new URL("./", import.meta.url);

async function source(name: string): Promise<string> {
  return readFile(new URL(name, directory), "utf8");
}

test("runtime validates the bearer token with Supabase Auth", async () => {
  const index = await source("index.ts");
  assert.match(index, /auth\.getUser\(accessToken\)/);
  assert.match(index, /data\.user\.is_anonymous === true/);
  assert.doesNotMatch(index, /service[_-]?role/i);
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
