from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20261024120000_permit_rate_limit.sql"
)
FUNCTION_DIR = REPO_ROOT / "supabase" / "functions" / "issue_launch_permit"
FUNCTION_SOURCE = FUNCTION_DIR / "index.ts"
SERVICE_SOURCE = FUNCTION_DIR / "service.ts"


def test_permit_rate_limit_table_is_private_and_authenticated_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "create table if not exists launcher.permit_attempts" in sql
    assert "alter table launcher.permit_attempts enable row level security" in sql
    assert "alter table launcher.permit_attempts force row level security" in sql
    assert (
        "revoke all on launcher.permit_attempts from public, anon, authenticated"
        in sql
    )
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "auth.uid()" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "make_interval(secs => p_window_seconds)" in sql
    assert (
        "grant execute on function launcher.consume_permit_attempt(integer, integer)"
        in sql
    )
    assert "to authenticated" in sql
    assert "to anon" not in sql


def test_permit_function_consumes_an_attempt_before_authorization() -> None:
    service = SERVICE_SOURCE.read_text(encoding="utf-8")
    function = FUNCTION_SOURCE.read_text(encoding="utf-8")

    assert "deps.consumePermitAttempt(caller)" in service
    assert 'error: "RateLimited"' in service
    consume_at = service.index("deps.consumePermitAttempt(caller)")
    authorize_at = service.index("deps.authorize(")
    assert consume_at < authorize_at

    assert "consumePermitAttempt" in function
    assert "consume_permit_attempt" in function
    assert "PERMIT_RATE_LIMIT" in function
    assert "PERMIT_RATE_WINDOW_SECONDS" in function
