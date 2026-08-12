from datetime import UTC, datetime, timedelta

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
)
from neko_launcher.application.controller import ApplicationController
from neko_launcher.domain.events import (
    AuthStarted,
    AuthSucceeded,
    EntitlementLoaded,
    GameProcessStateChanged,
    LaunchTweakerRequested,
    SessionClaimed,
    SessionRevoked,
    StartProxyRequested,
    StateChanged,
)
from neko_launcher.domain.models import (
    AuthStatus,
    Entitlement,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
)
from neko_launcher.infrastructure.event_bus import EventBus


class FakeProxy:
    def __init__(self) -> None:
        self.running = False
        self.host_owned = False
        self.stop_count = 0
        self.shutdown_count = 0

    def has_owned_host(self) -> bool:
        return self.host_owned

    def start(self) -> None:
        self.running = True
        self.host_owned = True

    def stop(self) -> None:
        self.running = False
        self.stop_count += 1

    def shutdown(self) -> None:
        self.running = False
        self.host_owned = False
        self.shutdown_count += 1


class FailingStartProxy(FakeProxy):
    def __init__(self, error: AuthorizedCoreError) -> None:
        super().__init__()
        self._error = error

    def start(self) -> None:
        raise self._error

class FakeGame:
    def __init__(self) -> None:
        self.running = False
        self.executable = ""

    def start(self, executable) -> None:
        self.executable = str(executable)
        self.running = True

    def stop(self) -> None:
        self.running = False

def test_auth_and_entitlement_state_transitions() -> None:
    bus = EventBus()
    controller = ApplicationController(bus)

    controller.dispatch(AuthStarted("user@example.com"))
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE)
        )
    )

    state = controller.state
    assert state.user_id == "user-id"
    assert state.entitlement is not None
    assert state.entitlement.status is EntitlementStatus.ACTIVE


def test_proxy_commands_use_gateway_and_update_state() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE)
        )
    )
    controller.dispatch(SessionClaimed("session-id"))
    controller.dispatch(GameProcessStateChanged(True))

    controller.dispatch(StartProxyRequested())

    assert proxy.running is True
    assert controller.state.proxy_status is ProxyStatus.RUNNING
    states = [event.state for event in bus.drain() if isinstance(event, StateChanged)]
    assert states[-1].proxy_status is ProxyStatus.RUNNING


@pytest.mark.parametrize(
    "error_code",
    [
        AuthorizedCoreErrorCode.SESSION_INACTIVE,
        AuthorizedCoreErrorCode.ENTITLEMENT_INACTIVE,
        AuthorizedCoreErrorCode.HEARTBEAT_STALE,
    ],
)
def test_authority_start_failure_does_not_lock_or_revoke_local_session(
    error_code: AuthorizedCoreErrorCode,
) -> None:
    bus = EventBus()
    proxy = FailingStartProxy(AuthorizedCoreError(error_code))
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE))
    )
    controller.dispatch(SessionClaimed("session-id"))
    controller.dispatch(GameProcessStateChanged(True))

    controller.dispatch(StartProxyRequested())

    state = controller.state
    assert state.auth_status is AuthStatus.AUTHENTICATED
    assert state.session_id == "session-id"
    assert state.entitlement is not None
    assert state.entitlement.status is EntitlementStatus.ACTIVE
    assert state.proxy_status is ProxyStatus.FAILED
    assert state.last_error == "เริ่มการเชื่อมต่อไม่สำเร็จ กรุณาลองใหม่"
    assert error_code.value not in state.last_error


def test_post_permit_target_unavailable_does_not_enable_automatic_retry() -> None:
    bus = EventBus()
    proxy = FailingStartProxy(
        AuthorizedCoreError(
            AuthorizedCoreErrorCode.TARGET_UNAVAILABLE,
            retry_safe=False,
        )
    )
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE))
    )
    controller.dispatch(SessionClaimed("session-id"))
    controller.dispatch(GameProcessStateChanged(True))

    controller.dispatch(StartProxyRequested())

    assert controller.state.proxy_status is ProxyStatus.FAILED
    assert controller.state.proxy_start_retry_safe is False


