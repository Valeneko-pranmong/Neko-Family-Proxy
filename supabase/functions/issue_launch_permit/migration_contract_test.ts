import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const liteMigrationUrl = new URL(
  "../../migrations/20260813120000_neko_auth_lite_first_active_session_wins.sql",
  import.meta.url,
);
const latestClaimMigrationUrl = new URL(
  "../../migrations/20260821120000_neko_auth_lite_latest_claim_wins.sql",
  import.meta.url,
);

async function migration(): Promise<string> {
  const migrations = await Promise.all([
    readFile(liteMigrationUrl, "utf8"),
    readFile(latestClaimMigrationUrl, "utf8"),
  ]);
  return migrations.join("\n");
}

function definition(sql: string, name: string): string {
  const marker = `create or replace function launcher.${name}`;
  const start = sql.toLowerCase().lastIndexOf(marker);
  assert.ok(start >= 0, `${name} missing`);
  const end = sql.indexOf("\n$$;", start);
  assert.ok(end >= 0, `${name} body missing`);
  return sql.slice(start, end + 4);
}

test("Lite claim serializes and atomically replaces every active session", async () => {
  const claim = definition(await migration(), "claim_session(");
  assert.match(
    claim,
    /pg_advisory_xact_lock\(hashtextextended\(v_user_id::text, 0\)\)/i,
  );
  assert.match(claim, /for update/i);
  assert.doesNotMatch(claim, /SESSION_ALREADY_ACTIVE|stale_recovered/i);
  assert.match(claim, /with revoked_sessions as/i);
  assert.match(
    claim,
    /update public\.launcher_sessions[\s\S]*where user_id = v_user_id[\s\S]*and revoked_at is null/i,
  );
  assert.match(claim, /replaced_by_new_session/i);
  assert.match(claim, /replacement_installation_id/i);
});

test("Lite claim preserves remembered installation reuse", async () => {
  const claim = definition(await migration(), "claim_session(");
  assert.match(
    claim,
    /where i\.user_id = v_user_id[\s\S]*i\.installation_key_hash = p_installation_key_hash/i,
  );
  assert.match(claim, /set last_seen_at = now\(\)[\s\S]*revoked_at = null/i);
  assert.doesNotMatch(claim, /installation_revoked|device_limit_reached/i);
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
    /SessionInactive|HeartbeatStale|EntitlementInactive/i,
  );
});

test("Lite permit classifies a superseded Auth session as inactive", async () => {
  const permit = definition(await migration(), "authorize_launch_permit(");
  assert.match(
    permit,
    /if v_state is null then[\s\S]*return jsonb_build_object\('error', 'SessionInactive'\)/i,
  );
  assert.doesNotMatch(permit, /SessionMismatch/i);
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
