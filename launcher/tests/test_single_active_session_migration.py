from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260809133000_remove_permanent_installation_lock.sql"
)


def migration_sql() -> str:
    if not MIGRATION.exists():
        return ""
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_claim_contract_treats_installations_as_reusable_history() -> None:
    sql = migration_sql()

    assert "create or replace function launcher.claim_session(" in sql
    assert "p_product_code text" in sql
    assert "p_installation_key_hash text" in sql
    assert "p_display_name text default null" in sql
    assert "returns jsonb" in sql
    assert "device_limit_reached" not in sql
    assert "count(*)" not in sql
    assert "raise exception 'installation_revoked'" not in sql
    assert "set last_seen_at = now()," in sql
    assert "revoked_at = null" in sql
    assert "'max_devices', v_max_devices" in sql
    assert "create unique index" not in sql
    assert "drop index" not in sql


def test_claim_contract_preserves_fail_closed_authorization_and_serialization() -> None:
    sql = migration_sql()

    assert "auth.uid()" in sql
    assert "account_restricted" in sql
    assert "license_invalid" in sql
    assert "p.is_active" in sql
    assert "l.status = 'active'" in sql
    assert "l.valid_from <= now()" in sql
    assert "l.valid_until > now()" in sql
    assert "^[0-9a-f]{64}$" in sql
    assert "pg_advisory_xact_lock" in sql
    assert sql.count("for share") >= 2
    assert "set search_path = public, launcher, pg_temp" in sql
    assert "revoke all on function launcher.claim_session(text, text, text) from public" in sql
    assert "revoke all on function launcher.claim_session(text, text, text) from anon" in sql
    assert "grant execute on function launcher.claim_session(text, text, text) to authenticated" in sql


def test_claim_replaces_only_sessions_and_records_audit_reason() -> None:
    sql = migration_sql()

    assert "update public.launcher_sessions" in sql
    assert "update public.installations set revoked_at" not in sql
    assert "'session_revoked'" in sql
    assert "'replaced_by_new_session'" in sql
    assert "'replacement_installation_id'" in sql
    assert "'session_claimed'" in sql
    assert "drop index" not in sql


def test_migration_clears_only_obsolete_installation_lock_state() -> None:
    sql = migration_sql()

    assert "update public.installations" in sql
    assert "set revoked_at = null" in sql
    assert "where revoked_at is not null" in sql
    assert "update public.profiles" not in sql
    assert "update public.licenses" not in sql
    assert "update public.launcher_sessions set revoked_at = null" not in sql
    assert "legacy/deprecated" in sql


def test_permanent_installation_admin_rpc_is_removed_but_history_is_preserved() -> None:
    sql = migration_sql()

    assert "drop function if exists launcher.admin_revoke_installation(uuid, uuid)" in sql
    assert "admin_installation_revoked" in sql
    assert "drop constraint" not in sql


def test_authoritative_one_active_session_index_is_verified_not_weakened() -> None:
    sql = migration_sql()

    assert "launcher_sessions_one_active_per_user_idx" in sql
    assert "i.indisunique" in sql
    assert "revoked_at is null" in sql
    assert "drop index" not in sql
    assert "create unique index" not in sql
