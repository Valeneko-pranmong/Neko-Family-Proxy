from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from threading import Event, RLock

from neko_launcher.domain.models import AppState, AuthStatus, entitlement_is_active


class ReconnectCompletion(str, Enum):
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    EXHAUSTED = "exhausted"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class ReconnectAttempt:
    generation: int
    attempt: int
    delay_seconds: float


class AutomaticProxyReconnectController:
    """Thread-safe bounded scheduler state for one runtime reconnect lifecycle."""

    _SECURITY_DENIALS = frozenset(
        {
            "AuthorizationRequired",
            "AuthorizationInvalid",
            "AuthorizationExpired",
            "AuthorizationReplay",
            "SessionInactive",
            "EntitlementInactive",
            "HeartbeatStale",
        }
    )

    def __init__(self, *, backoff_seconds: tuple[float, ...]) -> None:
        if not backoff_seconds or any(
            not isinstance(value, (int, float))
            or not isfinite(value)
            or value <= 0
            for value in backoff_seconds
        ):
            raise ValueError("reconnect backoff must contain positive finite delays")
        self._backoff_seconds = tuple(float(value) for value in backoff_seconds)
        self._lock = RLock()
        self._generation = 0
        self._attempts = 0
        self._armed = False
        self._blocked = False
        self._scheduled: ReconnectAttempt | None = None
        self._in_flight: ReconnectAttempt | None = None
        self._cancellation: Event | None = None

    @property
    def attempts(self) -> int:
        with self._lock:
            return self._attempts

    @property
    def in_flight(self) -> bool:
        with self._lock:
            return self._in_flight is not None

    @property
    def owns_recovery(self) -> bool:
        """Return whether runtime recovery owns automatic proxy activation."""
        with self._lock:
            return (
                self._scheduled is not None
                or self._in_flight is not None
                or self._attempts > 0
                or self._blocked
            )

    def observe_running(self) -> None:
        with self._lock:
            if self._scheduled is not None or self._in_flight is not None:
                return
            self._armed = True
            self._blocked = False
            self._attempts = 0
            self._cancellation = None

    def request(
        self,
        state: AppState,
        *,
        shutting_down: bool,
    ) -> ReconnectAttempt | None:
        with self._lock:
            if (
                not self._armed
                or self._blocked
                or self._scheduled is not None
                or self._in_flight is not None
                or self._attempts >= len(self._backoff_seconds)
                or not self._eligible(state, shutting_down=shutting_down)
            ):
                return None
            self._attempts += 1
            self._generation += 1
            attempt = ReconnectAttempt(
                generation=self._generation,
                attempt=self._attempts,
                delay_seconds=self._backoff_seconds[self._attempts - 1],
            )
            self._scheduled = attempt
            return attempt

    def begin(
        self,
        attempt: ReconnectAttempt,
        state: AppState,
        *,
        shutting_down: bool,
    ) -> Event | None:
        with self._lock:
            if self._scheduled != attempt:
                return None
            self._scheduled = None
            if not self._eligible(state, shutting_down=shutting_down):
                return None
            cancellation = Event()
            self._in_flight = attempt
            self._cancellation = cancellation
            return cancellation

    def complete(
        self,
        attempt: ReconnectAttempt,
        *,
        succeeded: bool,
        retry_safe: bool,
        failure_code: str | None = None,
    ) -> ReconnectCompletion:
        with self._lock:
            if self._in_flight != attempt:
                return ReconnectCompletion.BLOCKED
            self._in_flight = None
            self._cancellation = None
            if succeeded:
                self._attempts = 0
                self._blocked = False
                # Require one fresh healthy observation before a later
                # disconnect can open a new reconnect lifecycle.
                self._armed = False
                return ReconnectCompletion.SUCCEEDED
            if failure_code in self._SECURITY_DENIALS:
                self._blocked = True
                self._armed = False
                return ReconnectCompletion.BLOCKED
            if retry_safe and self._attempts < len(self._backoff_seconds):
                return ReconnectCompletion.RETRY
            self._blocked = True
            self._armed = False
            if retry_safe and self._attempts >= len(self._backoff_seconds):
                return ReconnectCompletion.EXHAUSTED
            return ReconnectCompletion.FAILED

    def cancel(self, *, reset_attempts: bool) -> None:
        with self._lock:
            if self._cancellation is not None:
                self._cancellation.set()
            self._generation += 1
            self._scheduled = None
            self._in_flight = None
            self._cancellation = None
            self._armed = False
            self._blocked = False
            if reset_attempts:
                self._attempts = 0

    @staticmethod
    def _eligible(state: AppState, *, shutting_down: bool) -> bool:
        return (
            not shutting_down
            and not getattr(state, "shutting_down", False)
            and not getattr(state, "proxy_reconnect_suppressed", False)
            and state.game_process_running
            and state.auth_status is AuthStatus.AUTHENTICATED
            and state.session_id is not None
            and entitlement_is_active(state.entitlement)
        )
