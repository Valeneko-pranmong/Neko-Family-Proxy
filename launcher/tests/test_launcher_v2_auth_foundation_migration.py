from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20261025130000_create_launcher_v2_auth_foundation.sql"
)
SUPABASE_README = REPO_ROOT / "supabase" / "README.md"


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def new_user_trigger() -> str:
    sql = migration_sql()
    marker = "create or replace function launcher.handle_new_user()"
    start = sql.rindex(marker)
    end = sql.index("\n$$;", start) + len("\n$$;")
    return sql[start:end]


def test_launcher_v2_schema_and_tables_are_private() -> None:
    sql = migration_sql()

    assert "create schema if not exists launcher_v2" in sql
    for table in ("profiles", "identity_links", "web_sessions", "audit_events"):
        assert f"create table launcher_v2.{table}" in sql
        assert f"alter table launcher_v2.{table} enable row level security" in sql
        assert f"alter table launcher_v2.{table} force row level security" in sql

    assert "revoke all on schema launcher_v2 from public, anon, authenticated" in sql
    assert (
        "revoke all on all tables in schema launcher_v2 from public, anon, authenticated"
        in sql
    )
    assert "grant usage on schema launcher_v2 to service_role" in sql
    assert "grant all on all tables in schema launcher_v2 to service_role" in sql
    assert "grant execute on function" not in sql
    assert "to authenticated" not in sql


def test_launcher_v2_is_exposed_only_for_server_side_access() -> None:
    sql = migration_sql()

    assert (
        "set pgrst.db_schemas = 'public, graphql_public, launcher, launcher_v2'"
        in sql
    )
    assert "notify pgrst, 'reload config'" in sql


def test_identity_links_are_unique_in_both_directions() -> None:
    sql = migration_sql()

    assert "identity_sub text not null unique" in sql
    assert "user_id uuid not null unique references auth.users(id)" in sql
    assert "status text not null default 'active'" in sql
    assert "check (status in ('active', 'unlinked'))" in sql


def test_web_sessions_are_a_server_written_allowlist() -> None:
    sql = migration_sql()

    assert "auth_session_id uuid primary key references auth.sessions(id)" in sql
    assert "user_id uuid not null references auth.users(id)" in sql
    assert "identity_link_id uuid not null" in sql
    assert "references launcher_v2.identity_links(id)" in sql
    assert "revoked_at timestamptz" in sql
    assert "web_sessions_user_active_idx" in sql


def test_new_user_trigger_routes_only_server_app_metadata_to_the_next_line() -> None:
    trigger = new_user_trigger()

    assert "raw_app_meta_data ->> 'auth_line'" in trigger
    assert "coalesce" in trigger
    assert "'legacy'" in trigger
    assert "'next'" in trigger
    assert "insert into launcher_v2.profiles" in trigger
    assert "insert into public.profiles" in trigger
    assert "revoke all on function launcher.handle_new_user() from public" in migration_sql()


def test_bridge_contract_is_documented() -> None:
    readme = SUPABASE_README.read_text(encoding="utf-8").lower()

    assert "launcher_v2" in readme
    assert "auth_line" in readme
    assert "web_sessions" in readme
    assert "service_role" in readme
