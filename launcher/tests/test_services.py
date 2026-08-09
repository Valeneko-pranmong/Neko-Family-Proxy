from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import (
    DeviceAuthorizationDenied,
    EntitlementUnavailable,
    LauncherServiceError,
)
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.models import (
    AuthenticatedUser,
    AuthStatus,
    CouponRedemption,
    Entitlement,
    EntitlementStatus,
    RegistrationResult,
    SessionClaim,
    SessionTerminationReason,
)
from neko_launcher.domain.events import EntitlementLoaded, GameProcessStateChanged
from neko_launcher.infrastructure.event_bus import EventBus


class FakeGateway:
    def __init__(self) -> None:
        self.has_access = False
        self.heartbeat_alive = True
        self.heartbeat_error = False
        self.signed_out = False
        self.sign_out_error = False
        self.local_session_cleared = False
        self.changed_password: str | None = None
        self.released: list[str] = []
        self.last_signup: tuple[str, str] | None = None
        self.release_started: Event | None = None
        self.release_continue: Event | None = None
        self.claim_error: Exception | None = None
        self.termination_reason = SessionTerminationReason.REVOKED
        self.termination_error = False
        self.before_termination_lookup: Callable[[], None] | None = None

    def sign_up(self, username: str, password: str) -> RegistrationResult:
        self.last_signup = (username, password)
        return RegistrationResult(username, True)

    def sign_in(self, username: str, password: str) -> AuthenticatedUser:
        return AuthenticatedUser("user-id", username)

    def restore_session(self) -> AuthenticatedUser | None:
        return AuthenticatedUser("user-id", "user@example.com")

    def sign_out(self) -> None:
        if self.sign_out_error:
            raise RuntimeError("remote sign-out failed")
        self.signed_out = True

    def clear_local_session(self) -> None:
        self.local_session_cleared = True

    def change_password(self, password: str) -> None:
        self.changed_password = password

    def auth_identifier_for_username(self, username: str) -> str:
        return f"{username}@project.supabase.co"

    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
        if self.claim_error is not None:
            raise self.claim_error
        if not self.has_access:
            raise EntitlementUnavailable("ยังไม่มีสิทธิ์")
        return SessionClaim(
            "session-id",
            Entitlement(
                product_code,
                EntitlementStatus.ACTIVE,
                datetime.now(UTC) + timedelta(days=30),
            ),
        )

    def heartbeat_session(self, session_id: str) -> bool:
        if self.heartbeat_error:
            raise RuntimeError("network")
        return self.heartbeat_alive

    def session_termination_reason(
        self, session_id: str
    ) -> SessionTerminationReason:
        if self.before_termination_lookup is not None:
            self.before_termination_lookup()
        if self.termination_error:
            raise RuntimeError("reason lookup failed")
        return self.termination_reason

    def release_session(self, session_id: str) -> bool:
        if self.release_started is not None:
            self.release_started.set()
        if self.release_continue is not None:
            self.release_continue.wait()
        self.released.append(session_id)
        return True

    def redeem_coupon(self, code: str) -> CouponRedemption:
        self.has_access = True
        return CouponRedemption(
            "neko-family-proxy",
            30,
            datetime.now(UTC) + timedelta(days=30),
        )


class FakeInstallation:
    key_hash = "a" * 64
    display_name = "Test PC"


@pytest.fixture
def workflow() -> tuple[LauncherService, ApplicationController, FakeGateway]:
    bus = EventBus()
    controller = ApplicationController(bus)
    gateway = FakeGateway()
    service = LauncherService(
        controller,
        gateway,
        gateway,
        FakeInstallation(),
        "neko-family-proxy",
    )
    return service, controller, gateway


