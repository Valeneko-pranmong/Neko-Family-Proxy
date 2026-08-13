import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../../migrations/20260813120000_neko_auth_lite_first_active_session_wins.sql",
  import.meta.url,
);

async function migration(): Promise<string> {
  return readFile(migrationUrl, "utf8");
}

function definition(sql: string, name: string): string {
  const marker = `create or replace function launcher.${name}`;
  const start = sql.toLowerCase().indexOf(marker);
  assert.ok(start >= 0, `${name} missing`);
  const end = sql.indexOf("\n$$;", start);
  assert.ok(end >= 0, `${name} body missing`);
  return sql.slice(start, end + 4);
}

test("Lite claim serializes and preserves fresh first session", async () => {
  const claim = definition(await migration(), "claim_session(");
  assert.match(
    claim,
    /pg_advisory_xact_lock\(hashtextextended\(v_user_id::text, 0\)\)/i,
  );
  assert.match(claim, /for update/i);
  assert.match(claim, /last_seen_at > now\(\) - interval '90 seconds'/i);
  assert.match(claim, /SESSION_ALREADY_ACTIVE/i);
  assert.doesNotMatch(claim, /replaced_by_new_session/i);
  assert.match(claim, /last_seen_at <= now\(\) - interval '90 seconds'/i);
  assert.match(claim, /stale_recovered/i);
});

test("Lite controls bind exact live Auth session", async () => {
  const sql = await migration();
  for (
    const name of [
      "heartbeat_session(p_session_id uuid)",
      "release_session(p_session_id uuid)",
    ]
  ) {
    const control = definition(sql, name);
    assert.match(control, /auth\.jwt\(\)\s*->>\s*'session_id'/i);
    assert.match(control, /s\.auth_session_id = v_auth_session_id/i);
    assert.match(
      control,
      /a\.id = v_auth_session_id[\s\S]*a\.user_id = v_user_id/i,
    );
  }
});

test("Lite permit RPC has only challenge input and no S0 ledger dependence", async () => {
  const permit = definition(await migration(), "authorize_launch_permit(");
  assert.match(permit, /authorize_launch_permit\(p_challenge text\)/i);
  assert.doesNotMatch(
    permit,
    /p_product_code|launch_permit_reservations|launch_permit_rate_events/i,
  );
  assert.match(
    permit,
    /pg_advisory_xact_lock\(hashtextextended\(v_user_id::text, 0\)\)/i,
  );
  assert.match(permit, /s\.auth_session_id = v_auth_session_id/i);
  assert.match(
    permit,
    /SessionMismatch|SessionInactive|HeartbeatStale|EntitlementInactive/i,
  );
});

test("Lite RPC grants stay authenticated-only and active index remains enforced", async () => {
  const sql = await migration();
  assert.match(
    sql,
    /revoke all on function launcher\.authorize_launch_permit\(text\) from public, anon/i,
  );
  assert.match(
    sql,
    /grant execute on function launcher\.authorize_launch_permit\(text\) to authenticated/i,
  );
  assert.match(sql, /launcher_sessions_one_active_per_user_idx/i);
  assert.match(sql, /where \(revoked_at is null\)/i);
});
