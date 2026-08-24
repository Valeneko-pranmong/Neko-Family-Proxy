from __future__ import annotations

from dataclasses import replace
from threading import Event as CancellationEvent, RLock

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
        self._proxy_operation_lock = RLock()
        self._active_proxy_cancellation: CancellationEvent | None = None

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
                proxy_reconnect_suppressed=False,
                shutting_down=False,
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
            if not event.running:
                self._cancel_active_proxy_operation()
            self._update(
                game_process_running=event.running,
                proxy_reconnect_suppressed=(
                    state.proxy_reconnect_suppressed if event.running else False
                ),
            )
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
                ProxyStatus.RECONNECTING,
                ProxyStatus.RUNNING,
            }:
                self._stop_proxy()
        elif isinstance(event, StartProxyRequested):
            self.start_proxy()
        elif isinstance(event, StopProxyRequested):
            self.stop_proxy()
        elif isinstance(event, LaunchTweakerRequested):
            self._launch_tweaker(event.executable)
        elif isinstance(event, ErrorOccurred):
            self._update(last_error=event.message)

    def sign_out(self, *, shutdown_core: bool = True) -> None:
        self._update(proxy_reconnect_suppressed=True)
        self._cancel_active_proxy_operation()
        shutdown_error = self._shutdown_proxy_host() if shutdown_core else None
        self._update(
            auth_status=AuthStatus.SIGNED_OUT,
            user_id=None,
            user_email=None,
            entitlement=None,
            session_id=None,
            proxy_status=(
                ProxyStatus.FAILED if shutdown_error else ProxyStatus.STOPPED
            ),
            proxy_start_retry_safe=False,
            proxy_failure_code=None,
            proxy_reconnect_suppressed=True,
            game_status=GameStatus.STOPPED,
            game_process_running=False,
            deferred_session_revocation_reason=None,
            last_error=shutdown_error,
        )

    def begin_account_recovery(self) -> None:
        """Enter recovery without creating normal user/session authorization."""
        self._update(proxy_reconnect_suppressed=True)
        self._cancel_active_proxy_operation()
        shutdown_error = self._shutdown_proxy_host()
        self._update(
            auth_status=AuthStatus.RECOVERY_CODE_ENTRY,
            user_id=None,
            user_email=None,
            entitlement=None,
            session_id=None,
            game_status=GameStatus.STOPPED,
            game_process_running=False,
            deferred_session_revocation_reason=None,
            proxy_status=(
                ProxyStatus.FAILED if shutdown_error else ProxyStatus.STOPPED
            ),
            proxy_start_retry_safe=False,
            proxy_failure_code=None,
            proxy_reconnect_suppressed=True,
            last_error=shutdown_error,
        )

    def recovery_verification_started(self) -> None:
        self._update(auth_status=AuthStatus.RECOVERY_VERIFYING, last_error=None)

    def recovery_code_entry_required(self, message: str | None = None) -> None:
        self._update(
            auth_status=AuthStatus.RECOVERY_CODE_ENTRY,
            user_id=None,
            user_email=None,
            entitlement=None,
            session_id=None,
            last_error=message,
        )

    def recovery_password_change_required(self) -> None:
        self._update(
            auth_status=AuthStatus.RECOVERY_PASSWORD_CHANGE,
            user_id=None,
            user_email=None,
            entitlement=None,
            session_id=None,
            last_error=None,
        )

    def invalidate_session(self, reason: str, *, shutdown_core: bool = True) -> None:
        """Immediately remove local authorization after a rejected heartbeat."""
        self._revoke_session(
            reason,
            allow_defer=False,
            shutdown_core=shutdown_core,
        )

    def shutdown(self) -> None:
        """Stop only the child processes created by this launcher."""
        self._update(shutting_down=True, proxy_reconnect_suppressed=True)
        self._cancel_active_proxy_operation()
        self._shutdown_proxy_host()
        self._stop_game()

    def _revoke_session(
        self,
        reason: str,
        *,
        allow_defer: bool = True,
        shutdown_core: bool = True,
    ) -> None:
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
        if shutdown_core:
            self._cancel_active_proxy_operation()
            self._shutdown_proxy_host()
        self._update(
            session_id=None,
            entitlement=None,
            proxy_reconnect_suppressed=True,
            deferred_session_revocation_reason=None,
            last_error=reason,
        )

    def start_proxy(
        self,
        *,
        cancellation: CancellationEvent | None = None,
        automatic_reconnect: bool = False,
    ) -> bool:
        if not automatic_reconnect:
            self._update(proxy_reconnect_suppressed=False)
        return self._start_proxy(
            cancellation=cancellation,
            automatic_reconnect=automatic_reconnect,
        )

    def stop_proxy(self) -> None:
        self.suppress_proxy_reconnect()
        self._stop_proxy()

    def suppress_proxy_reconnect(self) -> None:
        """Latch explicit user intent before asynchronous cleanup begins."""
        self._update(proxy_reconnect_suppressed=True, proxy_start_retry_safe=False)
        self._cancel_active_proxy_operation()

    def mark_proxy_reconnecting(self) -> None:
        state = self.state
        if (
            state.shutting_down
            or state.proxy_reconnect_suppressed
            or not state.game_process_running
        ):
            return
        self._update(
            proxy_status=ProxyStatus.RECONNECTING,
            proxy_failure_code=None,
            last_error=None,
        )

    def mark_proxy_reconnect_failed(self, message: str) -> None:
        state = self.state
        if (
            state.shutting_down
            or state.proxy_reconnect_suppressed
            or not state.game_process_running
            or state.proxy_status
            not in {ProxyStatus.RECONNECTING, ProxyStatus.FAILED}
        ):
            return
        self._update(
            proxy_status=ProxyStatus.FAILED,
            proxy_start_retry_safe=False,
            last_error=message,
        )

    def mark_proxy_running(self) -> None:
        state = self.state
        if (
            state.shutting_down
            or state.proxy_reconnect_suppressed
            or not state.game_process_running
        ):
            return
        self._update(
            proxy_status=ProxyStatus.RUNNING,
            proxy_start_retry_safe=False,
            proxy_failure_code=None,
            last_error=None,
        )

    def _start_proxy(
        self,
        *,
        cancellation: CancellationEvent | None = None,
        automatic_reconnect: bool = False,
    ) -> bool:
        state = self.state
        if automatic_reconnect and (
            cancellation is None
            or cancellation.is_set()
            or not self._automatic_reconnect_eligible(state)
        ):
            return False
        if not automatic_reconnect and state.shutting_down:
            return False
        if state.auth_status is not AuthStatus.AUTHENTICATED:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="กรุณาเข้าสู่ระบบก่อนเริ่มใช้งาน",
            )
            return False
        if (
            not entitlement_is_active(state.entitlement)
            or state.session_id is None
        ):
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="บัญชีนี้ยังไม่มีวันใช้งาน กรุณาเติมคูปองก่อน",
            )
            return False
        if not state.game_process_running:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="ยังไม่พบ pso2.exe จึงยังไม่เริ่มการเชื่อมต่อ",
            )
            return False
        if self._proxy_gateway is None:
            self._update(
                proxy_status=ProxyStatus.FAILED,
                last_error="เริ่มการเชื่อมต่อไม่ได้ กรุณาลองใหม่",
            )
            return False
        self._update(
            proxy_status=(
                ProxyStatus.RECONNECTING
                if automatic_reconnect
                else ProxyStatus.STARTING
            ),
            proxy_failure_code=None,
            last_error=None,
        )
        if automatic_reconnect and cancellation is not None:
            with self._lock:
                self._active_proxy_cancellation = cancellation
        auth_invalid = False
        try:
            with self._proxy_operation_lock:
                if automatic_reconnect and cancellation is not None:
                    self._proxy_gateway.reconnect(cancellation)
                elif cancellation is None:
                    self._proxy_gateway.start()
                else:
                    self._proxy_gateway.start(cancellation)
        except Exception as exc:
            auth_invalid = getattr(exc, "auth_invalid", False) is True
            current = self.state
            if not automatic_reconnect or self._automatic_reconnect_eligible(current):
                code = getattr(getattr(exc, "code", None), "value", None)
                self._update(
                    proxy_status=ProxyStatus.FAILED,
                    proxy_start_retry_safe=self._is_safe_pre_permit_failure(exc),
                    proxy_failure_code=code if isinstance(code, str) else None,
                    last_error=(
                        "เชื่อมต่อใหม่ไม่สำเร็จ กรุณารอสักครู่"
                        if automatic_reconnect
                        else "เริ่มการเชื่อมต่อไม่สำเร็จ กรุณาลองใหม่"
                    ),
                )
        else:
            current = self.state
            if (
                automatic_reconnect
                and not self._automatic_reconnect_eligible(current)
            ) or (
                not automatic_reconnect
                and (
                    current.shutting_down
                    or current.proxy_reconnect_suppressed
                    or not current.game_process_running
                )
            ):
                try:
                    self._proxy_gateway.stop()
                except Exception:
                    pass
                self._update(
                    proxy_status=ProxyStatus.STOPPED,
                    proxy_start_retry_safe=False,
                    proxy_failure_code=None,
                )
            else:
                self._update(
                    proxy_status=ProxyStatus.RUNNING,
                    proxy_start_retry_safe=False,
                    proxy_failure_code=None,
                    last_error=None,
                )
        finally:
            if automatic_reconnect and cancellation is not None:
                with self._lock:
                    if self._active_proxy_cancellation is cancellation:
                        self._active_proxy_cancellation = None
        return auth_invalid

    def _stop_proxy(self) -> None:
        if self._proxy_gateway is None:
            self._update(proxy_status=ProxyStatus.STOPPED)
            return
        self._update(proxy_status=ProxyStatus.STOPPING)
        with self._proxy_operation_lock:
            try:
                self._proxy_gateway.stop()
            except Exception:
                self._update(
                    proxy_status=ProxyStatus.FAILED,
                    last_error="หยุดการเชื่อมต่อไม่สำเร็จ กรุณาลองใหม่",
                )
            else:
                self._update(
                    proxy_status=ProxyStatus.STOPPED,
                    proxy_start_retry_safe=False,
                    proxy_failure_code=None,
                )

    def _shutdown_proxy_host(self) -> str | None:
        if self._proxy_gateway is None:
            self._update(proxy_status=ProxyStatus.STOPPED)
            return None
        with self._proxy_operation_lock:
            try:
                if not self._proxy_gateway.has_owned_host():
                    self._update(proxy_status=ProxyStatus.STOPPED)
                    return None
                self._update(proxy_status=ProxyStatus.STOPPING)
                self._proxy_gateway.shutdown()
            except Exception as exc:
                code = getattr(getattr(exc, "code", None), "value", None)
                safe_code = code if isinstance(code, str) else "SHUTDOWN_REJECTED"
                message = f"ปิด ProxyCore ไม่สมบูรณ์ ({safe_code})"
                self._update(proxy_status=ProxyStatus.FAILED, last_error=message)
                return message
        self._update(
            proxy_status=ProxyStatus.STOPPED,
            proxy_start_retry_safe=False,
            proxy_failure_code=None,
        )
        return None

    def _is_safe_pre_permit_failure(self, error: Exception) -> bool:
        """Allow automatic retry only for failures before permit issuance."""
        return getattr(error, "retry_safe", False) is True

    @staticmethod
    def _automatic_reconnect_eligible(state: AppState) -> bool:
        return (
            not state.shutting_down
            and not state.proxy_reconnect_suppressed
            and state.game_process_running
            and state.auth_status is AuthStatus.AUTHENTICATED
            and state.session_id is not None
            and entitlement_is_active(state.entitlement)
        )

    def _cancel_active_proxy_operation(self) -> None:
        with self._lock:
            cancellation = self._active_proxy_cancellation
        if cancellation is not None:
            cancellation.set()

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
