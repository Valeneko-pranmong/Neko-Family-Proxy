from __future__ import annotations

from dataclasses import dataclass

from .models import AppState, Entitlement


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
class StartProxyRequested(Event):
    pass


@dataclass(frozen=True)
class StopProxyRequested(Event):
    pass


@dataclass(frozen=True)
class LaunchGameRequested(Event):
    executable: str


@dataclass(frozen=True)
class StopGameRequested(Event):
    pass


@dataclass(frozen=True)
class ErrorOccurred(Event):
    message: str
