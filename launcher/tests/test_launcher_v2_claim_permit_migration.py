from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20261025131000_create_launcher_v2_claim_permit.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def function_definition(name: str) -> str:
    sql = migration_sql()
    marker = f"create or replace function launcher_v2.{name}("
    start = sql.rindex(marker)
    end = sql.index("\n$$;", start) + len("\n$$;")
    return sql[start:end]


def test_launcher_v2_entitlement_tables_are_private() -> None:
    sql = migration_sql()

    for table in (
        "products",
        "licenses",
        "installations",
        "sessions",
        "permit_attempts",
    ):
        assert f"create table launcher_v2.{table}" in sql
        assert f"alter table launcher_v2.{table} enable row level security" in sql
        assert f"alter table launcher_v2.{table} force row level security" in sql

    assert (
        "revoke all on all tables in schema launcher_v2 from public, anon, authenticated"
        in sql
    )
    assert "grant all on all tables in schema launcher_v2 to service_role" in sql
    assert "grant usage on schema launcher_v2 to authenticated" in sql
    assert "revoke all on sequence launcher_v2.permit_attempts_id_seq" in sql
    assert "grant usage, select on sequence launcher_v2.permit_attempts_id_seq" in sql
    assert "audit_events_event_type_check" in sql
    assert "'session_claimed'" in sql


def test_claim_requires_live_web_session_and_uses_next_line_tables() -> None:
    claim = function_definition("claim_session")

    assert "launcher_v2.web_sessions" in claim
    assert "launcher_v2.identity_links" in claim
    assert "auth.sessions" in claim
    assert "w.revoked_at is null" in claim
    assert "il.status = 'active'" in claim
    assert "launcher_v2.profiles" in claim
    assert "launcher_v2.licenses" in claim
    assert "launcher_v2.products" in claim
    assert "launcher_v2.installations" in claim
    assert "with revoked_sessions as" in claim
    assert "replaced_by_new_session" in claim
    assert "sessions_one_active_per_user_idx" in migration_sql()
    assert "public.launcher_sessions" not in claim
    assert "public.profiles" not in claim


def test_heartbeat_release_and_permit_require_the_allowlist() -> None:
    for name in ("heartbeat_session", "release_session", "authorize_launch_permit"):
        definition = function_definition(name)
        assert "launcher_v2.web_sessions" in definition
        assert "w.revoked_at is null" in definition
        assert "auth.sessions" in definition

    heartbeat = function_definition("heartbeat_session")
    assert "launcher_v2.licenses" in heartbeat
    assert "last_seen_at > now() - interval '90 seconds'" in heartbeat

    release = function_definition("release_session")
    assert "pg_advisory_xact_lock" in release
    assert "session_revoked" in release

    assert "heartbeatstale" in function_definition("authorize_launch_permit")
    assert "entitlementinactive" in function_definition("authorize_launch_permit")
    assert "sessioninactive" in function_definition("authorize_launch_permit")
    assert "sessionmismatch" in function_definition("authorize_launch_permit")


def test_permit_rate_limit_is_private_and_allowlist_gated() -> None:
    consume = function_definition("consume_permit_attempt")

    assert "launcher_v2.permit_attempts" in consume
    assert "launcher_v2.web_sessions" in consume
    assert "w.revoked_at is null" in consume
    assert "'not_authorized'" in consume
    assert "'rate_limited'" in consume
    assert "pg_advisory_xact_lock" in consume


def test_all_client_rpcs_are_authenticated_only() -> None:
    sql = migration_sql()

    for name in (
        "claim_session(text, text, text)",
        "heartbeat_session(uuid)",
        "release_session(uuid)",
        "authorize_launch_permit(text)",
        "consume_permit_attempt(integer, integer)",
    ):
        assert f"grant execute on function launcher_v2.{name}" in sql
        assert "to authenticated" in sql

    assert "public.launcher_sessions" not in sql
    assert "public.licenses" not in sql
    assert "public.profiles" not in sql
    assert "public.products" not in sql
    assert "public.installations" not in sql
