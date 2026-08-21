from __future__ import annotations

from pathlib import Path


MIGRATIONS = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
)
LITE_MIGRATION = MIGRATIONS / "20260813120000_neko_auth_lite_first_active_session_wins.sql"
LATEST_CLAIM_MIGRATION = MIGRATIONS / "20260821120000_neko_auth_lite_latest_claim_wins.sql"


def migration_sql() -> str:
    return "\n".join(
        migration.read_text(encoding="utf-8").lower()
        for migration in (LITE_MIGRATION, LATEST_CLAIM_MIGRATION)
    )


def claim_definition(sql: str) -> str:
    start = sql.rindex("create or replace function launcher.claim_session(")
    end = sql.index("\n$$;", start) + len("\n$$;")
    return sql[start:end]


def permit_definition(sql: str) -> str:
    start = sql.rindex("create or replace function launcher.authorize_launch_permit(")
    end = sql.index("\n$$;", start) + len("\n$$;")
    return sql[start:end]


def test_lite_claim_atomically_replaces_each_fresh_active_session() -> None:
    claim = claim_definition(migration_sql())

    assert "set search_path = ''" in claim
    assert "pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0))" in claim
    assert "for update" in claim
    assert "session_already_active" not in claim
    assert "stale_recovered" not in claim
    assert "with revoked_sessions as" in claim
    assert "update public.launcher_sessions" in claim
    assert "set revoked_at = now()" in claim
    assert "where user_id = v_user_id" in claim
    assert "and revoked_at is null" in claim
    assert "reason', 'replaced_by_new_session'" in claim
    assert "replacement_installation_id', v_installation.id" in claim


def test_lite_claim_reuses_remembered_installations_without_device_lock() -> None:
    claim = claim_definition(migration_sql())

    assert "where i.user_id = v_user_id" in claim
    assert "and i.installation_key_hash = p_installation_key_hash" in claim
    assert "set last_seen_at = now()," in claim
    assert "revoked_at = null" in claim
    assert "installation_revoked" not in claim
    assert "device_limit_reached" not in claim
    assert "insert into public.launcher_sessions(user_id, installation_id, license_id)" in claim


def test_lite_session_controls_bind_exact_live_auth_session_and_keep_stale_timeout() -> None:
    sql = migration_sql()

    for name in ("heartbeat_session", "release_session"):
        start = sql.rindex(f"create or replace function launcher.{name}(")
        end = sql.index("\n$$;", start)
        definition = sql[start:end]
        assert "auth.jwt() ->> 'session_id'" in definition
        assert "s.auth_session_id = v_auth_session_id" in definition
        assert "a.id = v_auth_session_id" in definition
        assert "a.user_id = v_user_id" in definition
    assert "last_seen_at > now() - interval '90 seconds'" in sql


def test_lite_release_serializes_with_claim_and_permit_authorization() -> None:
    sql = migration_sql()
    start = sql.rindex("create or replace function launcher.release_session(")
    end = sql.index("\n$$;", start)
    release = sql[start:end]

    assert "pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0))" in release


def test_lite_permit_rpc_has_one_challenge_input_and_exact_auth_session_binding() -> None:
    sql = migration_sql()
    permit = permit_definition(sql)

    assert "p_challenge text" in permit
    assert "p_product_code" not in permit
    assert "pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0))" in permit
    assert "s.auth_session_id = v_auth_session_id" in permit
    assert "a.id = v_auth_session_id" in permit
    assert "a.user_id = v_user_id" in permit
    assert "last_seen_at > now() - interval '90 seconds'" in permit
    assert "sessioninactive" in permit
    assert "heartbeatstale" in permit
    assert "entitlementinactive" in permit
    assert "launch_permit_reservations" not in permit
    assert "launch_permit_rate_events" not in permit


def test_lite_permit_classifies_superseded_auth_session_as_inactive() -> None:
    permit = permit_definition(migration_sql())
    inactive_branch = permit[permit.index("if v_state is null then") :]

    assert "sessioninactive" in inactive_branch
    assert "sessionmismatch" not in permit


def test_lite_migration_retires_two_argument_s0_permit_rpc_and_keeps_index() -> None:
    sql = migration_sql()

    assert "drop function if exists launcher.authorize_launch_permit(text, text)" in sql
    assert "launcher_sessions_one_active_per_user_idx" in sql
    assert "where (revoked_at is null)" in sql
    assert "grant execute on function launcher.authorize_launch_permit(text) to authenticated" in sql
    assert "revoke all on function launcher.authorize_launch_permit(text) from public, anon" in sql
