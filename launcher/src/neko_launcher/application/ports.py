from __future__ import annotations

from pathlib import Path
from typing import Protocol

from neko_launcher.domain.events import Event
from neko_launcher.domain.models import (
    AuthenticatedUser,
    CouponRedemption,
    RegistrationResult,
    SessionClaim,
)


class EventPublisher(Protocol):
    def publish(self, event: Event) -> None:
        ...


class ProxyGateway(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...


class GameGateway(Protocol):
    def start(self, executable: Path) -> None:
        ...

    def stop(self) -> None:
        ...


class AuthGateway(Protocol):
    def sign_up(self, username: str, password: str, email: str) -> RegistrationResult:
        ...

    def sign_in(self, username: str, password: str) -> AuthenticatedUser:
        ...

    def change_password(self, password: str) -> None:
        ...

    def lookup_recovery_email(self, username: str) -> str | None:
        ...

    def request_password_reset(self, email: str) -> None:
        ...

    def restore_session(self) -> AuthenticatedUser | None:
        ...

    def sign_out(self) -> None:
        ...


class EntitlementGateway(Protocol):
    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
        ...

    def heartbeat_session(self, session_id: str) -> bool:
        ...

    def release_session(self, session_id: str) -> bool:
        ...

    def redeem_coupon(self, code: str) -> CouponRedemption:
        ...


class SecureStore(Protocol):
    def read(self, key: str) -> str | None:
        ...

    def write(self, key: str, value: str) -> None:
        ...

    def delete(self, key: str) -> None:
        ...


class InstallationIdentity(Protocol):
    @property
    def key_hash(self) -> str:
        ...

    @property
    def display_name(self) -> str:
        ...
