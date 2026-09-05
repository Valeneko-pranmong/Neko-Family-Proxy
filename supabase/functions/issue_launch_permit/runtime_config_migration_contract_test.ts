import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const originalMigrationUrl = new URL(
  "../../migrations/20260904130000_runtime_proxy_config_v1.sql",
  import.meta.url,
);
const correctiveMigrationUrl = new URL(
  "../../migrations/20260905010000_fix_runtime_proxy_config_ascii_validation.sql",
  import.meta.url,
);

async function migration(url: URL): Promise<string> {
  return await readFile(url, "utf8");
}

function functionDefinition(sql: string, name: string): string {
  const marker = `create or replace function launcher.${name}`;
  const start = sql.toLowerCase().indexOf(marker);
  assert.ok(start >= 0, `${name} missing`);
  const end = sql.indexOf("\n$$;", start);
  assert.ok(end >= 0, `${name} body missing`);
  return sql.slice(start, end + 4);
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(
    new Uint8Array(digest),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

test("applied runtime config v1 migration remains byte unchanged", async () => {
  assert.equal(
    await sha256Hex(await migration(originalMigrationUrl)),
    "b6db37170f167aa1debd5d952e2f495882b20a27373bf8e3dcbb3b8e44e8fb27",
  );
});

test("corrective migration uses explicit printable ASCII validation without regex", async () => {
  const sql = await migration(correctiveMigrationUrl);
  const helper = functionDefinition(
    sql,
    "runtime_proxy_config_text_is_printable_ascii",
  );

  assert.doesNotMatch(sql, /\\x[0-9a-f]{2}/i);
  assert.doesNotMatch(sql, /~/);
  assert.doesNotMatch(sql, /regexp_/i);
  assert.match(helper, /p_value is null/i);
  assert.match(helper, /length\(p_value\) not between 1 and p_max_length/i);
  assert.match(
    helper,
    /for v_position in 1\.\.pg_catalog\.length\(p_value\) loop/i,
  );
  assert.match(
    helper,
    /pg_catalog\.ascii\(pg_catalog\.substr\(p_value, v_position, 1\)\)/i,
  );
  assert.match(helper, /not between 32 and 126/i);

  for (
    const [column, limit] of [
      ["endpoint_id", 64],
      ["host", 253],
      ["cipher", 64],
      ["credential", 256],
    ] as const
  ) {
    assert.match(
      sql,
      new RegExp(
        `check \\(launcher\\.runtime_proxy_config_text_is_printable_ascii\\(${column}, ${limit}\\)\\)`,
        "i",
      ),
    );
  }
});

test("corrective publish RPC validates bounds and preserves publication semantics", async () => {
  const sql = await migration(correctiveMigrationUrl);
  const publish = functionDefinition(sql, "publish_runtime_proxy_config");

  assert.match(
    publish,
    /publish_runtime_proxy_config\(\s*p_endpoint_id text,\s*p_host text,\s*p_port integer,\s*p_cipher text,\s*p_credential text\s*\)/i,
  );
  assert.match(
    publish,
    /returns jsonb\s*language plpgsql\s*security definer\s*set search_path = ''/i,
  );
  for (
    const [parameter, limit, error] of [
      ["p_endpoint_id", 64, "invalid_endpoint_id"],
      ["p_host", 253, "invalid_host"],
      ["p_cipher", 64, "invalid_cipher"],
      ["p_credential", 256, "invalid_credential"],
    ] as const
  ) {
    assert.match(
      publish,
      new RegExp(
        `if not launcher\\.runtime_proxy_config_text_is_printable_ascii\\(${parameter}, ${limit}\\) then\\s*raise exception '${error}'`,
        "i",
      ),
    );
  }
  assert.match(
    publish,
    /if p_port is null or p_port < 1 or p_port > 65535 then\s*raise exception 'invalid_port'/i,
  );
  assert.match(
    publish,
    /pg_catalog\.pg_advisory_xact_lock\(\s*pg_catalog\.hashtextextended\('launcher\.runtime_proxy_config_publication', 0\)\s*\)/i,
  );
  assert.match(
    publish,
    /pg_catalog\.coalesce\(pg_catalog\.max\(config_version\), 0\) \+ 1/i,
  );
  assert.match(publish, /insert into launcher\.runtime_proxy_config_versions/i);
  assert.match(publish, /on conflict \(singleton_id\) do update/i);

  const safeReturn = publish.slice(
    publish.toLowerCase().lastIndexOf("return pg_catalog.jsonb_build_object("),
  );
  assert.match(safeReturn, /'config_version'/i);
  assert.match(safeReturn, /'endpoint_id'/i);
  assert.match(safeReturn, /'published_at'/i);
  assert.doesNotMatch(safeReturn, /p_credential|'credential'/i);
});

test("corrective migration keeps publish execution service-role-only", async () => {
  const sql = await migration(correctiveMigrationUrl);
  const replacements = Array.from(
    sql.matchAll(/create or replace function\s+launcher\.([a-z_]+)\s*\(/gi),
    (match) => match[1],
  );

  assert.deepEqual(replacements, [
    "runtime_proxy_config_text_is_printable_ascii",
    "publish_runtime_proxy_config",
  ]);
  assert.match(
    sql,
    /revoke all on function launcher\.publish_runtime_proxy_config\(text, text, integer, text, text\)\s+from public, anon, authenticated, service_role;/i,
  );
  assert.match(
    sql,
    /grant execute on function launcher\.publish_runtime_proxy_config\(text, text, integer, text, text\)\s+to service_role;/i,
  );
  assert.doesNotMatch(
    sql,
    /grant execute[\s\S]*to (?:public|anon|authenticated)/i,
  );
  assert.doesNotMatch(
    sql,
    /create or replace function launcher\.get_active_runtime_proxy_config/i,
  );
  assert.doesNotMatch(sql, /runtime_proxy_config_versions_prevent_mutation/i);
});
