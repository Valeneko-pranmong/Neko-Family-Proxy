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
        self.reset_call: tuple[str, dict[str, str] | None] | None = None

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

    def reset_password_for_email(
        self,
        email: str,
        options: dict[str, str] | None,
    ) -> None:
        self.reset_call = (email, options)


def build_gateway(
    client: FakeRpcClient,
    reset_redirect_url: str = "",
) -> SupabaseGateway:
    return SupabaseGateway(
        "https://project.supabase.co",
        "sb_publishable_test",
        MemoryStore(),
        password_reset_redirect_url=reset_redirect_url,
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


def test_auth_email_lookup_calls_launcher_api_with_normalized_username() -> None:
    client = FakeRpcClient("tester@example.com")

    assert (
        build_gateway(client).lookup_auth_email("  Tester  ")
        == "tester@example.com"
    )
    assert client.schema_name == "launcher"
    assert client.function_name == "auth_email_for_username"
    assert client.parameters == {"p_username": "tester"}


def test_sign_up_uses_real_email_and_recovery_metadata() -> None:
    client = FakeRpcClient(None)

    result = build_gateway(client).sign_up(
        " Tester ",
        "password123",
        " USER@Example.COM ",
    )

    assert result.username == "tester"
    assert client.auth.sign_up_payload == {
        "email": "user@example.com",
        "password": "password123",
        "options": {
            "data": {
                "username": "tester",
                "display_name": "tester",
                "recovery_email": "user@example.com",
            }
        },
    }


def test_sign_in_resolves_current_auth_email_before_password_auth() -> None:
    client = FakeRpcClient("current@example.com")

    user = build_gateway(client).sign_in(" Tester ", "password123")

    assert user.username == "tester"
    assert client.function_name == "auth_email_for_username"
    assert client.auth.sign_in_payload == {
        "email": "current@example.com",
        "password": "password123",
    }


def test_sign_in_missing_lookup_uses_generic_credentials_error() -> None:
    client = FakeRpcClient(None)

    with pytest.raises(
        LauncherServiceError,
        match="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
    ):
        build_gateway(client).sign_in("tester", "password123")

    assert client.auth.sign_in_payload is None


def test_lookup_rpc_failure_uses_temporary_failure_message() -> None:
    client = FakeRpcClient(None, RuntimeError("rpc unavailable"))

    with pytest.raises(LauncherServiceError, match="ชั่วคราว"):
        build_gateway(client).lookup_auth_email("tester")


def test_password_reset_uses_permanent_redirect_url() -> None:
    client = FakeRpcClient(None)
    redirect_url = "https://neko-reset.vercel.app/reset-password/"

    build_gateway(client, redirect_url).request_password_reset(
        " USER@Example.COM "
    )

    assert client.auth.reset_call == (
        "user@example.com",
        {"redirect_to": redirect_url},
    )


def test_password_reset_refuses_stale_site_url_fallback() -> None:
    client = FakeRpcClient(None)

    with pytest.raises(LauncherServiceError, match="ยังไม่พร้อม"):
        build_gateway(client).request_password_reset("user@example.com")

    assert client.auth.reset_call is None


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
