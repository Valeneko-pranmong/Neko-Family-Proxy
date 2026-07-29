from datetime import UTC, datetime, timedelta

import pytest

from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import EntitlementUnavailable
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.models import (
    AuthenticatedUser,
    CouponRedemption,
    Entitlement,
    EntitlementStatus,
    RegistrationResult,
    SessionClaim,
)
from neko_launcher.infrastructure.event_bus import EventBus


class FakeGateway:
    def __init__(self) -> None:
        self.has_access = False
        self.heartbeat_alive = True
        self.heartbeat_error = False
        self.signed_out = False
        self.changed_password: str | None = None
        self.released: list[str] = []
        self.last_signup: tuple[str, str, str] | None = None
        self.last_reset_email: str | None = None
        self.reset_error = False

    def sign_up(self, username: str, password: str, email: str) -> RegistrationResult:
        self.last_signup = (username, password, email)
        return RegistrationResult(username, True)

    def sign_in(self, email: str, password: str) -> AuthenticatedUser:
        return AuthenticatedUser("user-id", email)

    def restore_session(self) -> AuthenticatedUser | None:
        return AuthenticatedUser("user-id", "user@example.com")

    def sign_out(self) -> None:
        self.signed_out = True

    def change_password(self, password: str) -> None:
        self.changed_password = password

    def lookup_auth_email(self, username: str) -> str | None:
        if username == "norecovery":
            return None
        if username == "networkfail":
            raise RuntimeError("network error")
        return f"{username}@example.com"

    def request_password_reset(self, email: str) -> None:
        if self.reset_error:
            raise RuntimeError("provider unavailable")
        self.last_reset_email = email

    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
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

    def release_session(self, session_id: str) -> bool:
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
    assert controller.state.entitlement is None
    assert controller.state.session_id is None


def test_sign_up_validates_and_forwards_recovery_email(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, _, gateway = workflow

    service.sign_up(" TestUser ", "password123", " USER@Example.COM ")

    assert gateway.last_signup == (
        "testuser",
        "password123",
        "user@example.com",
    )


@pytest.mark.parametrize("email", ["", "missing-at.example.com", "user@example"])
def test_sign_up_rejects_invalid_recovery_email(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
    email: str,
) -> None:
    service, _, gateway = workflow

    with pytest.raises(Exception, match="อีเมล"):
        service.sign_up("testuser", "password123", email)

    assert gateway.last_signup is None


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
    assert controller.state.session_id is None
    assert controller.state.entitlement is None


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


def test_password_reset_looks_up_auth_email_and_sends_link(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, _, gateway = workflow

    service.request_password_reset(" TestUser ")

    assert gateway.last_reset_email == "testuser@example.com"


@pytest.mark.parametrize("username", ["norecovery", "networkfail"])
def test_password_reset_silent_success_when_lookup_cannot_deliver(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
    username: str,
) -> None:
    service, _, gateway = workflow

    service.request_password_reset(username)

    assert gateway.last_reset_email is None


def test_password_reset_silent_success_on_delivery_error(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
) -> None:
    service, _, gateway = workflow
    gateway.reset_error = True

    service.request_password_reset("testuser")

    assert gateway.last_reset_email is None


@pytest.mark.parametrize("username", ["", "ab", "user@name"])
def test_password_reset_validates_username_before_lookup(
    workflow: tuple[LauncherService, ApplicationController, FakeGateway],
    username: str,
) -> None:
    service, _, gateway = workflow

    with pytest.raises(Exception):
        service.request_password_reset(username)

    assert gateway.last_reset_email is None
