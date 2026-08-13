from __future__ import annotations

from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260813120000_neko_auth_lite_first_active_session_wins.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def claim_definition(sql: str) -> str:
    start = sql.index("create or replace function launcher.claim_session(")
    end = sql.index("\n$$;", start) + len("\n$$;")
    return sql[start:end]


def permit_definition(sql: str) -> str:
    start = sql.index("create or replace function launcher.authorize_launch_permit(")
    end = sql.index("\n$$;", start) + len("\n$$;")
    return sql[start:end]


def test_lite_claim_preserves_first_fresh_session_without_mutating_it() -> None:
    claim = claim_definition(migration_sql())

    assert "pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0))" in claim
    assert "for update" in claim
    assert "last_seen_at > now() - interval '90 seconds'" in claim
    assert "sessionalreadyactive" in claim
    assert "replaced_by_new_session" not in claim
    assert "update public.launcher_sessions\n  set revoked_at = now()" in claim


def test_lite_claim_closes_only_a_stale_session_before_acquiring() -> None:
    claim = claim_definition(migration_sql())

    assert "last_seen_at <= now() - interval '90 seconds'" in claim
    assert "reason', 'stale_recovered'" in claim
    assert "insert into public.launcher_sessions(user_id, installation_id, license_id)" in claim


def test_lite_session_controls_bind_exact_live_auth_session_and_keep_stale_timeout() -> None:
    sql = migration_sql()

    for name in ("heartbeat_session", "release_session"):
        start = sql.index(f"create or replace function launcher.{name}(")
        end = sql.index("\n$$;", start)
        definition = sql[start:end]
        assert "auth.jwt() ->> 'session_id'" in definition
        assert "s.auth_session_id = v_auth_session_id" in definition
        assert "a.id = v_auth_session_id" in definition
        assert "a.user_id = v_user_id" in definition
    assert "last_seen_at > now() - interval '90 seconds'" in sql


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
    assert "sessionmismatch" in permit
    assert "heartbeatstale" in permit
    assert "entitlementinactive" in permit
    assert "launch_permit_reservations" not in permit
    assert "launch_permit_rate_events" not in permit


def test_lite_migration_retires_two_argument_s0_permit_rpc_and_keeps_index() -> None:
    sql = migration_sql()

    assert "drop function if exists launcher.authorize_launch_permit(text, text)" in sql
    assert "launcher_sessions_one_active_per_user_idx" in sql
    assert "where (revoked_at is null)" in sql
    assert "grant execute on function launcher.authorize_launch_permit(text) to authenticated" in sql
    assert "revoke all on function launcher.authorize_launch_permit(text) from public, anon" in sql
