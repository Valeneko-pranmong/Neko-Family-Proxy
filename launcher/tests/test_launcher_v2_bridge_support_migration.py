from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20261025132000_add_launcher_v2_bridge_support.sql"
)
CONFIG = REPO_ROOT / "supabase" / "config.toml"
RUNBOOK = REPO_ROOT / "docs" / "current" / "launcher-bridge-staging-runbook.md"


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_bridge_replay_table_and_helpers_are_service_role_only() -> None:
    sql = migration_sql()

    assert "create table launcher_v2.bridge_jti_replays" in sql
    assert "alter table launcher_v2.bridge_jti_replays enable row level security" in sql
    assert "alter table launcher_v2.bridge_jti_replays force row level security" in sql
    assert (
        "revoke all on launcher_v2.bridge_jti_replays from public, anon, authenticated"
        in sql
    )
    assert "grant select, insert, delete on launcher_v2.bridge_jti_replays" in sql

    for function in (
        "consume_bridge_jti(text, text, timestamptz)",
        "bridge_find_user_by_identity_sub(text)",
        "bridge_link_identity(text, uuid)",
        "bridge_record_web_session(uuid, uuid, uuid)",
    ):
        assert f"revoke all on function launcher_v2.{function}" in sql
        assert f"grant execute on function launcher_v2.{function}" in sql
    assert "to authenticated" not in sql
    assert "to service_role" in sql


def test_bridge_jti_consumption_is_single_use_and_bounded() -> None:
    sql = migration_sql()

    assert "delete from launcher_v2.bridge_jti_replays" in sql
    assert "expires_at < now() - interval '1 hour'" in sql
    assert "insert into launcher_v2.bridge_jti_replays" in sql
    assert "on conflict (jti) do nothing" in sql
    assert "get diagnostics v_count = row_count" in sql
    assert "return v_count = 1" in sql


def test_bridge_identity_helpers_require_next_line_app_metadata() -> None:
    sql = migration_sql()

    assert "raw_app_meta_data ->> 'identity_sub'" in sql
    assert "raw_app_meta_data ->> 'auth_line' = 'next'" in sql
    assert "invalid_next_line_user" in sql
    assert "identity_user_conflict" in sql
    assert "identity_link_conflict" in sql
    assert "last_login_at = now()" in sql


def test_bridge_web_session_recording_checks_live_auth_and_identity() -> None:
    sql = migration_sql()

    assert "from auth.sessions a" in sql
    assert "a.id = p_auth_session_id" in sql
    assert "a.user_id = p_user_id" in sql
    assert "from launcher_v2.identity_links il" in sql
    assert "il.status = 'active'" in sql
    assert "insert into launcher_v2.web_sessions" in sql
    assert "on conflict (auth_session_id) do update" in sql
    assert "revoked_at = null" in sql
    assert "public.launcher_sessions" not in sql
    assert "public.profiles" not in sql


def test_bridge_function_disables_gateway_jwt_verification() -> None:
    config = CONFIG.read_text(encoding="utf-8")

    assert "[functions.launcher_bridge]" in config
    bridge_section = config.split("[functions.launcher_bridge]", 1)[1]
    assert "verify_jwt = false" in bridge_section.split("[", 1)[0]


def test_staging_runbook_is_explicitly_non_production() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8").lower()

    assert "staging only" in runbook
    assert "do not apply these migrations to production" in runbook
    assert "do not put test data in the production install root" in runbook
    assert "<test-user-id>" in runbook
