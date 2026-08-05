from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from neko_launcher.application.ports import ProxyGateway
from neko_launcher.infrastructure.unavailable_gateway import (
    AuthorizationPendingProxyGateway,
)


class ProductionAuthorizationBlocker(str, Enum):
    CONTRACT_PACKAGE_UNAVAILABLE = "ContractPackageUnavailable"
    OWNER_ACCEPTANCE_INCOMPLETE = "OwnerAcceptanceIncomplete"
    PUBLIC_KEY_RELEASE_UNAVAILABLE = "PublicKeyReleaseUnavailable"
    RENEWAL_CONTRACT_INCOMPLETE = "RenewalContractIncomplete"
    SIGNED_CORE_BUNDLE_UNAVAILABLE = "SignedCoreBundleUnavailable"
    S1_ACCESS_UNAVAILABLE = "S1AccessUnavailable"
    PRODUCTION_ADAPTERS_INCOMPLETE = "ProductionAdaptersIncomplete"
    RELEASE_APPROVAL_INCOMPLETE = "ReleaseApprovalIncomplete"


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
    contract_revision="s0-rc1",
    contract_package_sha256=(
        "6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df"
    ),
    blockers=(
        ProductionAuthorizationBlocker.CONTRACT_PACKAGE_UNAVAILABLE,
        ProductionAuthorizationBlocker.OWNER_ACCEPTANCE_INCOMPLETE,
        ProductionAuthorizationBlocker.PUBLIC_KEY_RELEASE_UNAVAILABLE,
        ProductionAuthorizationBlocker.RENEWAL_CONTRACT_INCOMPLETE,
        ProductionAuthorizationBlocker.SIGNED_CORE_BUNDLE_UNAVAILABLE,
        ProductionAuthorizationBlocker.S1_ACCESS_UNAVAILABLE,
        ProductionAuthorizationBlocker.PRODUCTION_ADAPTERS_INCOMPLETE,
        ProductionAuthorizationBlocker.RELEASE_APPROVAL_INCOMPLETE,
    ),
)


def create_production_proxy_gateway() -> ProxyGateway:
    """Compose the only safe gateway for the current release evidence."""
    if CURRENT_PRODUCTION_AUTHORIZATION.is_ready:
        raise RuntimeError("approved production authorization adapters are missing")
    return AuthorizationPendingProxyGateway()
