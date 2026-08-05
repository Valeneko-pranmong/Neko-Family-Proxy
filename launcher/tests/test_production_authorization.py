from __future__ import annotations

from neko_launcher.application.production_authorization import (
    CURRENT_PRODUCTION_AUTHORIZATION,
    ProductionAuthorizationBlocker,
    create_production_proxy_gateway,
)
from neko_launcher.infrastructure.unavailable_gateway import (
    AuthorizationPendingProxyGateway,
)


def test_current_release_pins_the_same_s0_contract_as_core() -> None:
    gate = CURRENT_PRODUCTION_AUTHORIZATION

    assert gate.contract_id == "NEKO-AUTH-S0"
    assert gate.contract_revision == "s0-rc1"
    assert gate.contract_package_sha256 == (
        "6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df"
    )


def test_current_release_cannot_enable_partial_production_authorization() -> None:
    gate = CURRENT_PRODUCTION_AUTHORIZATION

    assert not gate.is_ready
    assert set(gate.blockers) == {
        ProductionAuthorizationBlocker.CONTRACT_PACKAGE_UNAVAILABLE,
        ProductionAuthorizationBlocker.OWNER_ACCEPTANCE_INCOMPLETE,
        ProductionAuthorizationBlocker.PUBLIC_KEY_RELEASE_UNAVAILABLE,
        ProductionAuthorizationBlocker.RENEWAL_CONTRACT_INCOMPLETE,
        ProductionAuthorizationBlocker.SIGNED_CORE_BUNDLE_UNAVAILABLE,
        ProductionAuthorizationBlocker.S1_ACCESS_UNAVAILABLE,
        ProductionAuthorizationBlocker.PRODUCTION_ADAPTERS_INCOMPLETE,
        ProductionAuthorizationBlocker.RELEASE_APPROVAL_INCOMPLETE,
    }


def test_current_release_composes_only_the_fail_closed_gateway() -> None:
    gateway = create_production_proxy_gateway()

    assert isinstance(gateway, AuthorizationPendingProxyGateway)
