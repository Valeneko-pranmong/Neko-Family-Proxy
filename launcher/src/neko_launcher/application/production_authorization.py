from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from neko_launcher.application.ports import ProxyGateway
from neko_launcher.infrastructure.unavailable_gateway import (
    AuthorizationPendingProxyGateway,
)


class ProductionAuthorizationBlocker(str, Enum):
    BACKEND_PERMIT_ISSUER_UNAVAILABLE = "BackendPermitIssuerUnavailable"
    PUBLIC_KEY_RELEASE_UNAVAILABLE = "PublicKeyReleaseUnavailable"
    PRODUCTION_ADAPTERS_INCOMPLETE = "ProductionAdaptersIncomplete"


@dataclass(frozen=True)
class ProductionAuthorizationGate:
    contract_id: str
    contract_revision: str
    contract_package_sha256: str
    blockers: tuple[ProductionAuthorizationBlocker, ...]

    @property
    def is_ready(self) -> bool:
        return not self.blockers


CURRENT_PRODUCTION_AUTHORIZATION = ProductionAuthorizationGate(
    contract_id="NEKO-AUTH-S0",
    contract_revision="minimal-v1",
    contract_package_sha256=(
        "6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df"
    ),
    blockers=(),
)


def create_production_proxy_gateway() -> ProxyGateway:
    """Compose the only safe gateway for the current release evidence."""
    if CURRENT_PRODUCTION_AUTHORIZATION.is_ready:
        raise RuntimeError(
            "approved production authorization adapters are composed in main"
        )
    return AuthorizationPendingProxyGateway()

