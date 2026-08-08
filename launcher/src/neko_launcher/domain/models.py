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


class SessionTerminationReason(str, Enum):
    REPLACED = "replaced"
    REVOKED = "revoked"
    INSTALLATION_REVOKED = "installation_revoked"
    LICENSE_UNAVAILABLE = "license_unavailable"
    ACCOUNT_RESTRICTED = "account_restricted"


class ProxyStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class GameStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


@dataclass(frozen=True)
class Entitlement:
    product_code: str
    status: EntitlementStatus
    valid_until: datetime | None = None
    max_devices: int = 1


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str

    @property
    def username(self) -> str:
        """User-facing identifier (kept in the legacy email slot)."""
        return self.email


@dataclass(frozen=True)
class RegistrationResult:
    email: str
    requires_email_confirmation: bool = False
    user: AuthenticatedUser | None = None

    @property
    def username(self) -> str:
        """User-facing identifier (kept in the legacy email slot)."""
        return self.email


@dataclass(frozen=True)
class SessionClaim:
    session_id: str
    entitlement: Entitlement


@dataclass(frozen=True)
class CouponRedemption:
    product_code: str
    days_added: int
    valid_until: datetime


@dataclass(frozen=True)
class AppState:
    auth_status: AuthStatus = AuthStatus.SIGNED_OUT
    user_id: str | None = None
    user_email: str | None = None
    entitlement: Entitlement | None = None
    session_id: str | None = None
    proxy_status: ProxyStatus = ProxyStatus.STOPPED
    game_status: GameStatus = GameStatus.STOPPED
    game_process_running: bool = False
    deferred_session_revocation_reason: str | None = None
    last_error: str | None = None


def entitlement_is_active(entitlement: Entitlement | None) -> bool:
    """Return whether an entitlement is active *and* has not expired."""
    if entitlement is None or entitlement.status is not EntitlementStatus.ACTIVE:
        return False
    if entitlement.valid_until is None:
        return True
    return entitlement.valid_until > datetime.now(entitlement.valid_until.tzinfo)
