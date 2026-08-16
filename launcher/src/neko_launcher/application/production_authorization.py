from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from neko_launcher.application.ports import ProxyGateway
from neko_launcher.infrastructure.unavailable_gateway import (
    AuthorizationPendingProxyGateway,
)


class ProductionAuthorizationBlocker(str, Enum):
    BACKEND_PERMIT_ISSUER_UNAVAILABLE = "BACKEND_PERMIT_ISSUER_UNAVAILABLE"
    CORE_PUBLIC_KEY_UNAVAILABLE = "CORE_PUBLIC_KEY_UNAVAILABLE"
    CORE_AUTHORIZED_START_UNAVAILABLE = "CORE_AUTHORIZED_START_UNAVAILABLE"
    SINGLE_ACTIVE_SESSION_ENFORCEMENT_UNAVAILABLE = (
        "SINGLE_ACTIVE_SESSION_ENFORCEMENT_UNAVAILABLE"
    )
    SESSION_CONCURRENCY_PROTECTION_UNAVAILABLE = (
        "SESSION_CONCURRENCY_PROTECTION_UNAVAILABLE"
    )
    CORE_CHALLENGE_VERIFICATION_UNAVAILABLE = "CORE_CHALLENGE_VERIFICATION_UNAVAILABLE"
    LITE_E2E_UNVERIFIED = "LITE_E2E_UNVERIFIED"


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
    contract_id="NEKO-AUTH-LITE",
    contract_revision="lite-v1",
    contract_package_sha256="",
    blockers=(),
)



def create_production_proxy_gateway() -> ProxyGateway:
    """Compose the only safe gateway for the current release evidence."""
    if CURRENT_PRODUCTION_AUTHORIZATION.is_ready:
        raise RuntimeError(
            "approved production authorization adapters are composed in main"
        )
    return AuthorizationPendingProxyGateway()