def test_shutdown_stops_only_launcher_owned_proxy_and_tweaker() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    game = FakeGame()
    controller = ApplicationController(bus, proxy, game)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE)
        )
    )
    controller.dispatch(SessionClaimed("session-id"))
    controller.dispatch(GameProcessStateChanged(True))
    controller.dispatch(StartProxyRequested())
    controller.dispatch(LaunchTweakerRequested("C:/Games/Tweaker.exe"))

    controller.shutdown()

    assert proxy.running is False
    assert proxy.shutdown_count == 1
    assert proxy.stop_count == 0
    assert game.running is False
    assert controller.state.proxy_status is ProxyStatus.STOPPED
    assert controller.state.game_status is GameStatus.STOPPED


def test_logout_gracefully_shuts_down_owned_core_host() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE)
        )
    )
    controller.dispatch(SessionClaimed("session-id"))
    controller.dispatch(GameProcessStateChanged(True))
    controller.dispatch(StartProxyRequested())

    controller.sign_out()

    assert proxy.shutdown_count == 1
    assert proxy.stop_count == 0
    assert proxy.host_owned is False
    assert controller.state.auth_status.value == "signed_out"


def test_proxy_refuses_to_start_without_entitlement_and_session() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))

    controller.dispatch(StartProxyRequested())

    assert proxy.running is False
    assert controller.state.proxy_status is ProxyStatus.FAILED
    assert controller.state.last_error is not None


def test_proxy_refuses_to_start_before_exact_game_process_is_detected() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE)
        )
    )
    controller.dispatch(SessionClaimed("session-id"))

    controller.dispatch(StartProxyRequested())

    assert proxy.running is False
    assert controller.state.proxy_status is ProxyStatus.FAILED
    assert "pso2.exe" in (controller.state.last_error or "")


def test_auto_tweaker_launch_does_not_start_proxy_before_pso2_process() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    game = FakeGame()
    controller = ApplicationController(bus, proxy, game)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE)
        )
    )
    controller.dispatch(SessionClaimed("session-id"))

    controller.dispatch(LaunchTweakerRequested("C:/Games/Tweaker.exe"))

    assert game.running is True
    assert proxy.running is False
    assert controller.state.game_status is GameStatus.RUNNING


def test_expired_entitlement_cannot_start_proxy_or_tweaker() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    game = FakeGame()
    controller = ApplicationController(bus, proxy, game)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement(
                "neko-family-proxy",
                EntitlementStatus.ACTIVE,
                datetime.now(UTC) - timedelta(minutes=1),
            )
        )
    )
    controller.dispatch(SessionClaimed("session-id"))

    controller.dispatch(StartProxyRequested())

    assert proxy.running is False
    assert controller.state.proxy_status is ProxyStatus.FAILED
    assert "เติมคูปอง" in (controller.state.last_error or "")


def test_expiry_waits_for_pso2_to_exit_before_stopping_proxy() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    game = FakeGame()
    controller = ApplicationController(bus, proxy, game)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement(
                "neko-family-proxy",
                EntitlementStatus.ACTIVE,
                datetime.now(UTC) + timedelta(minutes=1),
            )
        )
    )
    controller.dispatch(SessionClaimed("session-id"))
    controller.dispatch(GameProcessStateChanged(True))
    controller.dispatch(StartProxyRequested())
    controller.dispatch(LaunchTweakerRequested("C:/Games/Tweaker.exe"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement(
                "neko-family-proxy",
                EntitlementStatus.ACTIVE,
                datetime.now(UTC) - timedelta(minutes=1),
            )
        )
    )

    controller.dispatch(SessionRevoked("สิทธิ์หมดอายุแล้ว"))

    assert proxy.running is True
    assert game.running is True
    assert controller.state.session_id == "session-id"
    assert controller.state.deferred_session_revocation_reason is not None

    controller.dispatch(GameProcessStateChanged(False))

    assert proxy.running is False
    assert game.running is True
    assert controller.state.session_id is None
    assert controller.state.entitlement is None


def test_proxy_stops_when_pso2_exits_while_entitlement_is_still_valid() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))
    controller.dispatch(
        EntitlementLoaded(
            Entitlement("neko-family-proxy", EntitlementStatus.ACTIVE)
        )
    )
    controller.dispatch(SessionClaimed("session-id"))
    controller.dispatch(GameProcessStateChanged(True))
    controller.dispatch(StartProxyRequested())

    controller.dispatch(GameProcessStateChanged(False))

    assert proxy.running is False
    assert controller.state.proxy_status is ProxyStatus.STOPPED
    assert controller.state.session_id == "session-id"
    assert proxy.stop_count == 1
    assert proxy.shutdown_count == 0
    assert proxy.host_owned is True
