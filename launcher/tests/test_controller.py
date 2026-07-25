from neko_launcher.application.controller import ApplicationController
from neko_launcher.domain.events import (
    AuthStarted,
    AuthSucceeded,
    EntitlementLoaded,
    StartProxyRequested,
    StateChanged,
)
from neko_launcher.domain.models import Entitlement, EntitlementStatus, ProxyStatus
from neko_launcher.infrastructure.event_bus import EventBus


class FakeProxy:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def is_running(self) -> bool:
        return self.running


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

    controller.dispatch(StartProxyRequested())

    assert proxy.running is True
    assert controller.state.proxy_status is ProxyStatus.RUNNING
    states = [event.state for event in bus.drain() if isinstance(event, StateChanged)]
    assert states[-1].proxy_status is ProxyStatus.RUNNING
