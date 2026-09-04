from pathlib import Path

SQL_PATH = Path(__file__).resolve().parents[2].joinpath(
    "supabase", "migrations", "20260904130000_runtime_proxy_config_v1.sql"
)


def _sql() -> str:
    assert SQL_PATH.is_file(), f"Migration file missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


def test_runtime_config_is_not_customer_readable():
    sql = _sql().lower()
    # Explicit revokes on tables from public, anon, authenticated, and service_role
    assert "revoke all on table launcher.runtime_proxy_config_versions from public, anon, authenticated, service_role;" in sql
    assert "revoke all on table launcher.runtime_proxy_config_state from public, anon, authenticated, service_role;" in sql
    assert "revoke all on function launcher.publish_runtime_proxy_config(text, text, integer, text, text) from public, anon, authenticated;" in sql
    assert "revoke all on function launcher.get_active_runtime_proxy_config() from public, anon, authenticated;" in sql

    # Ensure no direct table grants exist for service_role or others
    assert "grant select" not in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql

    # Explicit schema USAGE and RPC EXECUTE grants for service_role
    assert "grant usage on schema launcher to service_role;" in sql
    assert "grant execute on function launcher.publish_runtime_proxy_config(text, text, integer, text, text) to service_role;" in sql
    assert "grant execute on function launcher.get_active_runtime_proxy_config() to service_role;" in sql


def test_publish_is_monotonic_with_separate_active_pointer():
    sql = _sql()
    sql_lower = sql.lower()
    assert "runtime_proxy_config_state" in sql_lower
    assert "coalesce(max(config_version), 0) + 1" in sql_lower
    assert "active_config_version" in sql_lower
    assert "pg_advisory_xact_lock" in sql_lower


def test_immutability_and_safe_publish_return():
    sql = _sql()
    sql_lower = sql.lower()

    # Function return safe metadata only
    assert "jsonb_build_object" in sql_lower
    assert "'config_version'" in sql_lower
    assert "'endpoint_id'" in sql_lower
    assert "'published_at'" in sql_lower

    # In publish function definition, verify credential is never part of the returned object
    # Find publish function body
    publish_start = sql_lower.find("function launcher.publish_runtime_proxy_config")
    assert publish_start != -1
    publish_end = sql_lower.find("$$;", publish_start)
    assert publish_end != -1
    publish_body = sql_lower[publish_start:publish_end]

    assert "return jsonb_build_object(" in publish_body
    # Ensure credential is not in the return jsonb_build_object
    return_stmt = publish_body[publish_body.find("return jsonb_build_object(") : ]
    assert "p_credential" not in return_stmt
    assert "'credential'" not in return_stmt

    # Immutability check on runtime_proxy_config_versions
    assert "runtime_proxy_config_versions_prevent_mutation" in sql_lower
    assert "before update or delete on launcher.runtime_proxy_config_versions" in sql_lower


def test_schema_qualified_objects_and_empty_search_path():
    sql = _sql()
    sql_lower = sql.lower()
    # Check security definer and set search_path = ''
    publish_start = sql_lower.find("function launcher.publish_runtime_proxy_config")
    get_active_start = sql_lower.find("function launcher.get_active_runtime_proxy_config")

    assert "security definer" in sql_lower[publish_start:]
    assert "set search_path = ''" in sql_lower[publish_start:]
    assert "security definer" in sql_lower[get_active_start:]
    assert "set search_path = ''" in sql_lower[get_active_start:]


def test_field_constraints():
    sql = _sql().lower()
    assert "config_version > 0" in sql
    assert "protocol = 'shadowsocks'" in sql
    assert "port between 1 and 65535" in sql
    # ASCII and length constraints
    assert "endpoint_id ~ '^[\\x20-\\x7e]{1,64}$'" in sql
    assert "host ~ '^[\\x20-\\x7e]{1,253}$'" in sql
    assert "cipher ~ '^[\\x20-\\x7e]{1,64}$'" in sql
    assert "credential ~ '^[\\x20-\\x7e]{1,256}$'" in sql
