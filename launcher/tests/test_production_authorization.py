import pytest
from pathlib import Path

from neko_launcher.application.production_authorization import (
    CURRENT_PRODUCTION_AUTHORIZATION,
    ProductionAuthorizationBlocker,
    ProductionAuthorizationGate,
    create_production_proxy_gateway,
)
from neko_launcher.infrastructure.core.authorized_proxy_gateway import AuthorizedProxyGateway
from neko_launcher.infrastructure.unavailable_gateway import AuthorizationPendingProxyGateway


def test_lite_release_gate_is_ready_after_accepted_integration_evidence() -> None:
    gate = CURRENT_PRODUCTION_AUTHORIZATION

    assert gate.contract_id == "NEKO-AUTH-LITE"
    assert gate.contract_revision == "lite-v1"
    assert gate.contract_package_sha256 == ""
    assert gate.blockers == ()
    assert gate.is_ready is True


def test_production_authorization_gate_preserves_fail_closed_semantics() -> None:
    synthetic_gate = ProductionAuthorizationGate(
        contract_id="NEKO-AUTH-LITE",
        contract_revision="lite-v1",
        contract_package_sha256="",
        blockers=(ProductionAuthorizationBlocker.LITE_E2E_UNVERIFIED,),
    )
    assert synthetic_gate.is_ready is False


def test_create_production_proxy_gateway_raises_when_gate_is_ready() -> None:
    with pytest.raises(
        RuntimeError,
        match="approved production authorization adapters are composed in main",
    ):
        create_production_proxy_gateway()


def test_app_factory_composes_authorized_proxy_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neko_launcher.bootstrap.app_factory import build_window

    monkeypatch.setenv("NEKO_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("NEKO_SUPABASE_ANON_KEY", "dummy.jwt.token")

    (tmp_path / "image_11.png").write_bytes(b"")
    (tmp_path / "icon_app.ico").write_bytes(b"")

    window = build_window(tmp_path)
    try:
        assert isinstance(window._controller._proxy_gateway, AuthorizedProxyGateway)
        assert not isinstance(
            window._controller._proxy_gateway, AuthorizationPendingProxyGateway
        )
    finally:
        window.root.destroy()

