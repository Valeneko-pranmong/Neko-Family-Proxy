from __future__ import annotations

from dataclasses import dataclass

from .models import AppState, Entitlement
from .telemetry import TelemetryState


class Event:
    """Marker base class for events crossing the application boundary."""


@dataclass(frozen=True)
class StateChanged(Event):
    state: AppState


@dataclass(frozen=True)
class AuthStarted(Event):
    email: str


@dataclass(frozen=True)
class AuthSucceeded(Event):
    user_id: str
    email: str


@dataclass(frozen=True)
class AuthFailed(Event):
    message: str


@dataclass(frozen=True)
class EntitlementLoaded(Event):
    entitlement: Entitlement | None


@dataclass(frozen=True)
class SessionClaimed(Event):
    session_id: str


@dataclass(frozen=True)
class SessionRevoked(Event):
    reason: str


@dataclass(frozen=True)
class GameProcessStateChanged(Event):
    """Reports whether the actual PSO2 client process is running."""

    running: bool


@dataclass(frozen=True)
class StartProxyRequested(Event):
    pass


@dataclass(frozen=True)
class StopProxyRequested(Event):
    pass


@dataclass(frozen=True)
class LaunchTweakerRequested(Event):
    """Launch Tweaker after auth/entitlement checks, without starting ProxyCore."""

    executable: str


@dataclass(frozen=True)
class ErrorOccurred(Event):
    message: str


@dataclass(frozen=True)
class TelemetryUpdated(Event):
    state: TelemetryState
