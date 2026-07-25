from __future__ import annotations

from pathlib import Path
from typing import Protocol

from neko_launcher.domain.events import Event


class EventPublisher(Protocol):
    def publish(self, event: Event) -> None:
        ...


class ProxyGateway(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def is_running(self) -> bool:
        ...


class AuthGateway(Protocol):
    def sign_in(self, email: str, password: str) -> tuple[str, str]:
        """Return user_id and normalized email after successful authentication."""
        ...


class EntitlementGateway(Protocol):
    def claim_session(self, product_code: str, installation_key: str) -> str:
        ...


class SecureStore(Protocol):
    def read(self, key: str) -> str | None:
        ...

    def write(self, key: str, value: str) -> None:
        ...

    def delete(self, key: str) -> None:
        ...
