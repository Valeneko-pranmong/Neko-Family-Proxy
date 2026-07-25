from __future__ import annotations

from dataclasses import replace
from threading import RLock

from neko_launcher.domain.events import (
    AuthFailed,
    AuthStarted,
    AuthSucceeded,
    EntitlementLoaded,
    ErrorOccurred,
    Event,
    ProxyStarted,
    ProxyStopped,
    SessionClaimed,
    SessionRevoked,
    StartProxyRequested,
    StateChanged,
    StopProxyRequested,
)
from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    EntitlementStatus,
    ProxyStatus,
)

from .ports import EventPublisher, ProxyGateway


class ApplicationController:
    """Owns application state and translates events into state transitions."""

    def __init__(
        self,
        event_bus: EventPublisher,
        proxy_gateway: ProxyGateway | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._proxy_gateway = proxy_gateway
        self._state = AppState()
        self._lock = RLock()

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    def dispatch(self, event: Event) -> None:
        if isinstance(event, AuthStarted):
            self._update(
                auth_status=AuthStatus.AUTHENTICATING,
                user_email=event.email,
                last_error=None,
            )
        elif isinstance(event, AuthSucceeded):
            self._update(
                auth_status=AuthStatus.AUTHENTICATED,
                user_id=event.user_id,
                user_email=event.email,
                last_error=None,
            )
        elif isinstance(event, AuthFailed):
            self._update(auth_status=AuthStatus.FAILED, last_error=event.message)
        elif isinstance(event, EntitlementLoaded):
            status = (
                event.entitlement.status
                if event.entitlement is not None
                else EntitlementStatus.NONE
            )
            entitlement = event.entitlement
            if entitlement is None:
                self._update(entitlement=None)
            else:
                self._update(
                    entitlement=replace(entitlement, status=status),
                    last_error=None,
                )
        elif isinstance(event, SessionClaimed):
            self._update(session_id=event.session_id, last_error=None)
        elif isinstance(event, SessionRevoked):
            self._update(session_id=None, last_error=event.reason)
        elif isinstance(event, StartProxyRequested):
            self._start_proxy()
        elif isinstance(event, StopProxyRequested):
            self._stop_proxy()
        elif isinstance(event, ProxyStarted):
            self._update(proxy_status=ProxyStatus.RUNNING, last_error=None)
        elif isinstance(event, ProxyStopped):
            self._update(proxy_status=ProxyStatus.STOPPED)
        elif isinstance(event, ErrorOccurred):
            self._update(last_error=event.message)

    def sign_out(self) -> None:
        self._update(
            auth_status=AuthStatus.SIGNED_OUT,
            user_id=None,
            user_email=None,
            entitlement=None,
            session_id=None,
            proxy_status=ProxyStatus.STOPPED,
            last_error=None,
        )

    def _start_proxy(self) -> None:
        if self._proxy_gateway is None:
            self._update(proxy_status=ProxyStatus.FAILED, last_error="Proxy service unavailable")
            return
        self._update(proxy_status=ProxyStatus.STARTING, last_error=None)
        try:
            self._proxy_gateway.start()
        except Exception as exc:
            self._update(proxy_status=ProxyStatus.FAILED, last_error=str(exc))
        else:
            self._update(proxy_status=ProxyStatus.RUNNING)

    def _stop_proxy(self) -> None:
        if self._proxy_gateway is None:
            self._update(proxy_status=ProxyStatus.STOPPED)
            return
        self._update(proxy_status=ProxyStatus.STOPPING)
        try:
            self._proxy_gateway.stop()
        except Exception as exc:
            self._update(proxy_status=ProxyStatus.FAILED, last_error=str(exc))
        else:
            self._update(proxy_status=ProxyStatus.STOPPED)

    def _update(self, **changes: object) -> None:
        with self._lock:
            self._state = replace(self._state, **changes)
            state = self._state
        self._event_bus.publish(StateChanged(state))
