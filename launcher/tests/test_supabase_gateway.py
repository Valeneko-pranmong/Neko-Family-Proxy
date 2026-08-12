import json
from types import SimpleNamespace

import httpx
import pytest
from supabase import ClientOptions, create_client

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    CoreChallenge,
    PermitDiagnosticCode,
)
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.domain.models import SessionTerminationReason
from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeRpcClient:
    def __init__(self, data: object, error: Exception | None = None) -> None:
        self.auth = FakeAuth()
        self.data = data
        self.error = error
        self.schema_name = ""
        self.function_name = ""
        self.parameters: dict[str, object] = {}

    def schema(self, name: str) -> "FakeRpcClient":
        self.schema_name = name
        return self

    def rpc(
        self,
        name: str,
        parameters: dict[str, object],
    ) -> "FakeRpcClient":
        self.function_name = name
        self.parameters = parameters
        return self

    def execute(self) -> SimpleNamespace:
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.data)


class FakeAuth:
    def __init__(self) -> None:
        self.sign_up_payload: dict[str, object] | None = None
        self.sign_in_payload: dict[str, str] | None = None
        self.updated_password: str | None = None
        self.sign_out_options: dict[str, str] | None = None

    def sign_up(self, payload: dict[str, object]) -> SimpleNamespace:
        self.sign_up_payload = payload
        options = payload.get("options")
        metadata = options["data"] if isinstance(options, dict) else {}
        user = SimpleNamespace(
            id="user-id",
            email=payload["email"],
            user_metadata=metadata,
        )
        return SimpleNamespace(user=user, session=SimpleNamespace())

    def sign_in_with_password(
        self,
        payload: dict[str, str],
    ) -> SimpleNamespace:
        self.sign_in_payload = payload
        user = SimpleNamespace(
            id="user-id",
            email=payload["email"],
            user_metadata={"username": "tester"},
        )
        return SimpleNamespace(user=user, session=SimpleNamespace())

    def update_user(self, payload: dict[str, str]) -> SimpleNamespace:
        self.updated_password = payload["password"]
        return SimpleNamespace(user=SimpleNamespace(id="user-id"))

    def sign_out(self, options: dict[str, str]) -> None:
        self.sign_out_options = options

    def get_session(self) -> SimpleNamespace:
        return SimpleNamespace(access_token="test-session-value")


class FakeFunctions:
    def __init__(self) -> None:
        self.access_token: str | None = None
        self.function_name = ""
        self.invoke_options: dict[str, object] = {}
        self._client = SimpleNamespace(timeout=httpx.Timeout(10.0))

    def set_auth(self, access_token: str) -> None:
        self.access_token = access_token

    def invoke(self, function_name: str, invoke_options: dict[str, object]) -> object:
        self.function_name = function_name
        self.invoke_options = invoke_options
        body = invoke_options.get("body")
        correlation_id = body.get("correlationId") if isinstance(body, dict) else None
        return {
            "version": 1,
            "contractRevision": "s0-rc1",
            "correlationId": correlation_id,
            "succeeded": True,
            "permit": "opaque-permit",
            "expiresInSeconds": 30,
        }


class FakeTableQuery:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, str, object]] = []

    def select(self, columns: str) -> "FakeTableQuery":
        return self

    def eq(self, key: str, value: object) -> "FakeTableQuery":
        self.filters.append(("eq", key, value))
        return self

    def neq(self, key: str, value: object) -> "FakeTableQuery":
        self.filters.append(("neq", key, value))
        return self

    def is_(self, key: str, value: object) -> "FakeTableQuery":
        self.filters.append(("is", key, value))
        return self

    def limit(self, count: int) -> "FakeTableQuery":
        return self

    def execute(self) -> SimpleNamespace:
        rows = self.rows
        for operation, key, value in self.filters:
            if operation == "eq":
                rows = [row for row in rows if row.get(key) == value]
            elif operation == "neq":
                rows = [row for row in rows if row.get(key) != value]
            elif operation == "is" and value == "null":
                rows = [row for row in rows if row.get(key) is None]
        return SimpleNamespace(data=rows)


