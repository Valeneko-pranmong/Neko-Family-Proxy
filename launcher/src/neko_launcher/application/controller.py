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
    LaunchGameRequested,
    SessionClaimed,
    SessionRevoked,
    StartProxyRequested,
    StartUsageRequested,
    StateChanged,
    StopGameRequested,
    StopProxyRequested,
)
from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    EntitlementStatus,
    GameStatus,
    ProxyStatus,
)

from .ports import EventPublisher, GameGateway, ProxyGateway


class ApplicationController:
    """Owns application state and translates events into state transitions."""

    def __init__(
        self,
        event_bus: EventPublisher,
        proxy_gateway: ProxyGateway | None = None,
        game_gateway: GameGateway | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._proxy_gateway = proxy_gateway
        self._game_gateway = game_gateway
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
            if self.state.proxy_status in {
                ProxyStatus.STARTING,
                ProxyStatus.RUNNING,
            }:
                self._stop_proxy()
            else:
                self._stop_game()
            self._update(
                session_id=None,
                entitlement=None,
                last_error=event.reason,
            )
        elif isinstance(event, StartProxyRequested):
            self._start_proxy()
        elif isinstance(event, StartUsageRequested):
            self._start_usage(event.executable)
        elif isinstance(event, StopProxyRequested):
            self._stop_proxy()
        elif isinstance(event, LaunchGameRequested):
            self._launch_game(event.executable)
        elif isinstance(event, StopGameRequested):
            self._stop_game()
        elif isinstance(event, ErrorOccurred):
            self._update(last_error=event.message)

    def sign_out(self) -> None:
        self._stop_game()
        self._update(
            auth_status=AuthStatus.SIGNED_OUT,
            user_id=None,
            user_email=None,
            entitlement=None,
            session_id=None,
            proxy_status=ProxyStatus.STOPPED,
            game_status=GameStatus.STOPPED,
            last_error=None,
        )

    def _start_proxy(self) -> None:
        state = self.state
        if state.auth_status is not AuthStatus.AUTHENTICATED:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="กรุณาเข้าสู่ระบบก่อนเริ่มใช้งาน",
            )
            return
        if (
            state.entitlement is None
            or state.entitlement.status is not EntitlementStatus.ACTIVE
            or state.session_id is None
        ):
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="บัญชีนี้ยังไม่มีวันใช้งาน กรุณาเติมคูปองก่อน",
            )
            return
        if self._proxy_gateway is None:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="เริ่มการเชื่อมต่อไม่ได้ กรุณาลองใหม่",
            )
            return
        self._update(proxy_status=ProxyStatus.STARTING, last_error=None)
        try:
            self._proxy_gateway.start()
        except Exception:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="เริ่มการเชื่อมต่อไม่สำเร็จ กรุณาลองใหม่",
            )
        else:
            self._update(proxy_status=ProxyStatus.RUNNING)

    def _start_usage(self, executable: str) -> None:
        """Start ProxyCore first, then launch the configured Tweaker."""
        if not executable.strip():
            self._update(
                game_status=GameStatus.FAILED,
                last_error="กรุณาเลือกไฟล์เปิดเกมก่อนเริ่มใช้งาน",
            )
            return

        # _start_proxy performs all authentication, entitlement, and session
        # checks.  Do not attempt to launch Tweaker when ProxyCore failed.
        if self.state.proxy_status is not ProxyStatus.RUNNING:
            self._start_proxy()
        if self.state.proxy_status is ProxyStatus.RUNNING:
            self._launch_game(executable)

    def _stop_proxy(self) -> None:
        self._stop_game()
        if self._proxy_gateway is None:
            self._update(proxy_status=ProxyStatus.STOPPED)
            return
        self._update(proxy_status=ProxyStatus.STOPPING)
        try:
            self._proxy_gateway.stop()
        except Exception:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="หยุดการเชื่อมต่อไม่สำเร็จ กรุณาลองใหม่",
            )
        else:
            self._update(proxy_status=ProxyStatus.STOPPED)

    def _launch_game(self, executable: str) -> None:
        state = self.state
        if state.auth_status is not AuthStatus.AUTHENTICATED:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="กรุณาเข้าสู่ระบบก่อนเปิดเกม",
            )
            return
        if (
            state.entitlement is None
            or state.entitlement.status is not EntitlementStatus.ACTIVE
            or state.session_id is None
        ):
            self._update(
                game_status=GameStatus.FAILED,
                last_error="บัญชีนี้ยังไม่มีวันใช้งาน กรุณาเติมคูปองก่อน",
            )
            return
        if state.proxy_status is not ProxyStatus.RUNNING:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="กรุณากดเริ่มใช้งานก่อนเปิดเกม",
            )
            return
        if self._game_gateway is None:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="เปิดเกมไม่ได้ กรุณาลองใหม่",
            )
            return
        self._update(game_status=GameStatus.STARTING, last_error=None)
        try:
            from pathlib import Path

            self._game_gateway.start(Path(executable))
        except Exception:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="เปิดเกมไม่สำเร็จ กรุณาตรวจสอบไฟล์ที่เลือก",
            )
        else:
            self._update(game_status=GameStatus.RUNNING)

    def _stop_game(self) -> None:
        if self._game_gateway is None:
            self._update(game_status=GameStatus.STOPPED)
            return
        if self.state.game_status is not GameStatus.RUNNING:
            return
        try:
            self._game_gateway.stop()
        except Exception:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="ปิดเกมไม่สำเร็จ กรุณาลองใหม่",
            )
        else:
            self._update(game_status=GameStatus.STOPPED)

    def _update(self, **changes: object) -> None:
        with self._lock:
            self._state = replace(self._state, **changes)
            state = self._state
        self._event_bus.publish(StateChanged(state))
