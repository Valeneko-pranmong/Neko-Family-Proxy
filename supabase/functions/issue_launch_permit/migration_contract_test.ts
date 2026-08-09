import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../../migrations/20260809150000_bind_permits_to_auth_sessions.sql",
  import.meta.url,
);

async function migration(): Promise<string> {
  return readFile(migrationUrl, "utf8");
}

test("migration binds Launcher sessions to validated Supabase Auth sessions", async () => {
  const sql = await migration();
  assert.match(sql, /add column auth_session_id uuid/i);
  assert.match(sql, /auth\.jwt\(\)\s*->>\s*'session_id'/i);
  assert.match(sql, /before insert on public\.launcher_sessions/i);
  assert.match(sql, /new\.auth_session_id\s*:=\s*v_auth_session_id/i);
});

test("permit authorization RPC checks the complete authoritative state", async () => {
  const sql = await migration();
  assert.match(
    sql,
    /create or replace function launcher\.authorize_launch_permit/is,
  );
  assert.match(sql, /s\.revoked_at is null/i);
  assert.match(sql, /s\.auth_session_id = v_auth_session_id/i);
  assert.match(sql, /pr\.status = 'active'/i);
  assert.match(sql, /p\.is_active/i);
  assert.match(sql, /l\.status = 'active'/i);
  assert.match(sql, /l\.valid_from <= now\(\)/i);
  assert.match(sql, /l\.valid_until > now\(\)/i);
  assert.match(sql, /s\.last_seen_at > now\(\) - interval '90 seconds'/i);
  assert.match(sql, /l\.user_id = s\.user_id/i);
  assert.match(sql, /i\.user_id = s\.user_id/i);
});

test("RPC is narrow, fixed-search-path, and authenticated-only", async () => {
  const sql = await migration();
  assert.match(
    sql,
    /security definer\s+set search_path = ''/is,
  );
  assert.match(
    sql,
    /revoke all on function launcher\.authorize_launch_permit\(text, text\)\s+from public/is,
  );
  assert.match(
    sql,
    /revoke all on function launcher\.authorize_launch_permit\(text, text\)\s+from anon/is,
  );
  assert.match(
    sql,
    /grant execute on function launcher\.authorize_launch_permit\(text, text\)\s+to authenticated/is,
  );
  assert.doesNotMatch(
    sql,
    /grant\s+(select|insert|update|delete|all).*public\.(launcher_sessions|licenses|installations)/is,
  );
});

test("single-active-session index and no-permanent-machine-lock policy remain intact", async () => {
  const sql = await migration();
  assert.match(sql, /launcher_sessions_one_active_per_user_idx/i);
  assert.doesNotMatch(sql, /where\s+i\.revoked_at\s+is\s+null/i);
  assert.doesNotMatch(sql, /installation_revoked|device_limit_reached/i);
});

test("migration text declares Auth checks, serialized replay reservation, and durable user rate accounting", async () => {
  const sql = await migration();
  assert.match(sql, /join auth\.sessions a on a\.id = v_auth_session_id/i);
  assert.match(sql, /a\.user_id = v_user_id/i);
  assert.match(sql, /a\.not_after is null or a\.not_after > now\(\)/i);
  assert.match(
    sql,
    /pg_advisory_xact_lock\(hashtextextended\(v_user_id::text, 0\)\)/i,
  );
  assert.match(sql, /create table launcher\.launch_permit_reservations/i);
  assert.match(
    sql,
    /auth_session_id uuid not null references auth\.sessions\(id\) on delete cascade/i,
  );
  assert.match(sql, /unique \(auth_session_id, challenge\)/i);
  assert.match(sql, /create table launcher\.launch_permit_rate_events/i);
  assert.match(
    sql,
    /rate_events[\s\S]*user_id uuid not null references auth\.users\(id\) on delete cascade/i,
  );
  assert.doesNotMatch(
    sql,
    /rate_events[\s\S]*auth_session_id[\s\S]*references auth\.sessions/i,
  );
  assert.match(
    sql,
    /from launcher\.launch_permit_rate_events r[\s\S]*r\.issued_at > now\(\) - interval '1 minute'/i,
  );
  assert.match(sql, /v_recent_issuances >= 10/i);
  assert.match(sql, /insert into launcher\.launch_permit_reservations/i);
  assert.match(
    sql,
    /insert into launcher\.launch_permit_rate_events\(user_id\)/i,
  );
});