class FakeTableClient:
    def __init__(self, tables: dict[str, list[dict[str, object]]]) -> None:
        self.auth = FakeAuth()
        self.tables = tables

    def schema(self, name: str) -> "FakeTableClient":
        return self

    def table(self, name: str) -> FakeTableQuery:
        return FakeTableQuery(self.tables[name])


def build_gateway(
    client: FakeRpcClient,
    store: MemoryStore | None = None,
) -> SupabaseGateway:
    return SupabaseGateway(
        "https://project.supabase.co",
        "sb_publishable_test",
        store or MemoryStore(),
        client=client,  # type: ignore[arg-type]
    )


def test_clear_local_session_removes_persisted_supabase_auth() -> None:
    client = FakeRpcClient(None)
    client.auth._storage_key = "supabase.auth.token"
    client.auth._refresh_token_timer = None
    store = MemoryStore()
    store.write("supabase.auth.token", "persisted-session")
    gateway = build_gateway(client, store)

    gateway.clear_local_session()

    assert store.read("supabase.auth.token") is None


def test_sign_out_revokes_only_this_installations_auth_session() -> None:
    client = FakeRpcClient(None)
    gateway = build_gateway(client)

    gateway.sign_out()

    assert client.auth.sign_out_options == {"scope": "local"}


def test_claim_session_calls_launcher_schema_and_parses_entitlement() -> None:
    client = FakeRpcClient(
        {
            "session_id": "session-id",
            "installation_id": "installation-id",
            "license_id": "license-id",
            "product_code": "neko-family-proxy",
            "valid_until": "2026-08-24T12:00:00+00:00",
            "max_devices": 1,
        }
    )

    result = build_gateway(client).claim_session(
        "neko-family-proxy",
        "a" * 64,
        "Test PC",
    )

    assert client.schema_name == "launcher"
    assert client.function_name == "claim_session"
    assert client.parameters["p_installation_key_hash"] == "a" * 64
    assert result.session_id == "session-id"
    assert result.installation_id == "installation-id"
    assert result.license_id == "license-id"
    assert result.entitlement.valid_until is not None


@pytest.mark.parametrize("code", ["device_limit_reached", "installation_revoked"])
def test_legacy_device_policy_errors_do_not_create_permanent_device_denial(
    code: str,
) -> None:
    client = FakeRpcClient(None, error=RuntimeError(code))

    with pytest.raises(LauncherServiceError) as raised:
        build_gateway(client).claim_session(
            "neko-family-proxy",
            "a" * 64,
            "Test PC",
        )

    assert raised.type is LauncherServiceError
    assert "เครื่องนี้" not in str(raised.value)
    assert "อุปกรณ์" not in str(raised.value)


def test_auth_identifier_is_derived_without_a_launcher_lookup() -> None:
    client = FakeRpcClient("unexpected-rpc-result@example.com")

    assert (
        build_gateway(client).auth_identifier_for_username("  Tester  ")
        == "tester@project.supabase.co"
    )
    assert client.function_name == ""


def test_sign_up_uses_internal_identifier_without_recovery_metadata() -> None:
    client = FakeRpcClient(None)

    result = build_gateway(client).sign_up(
        " Tester ",
        "password123",
    )

    assert result.username == "tester"
    assert client.auth.sign_up_payload == {
        "email": "tester@project.supabase.co",
        "password": "password123",
        "options": {
            "data": {
                "username": "tester",
                "display_name": "tester",
            }
        },
    }


def test_sign_in_derives_internal_identifier_without_rpc() -> None:
    client = FakeRpcClient("unexpected-rpc-result@example.com")

    user = build_gateway(client).sign_in(" Tester ", "password123")

    assert user.username == "tester"
    assert client.function_name == ""
    assert client.auth.sign_in_payload == {
        "email": "tester@project.supabase.co",
        "password": "password123",
    }

def test_change_password_uses_authenticated_auth_client() -> None:
    client = FakeRpcClient(None)

    build_gateway(client).change_password("new-password")

    assert client.auth.updated_password == "new-password"


