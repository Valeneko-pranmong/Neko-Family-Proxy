from pathlib import Path


MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260809120000_account_recovery_codes.sql"
)
VERIFY_FIX_MIGRATION = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260809124500_fix_recovery_verify_column_ambiguity.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def verify_fix_sql() -> str:
    return VERIFY_FIX_MIGRATION.read_text(encoding="utf-8").lower()


def test_recovery_schema_stores_only_verifiers_and_server_timestamps() -> None:
    sql = migration_sql()
    assert "create table public.account_recovery_codes" in sql
    assert "create table public.account_recovery_sessions" in sql
    assert "create table public.account_recovery_rate_limits" in sql
    for field in (
        "code_verifier",
        "expires_at",
        "used_at",
        "revoked_at",
        "attempt_count",
        "max_attempts",
        "status",
        "token_verifier",
        "password_fingerprint",
        "auth_attempt_started_at",
    ):
        assert field in sql
    assert "interval '5 minutes'" in sql
    assert "temporary_password" not in sql
    assert "new_password" not in sql
    assert "recovery_code text" not in sql


def test_recovery_functions_are_service_role_only_and_safe() -> None:
    sql = migration_sql()
    functions = (
        "admin_generate_recovery_code",
        "verify_recovery_code",
        "claim_recovery_password_change",
        "release_recovery_password_change",
        "complete_recovery_password_change",
    )
    for function in functions:
        assert f"function launcher.{function}" in sql
    assert sql.count("security definer") >= len(functions)
    assert sql.count("set search_path = ''") >= len(functions)
    for table in (
        "account_recovery_codes",
        "account_recovery_sessions",
        "account_recovery_rate_limits",
    ):
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table}" in sql
    assert sql.count("from public, anon, authenticated") >= len(functions)
    assert sql.count("to service_role") >= len(functions)


def test_generation_invalidates_older_codes_and_audits_without_secret() -> None:
    sql = migration_sql()
    assert "account_recovery_one_active_per_user_idx" in sql
    assert "status = 'revoked'" in sql
    assert "account_recovery_code_revoked" in sql
    assert "account_recovery_code_generated" in sql
    assert "created_by_admin" in sql
    assert "'code_verifier'" not in sql
    assert "cannot_recover_current_admin" in sql
    assert "target_not_customer" in sql
    assert "target_username_mismatch" in sql


def test_verification_enforces_expiry_attempts_rate_limit_and_single_use() -> None:
    sql = migration_sql()
    assert "attempt_count = attempt_count + 1" in sql
    assert "status = 'locked'" in sql
    assert "account_recovery_code_locked" in sql
    assert "account_recovery_verified" in sql
    assert "recovery_invalid" in sql
    assert "recovery_rate_limited" in sql
    assert "for update" in sql
    assert "used_at = now()" in sql
    assert "status = 'used'" in sql
    assert "on conflict (requester_verifier, window_started_at)" in sql
    assert "select false, 'recovery_invalid'" in sql
    assert "select false, 'recovery_rate_limited'" in sql


def test_password_change_is_restricted_idempotent_and_revokes_sessions() -> None:
    sql = migration_sql()
    assert "scope text not null default 'change_password'" in sql
    assert "scope = 'change_password'" in sql
    assert "password_fingerprint_mismatch" in sql
    assert "auth_update_in_progress" in sql
    assert "interval '2 minutes'" in sql
    assert "state = 'auth_updating'" in sql
    assert "state = 'retryable'" in sql
    assert "state = 'completed'" in sql
    assert "update public.launcher_sessions" in sql
    assert "where user_id = v_session.user_id" in sql
    assert "and revoked_at is null" in sql
    assert "account_password_recovered" in sql
    assert "recovery_session_invalid" in sql


def test_password_change_verifiers_are_lexically_validated_and_null_safe() -> None:
    sql = migration_sql()
    for function in (
        "claim_recovery_password_change",
        "release_recovery_password_change",
        "complete_recovery_password_change",
    ):
        body = sql.split(f"create or replace function launcher.{function}", 1)[1]
        body = body.split("$$;", 1)[0]
        assert "p_token_verifier !~ '^[0-9a-f]{64}$'" in body
        assert "p_password_fingerprint !~ '^[0-9a-f]{64}$'" in body
    assert "v_session.password_fingerprint is distinct from p_password_fingerprint" in sql


def test_recovery_is_active_customer_only_and_rate_limits_are_bounded() -> None:
    sql = migration_sql()
    generation = sql.split(
        "create or replace function launcher.admin_generate_recovery_code",
        1,
    )[1].split("create or replace function launcher.verify_recovery_code", 1)[0]
    verification = sql.split(
        "create or replace function launcher.verify_recovery_code",
        1,
    )[1].split("create or replace function launcher.claim_recovery_password_change", 1)[0]
    assert "v_target.status <> 'active'" in generation
    assert "status = 'active'" in verification
    assert "delete from public.account_recovery_rate_limits" in verification
    assert "window_started_at < now() - interval '1 day'" in verification


def test_completed_replay_precedes_revoked_or_expired_rejection() -> None:
    sql = migration_sql()
    claim = sql.split(
        "create or replace function launcher.claim_recovery_password_change",
        1,
    )[1].split(
        "create or replace function launcher.release_recovery_password_change",
        1,
    )[0]

    fingerprint_check = claim.index("password_fingerprint_mismatch")
    completed_check = claim.index("v_session.state = 'completed'")
    generic_rejection = claim.index("v_session.expires_at <= now()")

    assert fingerprint_check < completed_check < generic_rejection
    assert "v_session.revoked_at is not null" in claim[generic_rejection:]


def test_audit_constraint_preserves_history_and_adds_recovery_events() -> None:
    sql = migration_sql()
    for event in (
        "admin_password_reset",
        "account_recovery_code_generated",
        "account_recovery_code_revoked",
        "account_recovery_code_locked",
        "account_recovery_verified",
        "account_password_recovered",
        "account_recovery_auth_failed",
    ):
        assert f"'{event}'" in sql
    assert "function launcher.admin_password_reset" not in sql
    assert "function launcher.reset_user_password" not in sql


def test_verify_forward_fix_qualifies_columns_that_conflict_with_output_names() -> None:
    sql = verify_fix_sql()
    assert "create or replace function launcher.verify_recovery_code" in sql
    assert "from public.profiles as profile" in sql
    assert "select profile.id into v_user_id" in sql
    assert "from public.account_recovery_codes as recovery_code" in sql
    assert "where recovery_code.user_id = v_user_id" in sql
    assert "where user_id = v_user_id" not in sql
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql