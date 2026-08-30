from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AuthStatus(str, Enum):
    SIGNED_OUT = "signed_out"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    FAILED = "failed"
    RECOVERY_CODE_ENTRY = "recovery_code_entry"
    RECOVERY_VERIFYING = "recovery_verifying"
    RECOVERY_PASSWORD_CHANGE = "recovery_password_change"


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
    RECONNECTING = "reconnecting"
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
class RecoverySession:
    """Opaque, memory-only credential scoped exclusively to password recovery."""

    session_id: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionClaim:
    session_id: str
    entitlement: Entitlement
    installation_id: str = ""
    license_id: str = ""


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
    proxy_start_retry_safe: bool = False
    proxy_failure_code: str | None = None
    proxy_reconnect_suppressed: bool = False
    shutting_down: bool = False
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


# ---------------------------------------------------------------------------
# Phase 1 — Semantic network presentation-domain models
# (docs/current/dashboard-redesign-plan.md v1.2, sections 4.2 and 1.3)
# ---------------------------------------------------------------------------
#
# These types are pure presentation-domain foundations. They do NOT introduce
# a producer for any network measurement and they do NOT add raw address
# fields (no ip, hostname, port, bangkok, per_hop_latency_ms).


class NetworkHopRole(str, Enum):
    LOCAL_DEVICE = "local_device"
    LOCAL_PROXY_ENGINE = "local_proxy_engine"
    REMOTE_PROXY = "remote_proxy"
    GAME_NETWORK = "game_network"


class HopConnectionState(str, Enum):
    SUCCESS = "success"
    CONNECTING = "connecting"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NetworkHop:
    role: NetworkHopRole
    label: str
    location: str | None = None
    connection_state: HopConnectionState = HopConnectionState.UNAVAILABLE


@dataclass(frozen=True)
class NetworkPath:
    hops: tuple[NetworkHop, ...] = ()
    proxy_rtt_ms: int | None = None

    def __post_init__(self) -> None:
        if self.proxy_rtt_ms is not None and self.proxy_rtt_ms < 0:
            raise ValueError("proxy_rtt_ms must be non-negative or None")
