from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AuthStatus(str, Enum):
    SIGNED_OUT = "signed_out"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    FAILED = "failed"


class EntitlementStatus(str, Enum):
    UNKNOWN = "unknown"
    NONE = "none"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ProxyStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class Entitlement:
    product_code: str
    status: EntitlementStatus
    valid_until: datetime | None = None
    max_devices: int = 1


@dataclass(frozen=True)
class AppState:
    auth_status: AuthStatus = AuthStatus.SIGNED_OUT
    user_id: str | None = None
    user_email: str | None = None
    entitlement: Entitlement | None = None
    session_id: str | None = None
    proxy_status: ProxyStatus = ProxyStatus.STOPPED
    last_error: str | None = None
