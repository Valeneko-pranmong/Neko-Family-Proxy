from __future__ import annotations

from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).parents[2] / "supabase" / "migrations"
HISTORICAL_MIGRATION = MIGRATIONS / "20260809120000_account_recovery_codes.sql"
FORWARD_MIGRATION = (
    MIGRATIONS / "20260810040000_revoke_superseded_recovery_sessions.sql"
)
FUNCTION_START = (
    "create or replace function launcher.admin_generate_recovery_code("
)
FUNCTION_END = (
    "revoke all on function "
    "launcher.admin_generate_recovery_code(uuid, uuid, text, uuid, text)"
)
SESSION_REVOCATION = """update public.account_recovery_sessions
  set state = 'revoked',
      revoked_at = coalesce(revoked_at, now()),
      failure_code = 'superseded'
  where user_id = p_user_id
    and state in ('active', 'auth_updating', 'retryable');"""


def migration_sql() -> str:
    source = FORWARD_MIGRATION if FORWARD_MIGRATION.exists() else HISTORICAL_MIGRATION
    return source.read_text(encoding="utf-8").lower()


def generation_function(sql: str) -> str:
    assert FUNCTION_START in sql, "admin_generate_recovery_code definition missing"
    body = sql.split(FUNCTION_START, 1)[1]
    assert FUNCTION_END in body, "admin_generate_recovery_code grant boundary missing"
    return body.split(FUNCTION_END, 1)[0]


def assert_supersession_contract(sql: str) -> None:
    function = generation_function(sql)
    assert "perform launcher.assert_admin_actor(p_actor_id);" in function
    assert "from public.profiles" in function
    assert "where id = p_user_id" in function
    assert "for update;" in function
    assert SESSION_REVOCATION in function
    assert "state = 'completed'" not in SESSION_REVOCATION
    assert "token_verifier" not in function
    assert "code_verifier'" not in function
    assert "security definer" in function
    assert "set search_path = ''" in function


def test_generation_revokes_all_incomplete_recovery_sessions() -> None:
    assert_supersession_contract(migration_sql())


def test_supersession_contract_detects_removed_session_revocation() -> None:
    mutated = migration_sql().replace(SESSION_REVOCATION, "", 1)

    with pytest.raises(AssertionError):
        assert_supersession_contract(mutated)


def test_generation_synchronizes_with_code_verification_before_revoking_sessions() -> None:
    function = generation_function(migration_sql())
    profile_lock = function.index("from public.profiles")
    code_supersession = function.index("update public.account_recovery_codes")
    session_supersession = function.index(SESSION_REVOCATION)

    assert profile_lock < code_supersession < session_supersession
