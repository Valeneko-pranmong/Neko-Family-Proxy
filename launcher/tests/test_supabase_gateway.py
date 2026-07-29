from types import SimpleNamespace

import pytest

from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.infrastructure.supabase_gateway import SupabaseGateway


class MemoryStore:
    def read(self, key: str) -> str | None:
        return None

    def write(self, key: str, value: str) -> None:
        return

    def delete(self, key: str) -> None:
        return


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


def build_gateway(
    client: FakeRpcClient,
) -> SupabaseGateway:
    return SupabaseGateway(
        "https://project.supabase.co",
        "sb_publishable_test",
        MemoryStore(),
        client=client,  # type: ignore[arg-type]
    )


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
