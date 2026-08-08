from __future__ import annotations

from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260808143000_harden_session_policy_admin_operations.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_heartbeat_checks_the_license_bound_to_the_session() -> None:
    sql = migration_sql()

    assert "create or replace function launcher.heartbeat_session(" in sql
    assert "l.id = s.license_id" in sql
    assert "l.user_id = s.user_id" in sql
    assert "l.status = 'active'" in sql
    assert "l.valid_from <= now()" in sql
    assert "l.valid_until > now()" in sql
    assert "set search_path = public, launcher, pg_temp" in sql


def test_admin_installation_revocation_is_atomic_and_audited() -> None:
    sql = migration_sql()

    assert "create or replace function launcher.admin_revoke_installation(" in sql
    assert "perform launcher.assert_admin_actor(p_actor_id)" in sql
    assert "update public.installations" in sql
    assert "update public.launcher_sessions" in sql
    assert "'admin_installation_revoked'" in sql
    assert "scope', 'installation'" in sql
    assert "set search_path = public, launcher, pg_temp" in sql


def test_admin_installation_rpc_is_service_role_only() -> None:
    sql = migration_sql()

    signature = "launcher.admin_revoke_installation(uuid, uuid)"
    assert f"revoke all on function {signature}" in sql
    assert "from public, anon, authenticated" in sql
    assert f"grant execute on function {signature}" in sql
    assert "to service_role" in sql


def test_one_active_session_index_is_preserved() -> None:
    sql = migration_sql()

    assert "drop index" not in sql
    assert "launcher_sessions_one_active_per_user_idx" in sql
    assert "where revoked_at is null" in sql
