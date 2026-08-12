from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import LauncherServiceError, RecoveryRetryRequired
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.models import (
    AuthenticatedUser,
    AuthStatus,
    RecoverySession,
    RegistrationResult,
    SessionTerminationReason,
)
from neko_launcher.infrastructure.account_recovery_gateway import (
    HttpAccountRecoveryGateway,
    _NoRedirectHandler,
)
from neko_launcher.infrastructure.event_bus import EventBus


class FakeNormalGateway:
    def __init__(self) -> None:
        self.claims = 0
        self.coupons = 0
        self.changed_password: str | None = None

    def sign_up(self, username: str, password: str) -> RegistrationResult:
        return RegistrationResult(username)

    def sign_in(self, username: str, password: str) -> AuthenticatedUser:
        return AuthenticatedUser("user-id", username)

    def change_password(self, password: str) -> None:
        self.changed_password = password

    def auth_identifier_for_username(self, username: str) -> str:
        return username

    def restore_session(self) -> AuthenticatedUser | None:
        return None

    def sign_out(self) -> None:
        return None

    def clear_local_session(self) -> None:
        return None

    def claim_session(self, product_code: str, installation_key_hash: str, display_name: str):
        self.claims += 1
        raise AssertionError("recovery must not claim a normal Launcher session")

    def heartbeat_session(self, session_id: str) -> bool:
        return False

    def session_termination_reason(self, session_id: str) -> SessionTerminationReason:
        return SessionTerminationReason.REVOKED

    def release_session(self, session_id: str) -> bool:
        return False

    def redeem_coupon(self, code: str):
        self.coupons += 1
        raise AssertionError("recovery must not redeem coupons")