def test_sign_in_without_license_keeps_account_ready_for_coupon(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, _ = workflow

    service.sign_in("TestUser", "password123")

    assert controller.state.user_email == "testuser"
    assert controller.state.auth_status is AuthStatus.AUTHENTICATED
    assert controller.state.entitlement is None
    assert controller.state.session_id is None
    assert "เติมวันด้วยคูปอง" in (controller.state.last_error or "")


def test_safe_claim_error_after_valid_credentials_preserves_authenticated_state(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.claim_error = LauncherServiceError("เริ่มเซสชันไม่สำเร็จ กรุณาลองใหม่")

    with pytest.raises(LauncherServiceError, match="เริ่มเซสชันไม่สำเร็จ"):
        service.sign_in("testuser", "password123")

    assert controller.state.auth_status is AuthStatus.AUTHENTICATED
    assert controller.state.user_email == "testuser"
    assert controller.state.session_id is None


def test_sign_in_stays_signed_out_when_device_authorization_is_denied(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.claim_error = DeviceAuthorizationDenied(
        "เครื่องนี้ไม่สามารถใช้งานบัญชีนี้ได้ กรุณาติดต่อฝ่ายบริการ"
    )

    with pytest.raises(DeviceAuthorizationDenied):
        service.sign_in("testuser", "password123")

    assert gateway.signed_out is True
    assert gateway.local_session_cleared is True
    assert controller.state.user_id is None
    assert controller.state.auth_status.value == "signed_out"


def test_restore_session_stays_signed_out_when_device_authorization_is_denied(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.claim_error = DeviceAuthorizationDenied(
        "เครื่องนี้ไม่สามารถใช้งานบัญชีนี้ได้ กรุณาติดต่อฝ่ายบริการ"
    )

    assert service.restore_session() is False

    assert gateway.signed_out is True
    assert gateway.local_session_cleared is True
    assert controller.state.user_id is None
    assert controller.state.auth_status.value == "signed_out"


def test_sign_up_normalizes_username_and_uses_only_username_and_password(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, _, gateway = workflow

    service.sign_up(" TestUser ", "password123")

    assert gateway.last_signup == ("testuser", "password123")


def test_redeem_coupon_refreshes_entitlement_and_claims_session(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, _ = workflow
    service.sign_in("testuser", "password123")

    result = service.redeem_coupon("NEKO-test")

    assert result.days_added == 30
    assert controller.state.entitlement is not None
    assert controller.state.entitlement.status is EntitlementStatus.ACTIVE
    assert controller.state.session_id == "session-id"


def test_failed_heartbeat_revokes_launcher_session(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.heartbeat_alive = False

    assert service.heartbeat() is False
    assert gateway.signed_out is True
    assert gateway.local_session_cleared is True
    assert controller.state.auth_status is AuthStatus.SIGNED_OUT
    assert controller.state.user_id is None
    assert controller.state.session_id is None
    assert controller.state.entitlement is None
    assert "เซสชัน" in (controller.state.last_error or "")


def test_rejected_heartbeat_invalidates_authorization_before_reason_lookup(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.heartbeat_alive = False
    state_during_lookup = []
    gateway.before_termination_lookup = lambda: state_during_lookup.append(
        controller.state
    )

    assert service.heartbeat() is False

    observed = state_during_lookup[0]
    assert observed.session_id is None
    assert observed.entitlement is None
    assert observed.proxy_status.value == "stopped"


def test_failed_reason_lookup_signs_out_with_generic_revoked_message(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.heartbeat_alive = False
    gateway.termination_error = True

    assert service.heartbeat() is False

    assert controller.state.auth_status is AuthStatus.SIGNED_OUT
    assert controller.state.session_id is None
    assert controller.state.entitlement is None
    assert "เซสชันปัจจุบันใช้งานไม่ได้แล้ว" in (
        controller.state.last_error or ""
    )


def test_rejected_heartbeat_never_defers_invalidation_for_running_game(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    controller.dispatch(GameProcessStateChanged(True))
    controller.dispatch(EntitlementLoaded(None))
    gateway.heartbeat_alive = False
    state_during_lookup = []
    gateway.before_termination_lookup = lambda: state_during_lookup.append(
        controller.state
    )

    assert service.heartbeat() is False

    observed = state_during_lookup[0]
    assert observed.session_id is None
    assert observed.entitlement is None
    assert observed.deferred_session_revocation_reason is None


@pytest.mark.parametrize(
    ("termination_reason", "expected_message"),
    [
        (SessionTerminationReason.REPLACED, "การเข้าสู่ระบบใหม่กว่า"),
        (SessionTerminationReason.REVOKED, "ใช้งานไม่ได้แล้ว"),
        (SessionTerminationReason.INSTALLATION_REVOKED, "เครื่องนี้"),
        (SessionTerminationReason.LICENSE_UNAVAILABLE, "สิทธิ์ใช้งาน"),
        (SessionTerminationReason.ACCOUNT_RESTRICTED, "บัญชี"),
    ],
)
def test_failed_heartbeat_explains_the_safe_termination_reason(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
    termination_reason: SessionTerminationReason,
    expected_message: str,
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.heartbeat_alive = False
    gateway.termination_reason = termination_reason

    assert service.heartbeat() is False

    assert expected_message in (controller.state.last_error or "")


def test_failed_heartbeat_clears_local_session_when_remote_sign_out_fails(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.heartbeat_alive = False
    gateway.sign_out_error = True

    assert service.heartbeat() is False

    assert gateway.local_session_cleared is True
    assert controller.state.auth_status is AuthStatus.SIGNED_OUT


def test_device_denial_preserves_typed_error_when_remote_sign_out_fails(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.claim_error = DeviceAuthorizationDenied("installation_revoked")
    gateway.sign_out_error = True

    with pytest.raises(DeviceAuthorizationDenied, match="installation_revoked"):
        service.sign_in("testuser", "password123")

    assert gateway.local_session_cleared is True
    assert controller.state.auth_status is AuthStatus.SIGNED_OUT


def test_transient_heartbeat_errors_need_three_failures_before_revocation(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.heartbeat_error = True

    assert service.heartbeat() is True
    assert service.heartbeat() is True
    assert controller.state.session_id == "session-id"

    assert service.heartbeat() is False
    assert controller.state.session_id is None
    assert "เครือข่าย" in (controller.state.last_error or "")


def test_heartbeat_failure_counter_resets_for_a_new_session(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.heartbeat_error = True

    assert service.heartbeat() is True
    assert service.heartbeat() is True
    assert service.heartbeat() is False
    assert controller.state.auth_status is AuthStatus.SIGNED_OUT

    gateway.heartbeat_error = False
    service.sign_in("testuser", "password123")
    gateway.heartbeat_error = True

    assert service.heartbeat() is True
    assert service.heartbeat() is True
    assert controller.state.session_id == "session-id"


def test_sign_out_releases_launcher_session_and_auth_session(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")

    service.sign_out()

    assert gateway.released == ["session-id"]
    assert gateway.signed_out is True
    assert controller.state.user_id is None


def test_change_password_requires_login_and_updates_auth_gateway(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow

    with pytest.raises(Exception, match="เข้าสู่ระบบก่อน"):
        service.change_password("new-password")

    service.sign_in("testuser", "password123")
    service.change_password("new-password")

    assert gateway.changed_password == "new-password"
    assert controller.state.user_email == "testuser"


def test_shutdown_does_not_wait_for_a_stalled_remote_release(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, controller, gateway = workflow
    gateway.has_access = True
    service.sign_in("testuser", "password123")
    gateway.release_started = Event()
    gateway.release_continue = Event()

    service.shutdown(remote_release_grace=0.01)

    assert gateway.release_started.is_set()
    assert controller.state.session_id is None
    gateway.release_continue.set()


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("ab", "password123"),
        ("testuser", "short"),
    ],
)
def test_credentials_are_validated_before_network_calls(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
    username: str,
    password: str,
) -> None:
    service, _, _ = workflow

    with pytest.raises(Exception):
        service.sign_in(username, password)
