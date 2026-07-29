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
from datetime import UTC, datetime, timedelta
from neko_launcher.domain.models import (
    Entitlement,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
)
from neko_launcher.infrastructure.event_bus import EventBus


class FakeProxy:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

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

    controller.dispatch(StartProxyRequested())

    assert proxy.running is True
    assert controller.state.proxy_status is ProxyStatus.RUNNING
    states = [event.state for event in bus.drain() if isinstance(event, StateChanged)]
    assert states[-1].proxy_status is ProxyStatus.RUNNING


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
    controller.dispatch(StartProxyRequested())
    controller.dispatch(LaunchTweakerRequested("C:/Games/Tweaker.exe"))

    controller.shutdown()

    assert proxy.running is False
    assert game.running is False
    assert controller.state.proxy_status is ProxyStatus.STOPPED
    assert controller.state.game_status is GameStatus.STOPPED


def test_proxy_refuses_to_start_without_entitlement_and_session() -> None:
    bus = EventBus()
    proxy = FakeProxy()
    controller = ApplicationController(bus, proxy)
    controller.dispatch(AuthSucceeded("user-id", "user@example.com"))

    controller.dispatch(StartProxyRequested())

    assert proxy.running is False
    assert controller.state.proxy_status is ProxyStatus.FAILED
    assert controller.state.last_error is not None


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
    controller.dispatch(StartProxyRequested())
    controller.dispatch(LaunchTweakerRequested("C:/Games/Tweaker.exe"))
    controller.dispatch(GameProcessStateChanged(True))
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
    controller.dispatch(StartProxyRequested())
    controller.dispatch(GameProcessStateChanged(True))

    controller.dispatch(GameProcessStateChanged(False))

    assert proxy.running is False
    assert controller.state.proxy_status is ProxyStatus.STOPPED
    assert controller.state.session_id == "session-id"
