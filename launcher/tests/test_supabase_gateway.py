from types import SimpleNamespace

import pytest

from neko_launcher.application.errors import (
    DeviceAuthorizationDenied,
    LauncherServiceError,
)
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


def test_claim_session_calls_launcher_schema_and_parses_entitlement() -> None:
    client = FakeRpcClient(
        {
            "session_id": "session-id",
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
    assert result.entitlement.valid_until is not None


@pytest.mark.parametrize("code", ["device_limit_reached", "installation_revoked"])
def test_claim_session_raises_typed_device_authorization_error(code: str) -> None:
    client = FakeRpcClient(None, error=RuntimeError(code))

    with pytest.raises(DeviceAuthorizationDenied):
        build_gateway(client).claim_session(
            "neko-family-proxy",
            "a" * 64,
            "Test PC",
        )


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
