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
    GameProcessStateChanged,
    LaunchTweakerRequested,
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
    GameStatus,
    ProxyStatus,
    entitlement_is_active,
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
            self._revoke_session(event.reason)
        elif isinstance(event, GameProcessStateChanged):
            state = self.state
            self._update(game_process_running=event.running)
            deferred_reason = state.deferred_session_revocation_reason
            if not event.running and deferred_reason is not None:
                self._revoke_session(
                    deferred_reason,
                    allow_defer=False,
                )
            elif (
                not event.running
                and state.session_id is not None
                and not entitlement_is_active(state.entitlement)
            ):
                self._revoke_session("สิทธิ์หมดอายุแล้ว", allow_defer=False)
            elif not event.running and state.proxy_status in {
                ProxyStatus.STARTING,
                ProxyStatus.RUNNING,
            }:
                self._stop_proxy()
        elif isinstance(event, StartProxyRequested):
            self._start_proxy()
        elif isinstance(event, StopProxyRequested):
            self._stop_proxy()
        elif isinstance(event, LaunchTweakerRequested):
            self._launch_tweaker(event.executable)
        elif isinstance(event, ErrorOccurred):
            self._update(last_error=event.message)

    def sign_out(self) -> None:
        self._stop_proxy()
        self._update(
            auth_status=AuthStatus.SIGNED_OUT,
            user_id=None,
            user_email=None,
            entitlement=None,
            session_id=None,
            proxy_status=ProxyStatus.STOPPED,
            game_status=GameStatus.STOPPED,
            game_process_running=False,
            deferred_session_revocation_reason=None,
            last_error=None,
        )

    def shutdown(self) -> None:
        """Stop only the child processes created by this launcher."""
        self._stop_proxy()
        self._stop_game()

    def _revoke_session(self, reason: str, *, allow_defer: bool = True) -> None:
        """End a session, delaying only an expiry while PSO2 is in progress."""
        state = self.state
        if (
            allow_defer
            and state.game_process_running
            and not entitlement_is_active(state.entitlement)
        ):
            self._update(
                deferred_session_revocation_reason=reason,
                last_error=None,
            )
            return
        self._stop_proxy()
        self._update(
            session_id=None,
            entitlement=None,
            deferred_session_revocation_reason=None,
            last_error=reason,
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
            not entitlement_is_active(state.entitlement)
            or state.session_id is None
        ):
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="บัญชีนี้ยังไม่มีวันใช้งาน กรุณาเติมคูปองก่อน",
            )
            return
        if not state.game_process_running:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="ยังไม่พบ pso2.exe จึงยังไม่เริ่มการเชื่อมต่อ",
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

    def _stop_proxy(self) -> None:
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

    def _launch_tweaker(self, executable: str) -> None:
        state = self.state
        if not executable.strip():
            self._update(
                game_status=GameStatus.FAILED,
                last_error="กรุณาเลือกไฟล์ Tweaker.exe ก่อนเริ่มใช้งาน",
            )
            return
        if state.auth_status is not AuthStatus.AUTHENTICATED:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="กรุณาเข้าสู่ระบบก่อนเปิด Tweaker",
            )
            return
        if (
            not entitlement_is_active(state.entitlement)
            or state.session_id is None
        ):
            self._update(
                game_status=GameStatus.FAILED,
                last_error="บัญชีนี้หมดวันใช้งานแล้ว กรุณาเติมคูปองก่อน",
            )
            return
        if self._game_gateway is None:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="เปิด Tweaker ไม่ได้ กรุณาลองใหม่",
            )
            return
        self._update(game_status=GameStatus.STARTING, last_error=None)
        try:
            from pathlib import Path

            self._game_gateway.start(Path(executable))
        except Exception:
            self._update(
                game_status=GameStatus.FAILED,
                last_error="เปิด Tweaker ไม่สำเร็จ กรุณาตรวจสอบไฟล์ที่เลือก",
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
                last_error="ปิด Tweaker ไม่สำเร็จ กรุณาลองใหม่",
            )
        else:
            self._update(game_status=GameStatus.STOPPED)

    def _update(self, **changes: object) -> None:
        with self._lock:
            self._state = replace(self._state, **changes)
            state = self._state
        self._event_bus.publish(StateChanged(state))