def test_permit_uses_same_authenticated_client_as_session_claim() -> None:
    client = FakeRpcClient(None)
    client.functions = FakeFunctions()
    gateway = build_gateway(client)

    permit = gateway.issue_launch_permit(
        gateway,
        "0123456789abcdef0123456789abcdef",
        CoreChallenge("a" * 43),
        "b" * 64,
        "pso2.exe",
        4242,
        "ProcessMode",
        "neko-family-proxy",
        "proxy:start",
        10.0,
    )

    assert permit.reveal_for_transport() == "opaque-permit"
    assert client.functions.access_token == "test-session-value"
    assert client.functions.function_name == "issue_launch_permit"


def test_pinned_supabase_sdk_sends_current_access_token_and_decodes_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["authorization"] = request.headers.get("Authorization")
        observed["body"] = json.loads(request.content)
        observed["timeout"] = request.extensions.get("timeout")
        return httpx.Response(
            200,
            json={
                "version": 1,
                "contractRevision": "s0-rc1",
                "correlationId": "0123456789abcdef0123456789abcdef",
                "succeeded": True,
                "permit": "opaque-sdk-permit",
                "expiresInSeconds": 30,
            },
        )

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        timeout=10.0,
    )
    client = create_client(
        "https://project.supabase.co",
        "sb_publishable_test",
        options=ClientOptions(httpx_client=http_client),
    )
    monkeypatch.setattr(
        client.auth,
        "get_session",
        lambda: SimpleNamespace(access_token="current-access-token"),
    )
    gateway = SupabaseGateway(
        "https://project.supabase.co",
        "sb_publishable_test",
        MemoryStore(),
        client=client,
    )

    permit = gateway.issue_launch_permit(
        gateway,
        "0123456789abcdef0123456789abcdef",
        CoreChallenge("a" * 43),
        "b" * 64,
        "pso2.exe",
        4242,
        "ProcessMode",
        "neko-family-proxy",
        "proxy:start",
        10.0,
    )

    assert observed["path"] == "/functions/v1/issue_launch_permit"
    assert observed["authorization"] == "Bearer current-access-token"
    assert observed["timeout"] == {
        "connect": 10.0,
        "read": 10.0,
        "write": 10.0,
        "pool": 10.0,
    }
    assert observed["body"] == {
        "version": 1,
        "contractRevision": "s0-rc1",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "challenge": "a" * 43,
        "configurationDigest": "b" * 64,
        "processName": "pso2.exe",
        "targetPid": 4242,
        "mode": "ProcessMode",
        "product": "neko-family-proxy",
        "scope": "proxy:start",
    }
    assert permit.reveal_for_transport() == "opaque-sdk-permit"