class FakeRecoveryGateway:
    def __init__(self) -> None:
        self.verifications: list[tuple[str, str]] = []
        self.changes: list[tuple[str, str]] = []
        self.verify_error: Exception | None = None
        self.change_error: Exception | None = None

    def verify_recovery_code(self, username: str, recovery_code: str) -> RecoverySession:
        self.verifications.append((username, recovery_code))
        if self.verify_error:
            raise self.verify_error
        return RecoverySession(
            session_id="11111111-1111-4111-8111-111111111111",
            token="opaque_recovery_token_value_abcdefghijklmnopqrstuvwxyz",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    def change_password(self, recovery_session: str, new_password: str) -> None:
        self.changes.append((recovery_session, new_password))
        if self.change_error:
            raise self.change_error


class FakeInstallation:
    key_hash = "a" * 64
    display_name = "Test PC"


def recovery_workflow():
    controller = ApplicationController(EventBus())
    normal = FakeNormalGateway()
    recovery = FakeRecoveryGateway()
    service = LauncherService(
        controller,
        normal,
        normal,
        FakeInstallation(),
        "product",
        recovery_gateway=recovery,
    )
    return service, controller, normal, recovery


def test_valid_recovery_code_enters_recovery_only_state_without_normal_session() -> None:
    service, controller, normal, recovery = recovery_workflow()
    service.begin_account_recovery()

    service.verify_recovery_code(" TestUser ", " ABCD-EFGH-JKLM-NPQR-STUV-WX2345 ")

    assert recovery.verifications == [("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")]
    assert controller.state.auth_status is AuthStatus.RECOVERY_PASSWORD_CHANGE
    assert controller.state.user_id is None
    assert controller.state.session_id is None
    assert controller.state.entitlement is None
    assert normal.claims == 0


def test_recovery_state_cannot_start_core_tweaker_coupon_or_normal_session() -> None:
    service, controller, normal, _ = recovery_workflow()
    service.begin_account_recovery()
    service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

    service.start_proxy()
    service.launch_tweaker("Tweaker.exe")
    with pytest.raises(LauncherServiceError, match="เข้าสู่ระบบ"):
        service.redeem_coupon("coupon")

    assert controller.state.proxy_status.value == "failed"
    assert controller.state.game_status.value == "failed"
    assert normal.claims == 0
    assert normal.coupons == 0


def test_invalid_recovery_code_remains_on_code_entry() -> None:
    service, controller, _, recovery = recovery_workflow()
    recovery.verify_error = LauncherServiceError("รหัสกู้บัญชีไม่ถูกต้องหรือหมดอายุแล้ว")
    service.begin_account_recovery()

    with pytest.raises(LauncherServiceError, match="ไม่ถูกต้องหรือหมดอายุ"):
        service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

    assert controller.state.auth_status is AuthStatus.RECOVERY_CODE_ENTRY
    assert service.has_recovery_session is False


def test_duplicate_verify_is_rejected_before_second_backend_call() -> None:
    service, controller, _, recovery = recovery_workflow()
    original_verify = recovery.verify_recovery_code

    def verify_and_attempt_duplicate(
        username: str, recovery_code: str
    ) -> RecoverySession:
        with pytest.raises(LauncherServiceError, match="กรุณารอ"):
            service.verify_recovery_code(username, recovery_code)
        return original_verify(username, recovery_code)

    recovery.verify_recovery_code = verify_and_attempt_duplicate  # type: ignore[method-assign]
    service.begin_account_recovery()

    service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

    assert len(recovery.verifications) == 1
    assert controller.state.auth_status is AuthStatus.RECOVERY_PASSWORD_CHANGE


def test_password_policy_and_confirmation_are_enforced_before_backend() -> None:
    service, _, _, recovery = recovery_workflow()
    service.begin_account_recovery()
    service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

    with pytest.raises(LauncherServiceError, match="12-128"):
        service.change_recovery_password("alllowercase12!", "alllowercase12!")
    with pytest.raises(LauncherServiceError, match="ไม่ตรงกัน"):
        service.change_recovery_password("ValidPassword12!", "DifferentPassword12!")

    assert recovery.changes == []


def test_ambiguous_password_change_keeps_same_recovery_session_for_exact_retry() -> None:
    service, controller, _, recovery = recovery_workflow()
    service.begin_account_recovery()
    service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")
    recovery.change_error = RecoveryRetryRequired(
        "ระบบกู้บัญชียังดำเนินการไม่เสร็จ กรุณาลองส่งรหัสผ่านเดิมอีกครั้ง"
    )

    with pytest.raises(LauncherServiceError, match="รหัสผ่านเดิม"):
        service.change_recovery_password("ValidPassword12!", "ValidPassword12!")

    assert controller.state.auth_status is AuthStatus.RECOVERY_PASSWORD_CHANGE
    assert service.has_recovery_session is True
    with pytest.raises(RecoveryRetryRequired, match="รหัสผ่านเดิม"):
        service.change_recovery_password("OtherPassword12!", "OtherPassword12!")
    assert len(recovery.changes) == 1
    recovery.change_error = None
    service.change_recovery_password("ValidPassword12!", "ValidPassword12!")
    assert len(recovery.changes) == 2
    assert recovery.changes[0] == recovery.changes[1]


def test_cancelled_verification_cannot_restore_recovery_session() -> None:
    service, controller, _, recovery = recovery_workflow()
    original_verify = recovery.verify_recovery_code

    def verify_then_cancel(username: str, recovery_code: str) -> RecoverySession:
        result = original_verify(username, recovery_code)
        service.cancel_account_recovery()
        return result

    recovery.verify_recovery_code = verify_then_cancel  # type: ignore[method-assign]
    service.begin_account_recovery()

    with pytest.raises(LauncherServiceError, match="ยกเลิก"):
        service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

    assert service.has_recovery_session is False
    assert controller.state.auth_status is AuthStatus.SIGNED_OUT


def test_cancelled_failed_verification_cannot_reopen_recovery_screen() -> None:
    service, controller, _, recovery = recovery_workflow()

    def cancel_then_fail(_username: str, _recovery_code: str) -> RecoverySession:
        service.cancel_account_recovery()
        raise LauncherServiceError("รหัสกู้บัญชีไม่ถูกต้องหรือหมดอายุแล้ว")

    recovery.verify_recovery_code = cancel_then_fail  # type: ignore[method-assign]
    service.begin_account_recovery()

    with pytest.raises(LauncherServiceError):
        service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

    assert service.has_recovery_session is False
    assert controller.state.auth_status is AuthStatus.SIGNED_OUT


def test_starting_recovery_invalidates_inflight_normal_session_restore() -> None:
    service, controller, normal, _ = recovery_workflow()

    def restore_then_start_recovery() -> AuthenticatedUser:
        service.begin_account_recovery()
        return AuthenticatedUser("user-id", "testuser")

    normal.restore_session = restore_then_start_recovery  # type: ignore[method-assign]

    assert service.restore_session() is False
    assert controller.state.auth_status is AuthStatus.RECOVERY_CODE_ENTRY
    assert normal.claims == 0


def test_successful_recovery_clears_credentials_and_returns_to_login() -> None:
    service, controller, _, _ = recovery_workflow()
    service.begin_account_recovery()
    service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

    service.change_recovery_password("ValidPassword12!", "ValidPassword12!")

    assert controller.state.auth_status is AuthStatus.SIGNED_OUT
    assert service.has_recovery_session is False
    assert controller.state.user_id is None
    assert controller.state.session_id is None


def test_cancel_and_shutdown_discard_recovery_session() -> None:
    for action in ("cancel", "shutdown"):
        service, controller, _, _ = recovery_workflow()
        service.begin_account_recovery()
        service.verify_recovery_code("testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345")

        if action == "cancel":
            service.cancel_account_recovery()
        else:
            service.shutdown()

        assert service.has_recovery_session is False
        assert controller.state.auth_status is AuthStatus.SIGNED_OUT


class FakeHttpResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self._body


def http_error(status: int, payload: object) -> HTTPError:
    return HTTPError(
        "https://example.test/api",
        status,
        "error",
        {},
        BytesIO(json.dumps(payload).encode()),
    )


def test_http_verify_uses_exact_contract_and_strict_response(monkeypatch) -> None:
    captured = {}

    def urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeHttpResponse(
            200,
            {
                "ok": True,
                "recovery_session_id": "11111111-1111-4111-8111-111111111111",
                "recovery_session": "A" * 43,
                "scope": "change_password",
                "expires_at": "2026-08-09T05:00:00Z",
            },
        )

    monkeypatch.setattr("neko_launcher.infrastructure.account_recovery_gateway._open_no_redirect", urlopen)
    result = HttpAccountRecoveryGateway("https://example.test").verify_recovery_code(
        "testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345"
    )

    assert captured["url"].endswith("/api/account/recovery/verify")
    assert captured["body"] == {
        "username": "testuser",
        "recovery_code": "ABCD-EFGH-JKLM-NPQR-STUV-WX2345",
    }
    assert "Authorization" not in captured["headers"]
    assert result.token == "A" * 43


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"ok": True, "scope": "change_password"}, "ระบบกู้บัญชีตอบกลับไม่ถูกต้อง"),
        ({
            "ok": True,
            "recovery_session_id": "11111111-1111-4111-8111-111111111111",
            "recovery_session": "A" * 43,
            "scope": "normal_login",
            "expires_at": "2026-08-09T05:00:00Z",
        }, "ระบบกู้บัญชีตอบกลับไม่ถูกต้อง"),
        ({
            "ok": True,
            "recovery_session_id": "11111111-1111-4111-8111-111111111111",
            "recovery_session": "A" * 43,
            "scope": "change_password",
            "expires_at": "2026-08-09 05:00:00",
        }, "ระบบกู้บัญชีตอบกลับไม่ถูกต้อง"),
    ],
)
def test_http_verify_rejects_malformed_success(monkeypatch, payload, message) -> None:
    monkeypatch.setattr("neko_launcher.infrastructure.account_recovery_gateway._open_no_redirect", lambda *_args, **_kwargs: FakeHttpResponse(200, payload))
    with pytest.raises(LauncherServiceError, match=message):
        HttpAccountRecoveryGateway("https://example.test").verify_recovery_code(
            "testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345"
        )


