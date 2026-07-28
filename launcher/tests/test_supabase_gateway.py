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
    def __init__(self, data: object) -> None:
        self.auth = SimpleNamespace()
        self.data = data
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
        return SimpleNamespace(data=self.data)


def build_gateway(client: FakeRpcClient) -> SupabaseGateway:
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


def test_user_exists_calls_launcher_api_with_normalized_username() -> None:
    client = FakeRpcClient(True)

    assert build_gateway(client).user_exists("  ZaloNext  ") is True
    assert client.schema_name == "launcher"
    assert client.function_name == "user_exists"
    assert client.parameters == {"p_username": "zalonext"}


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
