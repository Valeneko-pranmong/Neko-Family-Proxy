from __future__ import annotations

from neko_launcher.application.production_authorization import (
    CURRENT_PRODUCTION_AUTHORIZATION,
    ProductionAuthorizationBlocker,
    create_production_proxy_gateway,
)
from neko_launcher.infrastructure.unavailable_gateway import AuthorizationPendingProxyGateway


def test_lite_release_is_explicitly_fail_closed_until_core_and_e2e_exist() -> None:
    gate = CURRENT_PRODUCTION_AUTHORIZATION

    assert gate.contract_id == "NEKO-AUTH-LITE"
    assert gate.contract_revision == "lite-v1"
    assert gate.contract_package_sha256 == ""
    assert gate.blockers == (
        ProductionAuthorizationBlocker.BACKEND_PERMIT_ISSUER_UNAVAILABLE,
        ProductionAuthorizationBlocker.CORE_PUBLIC_KEY_UNAVAILABLE,
        ProductionAuthorizationBlocker.CORE_AUTHORIZED_START_UNAVAILABLE,
        ProductionAuthorizationBlocker.SINGLE_ACTIVE_SESSION_ENFORCEMENT_UNAVAILABLE,
        ProductionAuthorizationBlocker.SESSION_CONCURRENCY_PROTECTION_UNAVAILABLE,
        ProductionAuthorizationBlocker.CORE_CHALLENGE_VERIFICATION_UNAVAILABLE,
        ProductionAuthorizationBlocker.LITE_E2E_UNVERIFIED,
    )
    assert not gate.is_ready


def test_lite_release_returns_pending_gateway_while_blockers_remain() -> None:
    assert isinstance(create_production_proxy_gateway(), AuthorizationPendingProxyGateway)