def test_current_session_heartbeat_applies_requested_http_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=True)

    client = create_client(
        "https://project.supabase.co",
        "sb_publishable_test",
        options=ClientOptions(
            schema="launcher",
            httpx_client=httpx.Client(
                transport=httpx.MockTransport(handler),
                timeout=2.5,
            ),
        ),
    )
    monkeypatch.setattr(
        client.auth,
        "get_session",
        lambda: SimpleNamespace(access_token="current-access-token"),
    )
    gateway = SupabaseGateway(
        "https://project.supabase.co",
        "sb_publishable_test",
        MemoryStore(),
        client=client,
    )

    alive = gateway.heartbeat_session_with_timeout("current-session", 2.5)

    assert alive is True
    assert observed["path"] == "/rest/v1/rpc/heartbeat_session"
    assert observed["timeout"] == {
        "connect": 2.5,
        "read": 2.5,
        "write": 2.5,
        "pool": 2.5,
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, PermitDiagnosticCode.PERMIT_HTTP_401),
        (403, PermitDiagnosticCode.PERMIT_HTTP_403),
        (404, PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND),
        (500, PermitDiagnosticCode.PERMIT_HTTP_500),
    ],
)
def test_pinned_supabase_sdk_http_failures_are_classified_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    expected: PermitDiagnosticCode,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "sensitive backend detail"})

    client = create_client(
        "https://project.supabase.co",
        "sb_publishable_test",
        options=ClientOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    monkeypatch.setattr(
        client.auth,
        "get_session",
        lambda: SimpleNamespace(access_token="current-access-token"),
    )
    gateway = SupabaseGateway(
        "https://project.supabase.co",
        "sb_publishable_test",
        MemoryStore(),
        client=client,
    )

    with pytest.raises(AuthorizedCoreError) as raised:
        gateway.issue_launch_permit(
            gateway,
            "0123456789abcdef0123456789abcdef",
            CoreChallenge("a" * 43),
            "b" * 64,
            "pso2.exe",
            4242,
            "ProcessMode",
            "neko-family-proxy",
            "proxy:start",
            10.0,
        )

    assert raised.value.diagnostic_code is expected
    assert raised.value.diagnostic_context["http_status"] == status
    assert str(raised.value) == "authorization permit is unavailable"
    assert "sensitive backend detail" not in str(raised.value)


def test_redeem_coupon_maps_safe_server_error() -> None:
    client = FakeRpcClient({"ok": False, "error": "invalid_coupon"})

    with pytest.raises(LauncherServiceError, match="คูปองไม่ถูกต้อง"):
        build_gateway(client).redeem_coupon("bad-code")


def test_account_restriction_uses_suspended_account_copy() -> None:
    error = SupabaseGateway._rpc_error(RuntimeError("account_restricted"), "fallback")

    assert "ระงับ" in str(error)


def termination_client(
    *,
    sessions: list[dict[str, object]] | None = None,
    valid_from: str = "2020-01-01T00:00:00+00:00",
    valid_until: str = "2099-01-01T00:00:00+00:00",
) -> FakeTableClient:
    return FakeTableClient(
        {
            "launcher_sessions": sessions
            or [
                {
                    "id": "current-session",
                    "user_id": "user-id",
                    "installation_id": "installation-id",
                    "license_id": "license-id",
                    "revoked_at": None,
                }
            ],
            "profiles": [{"id": "user-id", "status": "active"}],
            "installations": [{"id": "installation-id", "revoked_at": None}],
            "licenses": [
                {
                    "id": "license-id",
                    "status": "active",
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                }
            ],
        }
    )


def test_current_session_is_not_classified_as_its_own_replacement() -> None:
    client = termination_client()

    reason = build_gateway(client).session_termination_reason("current-session")  # type: ignore[arg-type]

    assert reason is SessionTerminationReason.REVOKED


def test_newer_active_session_takes_priority_over_legacy_installation_state() -> None:
    client = termination_client(
        sessions=[
            {
                "id": "replaced-session",
                "user_id": "user-id",
                "installation_id": "installation-id",
                "license_id": "license-id",
                "revoked_at": "2026-08-09T00:00:00+00:00",
            },
            {
                "id": "new-session",
                "user_id": "user-id",
                "installation_id": "other-installation-id",
                "license_id": "license-id",
                "revoked_at": None,
            },
        ]
    )
    client.tables["installations"][0]["revoked_at"] = "2026-08-09T00:00:00+00:00"

    reason = build_gateway(client).session_termination_reason("replaced-session")  # type: ignore[arg-type]

    assert reason is SessionTerminationReason.REPLACED


def test_future_license_is_classified_as_unavailable() -> None:
    client = termination_client(valid_from="2099-01-01T00:00:00+00:00")

    reason = build_gateway(client).session_termination_reason("current-session")  # type: ignore[arg-type]

    assert reason is SessionTerminationReason.LICENSE_UNAVAILABLE


def test_invalid_password_error_uses_customer_friendly_copy() -> None:
    error = SupabaseGateway._auth_error(
        RuntimeError("Invalid login credentials"),
        "fallback",
    )

    assert str(error) == "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"


def test_duplicate_signup_error_directs_user_to_login() -> None:
    error = SupabaseGateway._auth_error(
        RuntimeError("User already registered"),
        "fallback",
    )

    assert str(error) == "ชื่อผู้ใช้นี้มีบัญชีอยู่แล้ว กรุณาไปที่แท็บเข้าสู่ระบบ"