def test_http_change_password_uses_bearer_and_exact_body(monkeypatch) -> None:
    captured = {}

    def urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        return FakeHttpResponse(200, {"ok": True, "completed": True, "state": "completed"})

    monkeypatch.setattr("neko_launcher.infrastructure.account_recovery_gateway._open_no_redirect", urlopen)
    HttpAccountRecoveryGateway("https://example.test").change_password(
        "A" * 43, "ValidPassword12!"
    )

    assert captured["headers"]["Authorization"] == f"Bearer {'A' * 43}"
    assert captured["body"] == {"new_password": "ValidPassword12!"}


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (400, "Recovery code is invalid or expired", "ไม่ถูกต้องหรือหมดอายุ"),
        (500, "Server error", "ระบบขัดข้อง"),
        (502, "Recovery backend returned an invalid response", "ระบบขัดข้อง"),
    ],
)
def test_http_verify_maps_only_safe_thai_errors(monkeypatch, status, error, expected) -> None:
    monkeypatch.setattr("neko_launcher.infrastructure.account_recovery_gateway._open_no_redirect", lambda *_a, **_k: (_ for _ in ()).throw(http_error(status, {"error": error})))
    with pytest.raises(LauncherServiceError, match=expected):
        HttpAccountRecoveryGateway("https://example.test").verify_recovery_code(
            "testuser", "ABCD-EFGH-JKLM-NPQR-STUV-WX2345"
        )


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (400, "Password must be 12-128 characters and include upper, lower, number, and symbol", "12-128"),
        (401, "Recovery session is invalid or expired", "หมดอายุ"),
        (409, "Retry the same recovery session and password", "รหัสผ่านเดิม"),
        (503, "Recovery backend is temporarily unavailable", "รหัสผ่านเดิม"),
        (503, "Password was updated but recovery finalization is pending; retry the same request", "รหัสผ่านเดิม"),
    ],
)
def test_http_change_maps_retry_and_expiry_semantics(monkeypatch, status, error, expected) -> None:
    monkeypatch.setattr("neko_launcher.infrastructure.account_recovery_gateway._open_no_redirect", lambda *_a, **_k: (_ for _ in ()).throw(http_error(status, {"error": error})))
    with pytest.raises(LauncherServiceError, match=expected):
        HttpAccountRecoveryGateway("https://example.test").change_password(
            "A" * 43, "ValidPassword12!"
        )


def test_network_failure_during_change_requires_exact_same_retry(monkeypatch) -> None:
    monkeypatch.setattr("neko_launcher.infrastructure.account_recovery_gateway._open_no_redirect", lambda *_a, **_k: (_ for _ in ()).throw(URLError("secret transport detail")))
    with pytest.raises(LauncherServiceError, match="รหัสผ่านเดิม") as raised:
        HttpAccountRecoveryGateway("https://example.test").change_password(
            "A" * 43, "ValidPassword12!"
        )
    assert "secret transport detail" not in str(raised.value)


def test_recovery_http_client_refuses_redirects() -> None:
    assert (
        _NoRedirectHandler().redirect_request(
            None, None, 307, "redirect", {}, "https://other.example.test"
        )
        is None
    )
