from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import neko_launcher.bootstrap.app_factory as app_factory
from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.models import AuthenticatedUser, CouponRedemption, SessionClaim
from neko_launcher.infrastructure.auth.proxy_api_auth import (
    REFRESH_TOKEN_STORE_KEY,
    ProxyApiAuthGateway,
    ProxyApiEntitlementStub,
    ProxyApiTokenStore,
)
from neko_launcher.infrastructure.auth.proxy_api_gateway import (
    ProxyApiError,
    ProxyApiGateway,
    ProxyApiHttpResponse,
    ProxyApiTransportError,
)
from neko_launcher.infrastructure.auth.web_auth import IdentityTokenSet
from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.infrastructure.event_bus import EventBus

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "proxy_api_contract.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers,
        payload,
        timeout: float,
    ) -> ProxyApiHttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload) if payload is not None else None,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected transport call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, ProxyApiHttpResponse)
        return response


class FakeIdentityAuthenticator:
    def __init__(
        self,
        tokens: IdentityTokenSet | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.tokens = tokens
        self.error = error
        self.called = False

    def authenticate_identity(self) -> IdentityTokenSet:
        self.called = True
        if self.error is not None:
            raise self.error
        assert self.tokens is not None
        return self.tokens


def _response(status: int, document: dict[str, object] | None) -> ProxyApiHttpResponse:
    body = b"" if document is None else json.dumps(document).encode("utf-8")
    return ProxyApiHttpResponse(status=status, headers={}, body=body, document=document)


def _error_response(code: str) -> ProxyApiHttpResponse:
    fixture = FIXTURE["errors"][code]
    return _response(int(fixture["status"]), fixture["body"])


def _identity_tokens() -> IdentityTokenSet:
    return IdentityTokenSet(
        access_token="identity-access-fixture",
        refresh_token="identity-refresh-fixture",
        expires_in=600,
    )


def _store() -> MemoryStore:
    return MemoryStore()


def _auth(
    transport: FakeTransport,
    store: MemoryStore,
) -> ProxyApiAuthGateway:
    client = ProxyApiGateway(
        proxy_api_base_url="https://proxy.test",
        identity_base_url="https://identity.test",
        transport=transport,
    )
    return ProxyApiAuthGateway(client, ProxyApiTokenStore(store))


def test_sign_in_preflights_and_stores_only_refresh_token() -> None:
    store = _store()
    transport = FakeTransport([_response(200, FIXTURE["me_active"])])
    auth = _auth(transport, store)
    authenticator = FakeIdentityAuthenticator(_identity_tokens())

    user = auth.sign_in_with_web(authenticator)

    assert authenticator.called is True
    assert user == AuthenticatedUser(
        user_id="11111111-1111-4111-8111-111111111111",
        email="Neko Tester",
    )
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "identity-refresh-fixture"}
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://proxy.test/v1/me"
    assert call["headers"]["Authorization"] == "Bearer identity-access-fixture"
    assert auth.account_status is not None
    assert auth.account_status.status == "active"


@pytest.mark.parametrize("code", ["invalid_token", "token_expired"])
def test_sign_in_refreshes_once_on_auth_error(code: str) -> None:
    store = _store()
    transport = FakeTransport(
        [
            _error_response(code),
            _response(200, FIXTURE["refresh_success"]),
            _response(200, FIXTURE["me_active"]),
        ]
    )
    auth = _auth(transport, store)

    user = auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert user.user_id == "11111111-1111-4111-8111-111111111111"
    assert [call["url"] for call in transport.calls] == [
        "https://proxy.test/v1/me",
        "https://identity.test/api/launcher/token",
        "https://proxy.test/v1/me",
    ]
    refresh_call = transport.calls[1]
    assert refresh_call["payload"] == {
        "grant_type": "refresh_token",
        "client_id": "neko-launcher",
        "refresh_token": "identity-refresh-fixture",
    }
    assert transport.calls[2]["headers"]["Authorization"] == (
        "Bearer access-token-fixture-2"
    )
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "refresh-token-fixture-2"}


@pytest.mark.parametrize(
    "code",
    [
        "insufficient_scope",
        "identity_not_linked",
        "account_pending",
        "account_suspended",
    ],
)
def test_failed_preflight_clears_refresh_token(code: str) -> None:
    store = _store()
    transport = FakeTransport([_error_response(code)])
    auth = _auth(transport, store)

    with pytest.raises(ProxyApiError) as captured:
        auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert captured.value.code == code
    assert store.values == {}
    assert auth.account_status is None


@pytest.mark.parametrize(
    ("fixture_name", "expected_code"),
    [
        ("me_pending", "account_pending"),
        ("me_suspended", "account_suspended"),
    ],
)
def test_account_status_from_success_response_is_enforced(
    fixture_name: str,
    expected_code: str,
) -> None:
    store = _store()
    transport = FakeTransport([_response(200, FIXTURE[fixture_name])])
    auth = _auth(transport, store)

    with pytest.raises(ProxyApiError) as captured:
        auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert captured.value.code == expected_code
    assert store.values == {}


def test_login_timeout_clears_refresh_token() -> None:
    store = _store()
    transport = FakeTransport([ProxyApiTransportError("timeout")])
    auth = _auth(transport, store)

    with pytest.raises(ProxyApiError) as captured:
        auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert captured.value.code == "timeout"
    assert store.values == {}


def test_restore_refreshes_and_replaces_rotated_token() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport(
        [
            _response(200, FIXTURE["refresh_success"]),
            _response(200, FIXTURE["me_active"]),
        ]
    )
    auth = _auth(transport, store)

    user = auth.restore_session()

    assert user is not None
    assert user.user_id == "11111111-1111-4111-8111-111111111111"
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "refresh-token-fixture-2"}
    assert transport.calls[0]["payload"]["refresh_token"] == "old-refresh-fixture"
    assert transport.calls[1]["headers"]["Authorization"] == (
        "Bearer access-token-fixture-2"
    )


def test_restore_without_token_does_not_call_network() -> None:
    store = _store()
    transport = FakeTransport([])
    auth = _auth(transport, store)

    assert auth.restore_session() is None
    assert transport.calls == []


def test_restore_invalid_refresh_clears_token() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport([_response(400, FIXTURE["oauth_invalid_grant"])])
    auth = _auth(transport, store)

    assert auth.restore_session() is None
    assert store.values == {}


def test_restore_transient_failure_keeps_refresh_token() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport([_error_response("upstream_unavailable")])
    auth = _auth(transport, store)

    assert auth.restore_session() is None
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "old-refresh-fixture"}


def test_sign_out_clears_memory_and_refresh_token() -> None:
    store = _store()
    transport = FakeTransport([_response(200, FIXTURE["me_active"])])
    auth = _auth(transport, store)
    auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    auth.sign_out()

    assert store.values == {}
    assert auth.account_status is None


@pytest.mark.parametrize(
    "call",
    [
        lambda auth: auth.sign_up("user", "password123"),
        lambda auth: auth.sign_in("user", "password123"),
        lambda auth: auth.change_password("password123"),
        lambda auth: auth.auth_identifier_for_username("user"),
    ],
)
def test_password_and_recovery_surfaces_are_rejected(call) -> None:
    auth = _auth(FakeTransport([]), _store())

    with pytest.raises(LauncherServiceError, match="Discord"):
        call(auth)


def test_authenticator_without_identity_exchange_is_rejected() -> None:
    auth = _auth(FakeTransport([]), _store())

    with pytest.raises(LauncherServiceError, match="ไม่รองรับ"):
        auth.sign_in_with_web(object())


def test_logs_do_not_contain_tokens(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    store = _store()
    transport = FakeTransport([_response(200, FIXTURE["me_active"])])
    auth = _auth(transport, store)

    auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert "identity-access-fixture" not in caplog.text
    assert "identity-refresh-fixture" not in caplog.text
    assert "access-token-fixture-2" not in caplog.text


class BombEntitlement:
    def __init__(self) -> None:
        self.claim_calls = 0

    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
        self.claim_calls += 1
        raise AssertionError("proxy API mode must not claim a legacy session")

    def heartbeat_session(self, session_id: str) -> bool:
        raise AssertionError("proxy API mode must not heartbeat a legacy session")

    def session_termination_reason(self, session_id: str):
        raise AssertionError("proxy API mode must not read a legacy session")

    def release_session(self, session_id: str) -> bool:
        return False

    def redeem_coupon(self, code: str) -> CouponRedemption:
        raise AssertionError("proxy API mode must not redeem through Supabase")


class FakeWebAuthGateway:
    def sign_in_with_web(self, authenticator) -> AuthenticatedUser:
        return AuthenticatedUser("identity-user-id", "Neko Tester")

    def restore_session(self) -> AuthenticatedUser | None:
        return AuthenticatedUser("identity-user-id", "Neko Tester")

    def sign_up(self, username: str, password: str):
        raise AssertionError("unexpected sign_up")

    def sign_in(self, username: str, password: str):
        raise AssertionError("unexpected sign_in")

    def change_password(self, password: str) -> None:
        raise AssertionError("unexpected change_password")

    def auth_identifier_for_username(self, username: str) -> str:
        raise AssertionError("unexpected auth_identifier_for_username")

    def sign_out(self) -> None:
        return

    def clear_local_session(self) -> None:
        return


def _service_proxy_mode() -> tuple[LauncherService, BombEntitlement]:
    entitlement = BombEntitlement()
    service = LauncherService(
        ApplicationController(EventBus()),
        FakeWebAuthGateway(),
        entitlement,
        SimpleNamespace(key_hash="a" * 64, display_name="Test PC"),
        "neko-family-proxy",
        web_auth_only=True,
        proxy_api_mode=True,
    )
    return service, entitlement


def test_service_proxy_mode_skips_legacy_claim_on_web_login() -> None:
    service, entitlement = _service_proxy_mode()

    service.sign_in_with_web(object())

    assert entitlement.claim_calls == 0
    assert service._controller.state.auth_status.value == "authenticated"


def test_service_proxy_mode_skips_legacy_claim_on_restore() -> None:
    service, entitlement = _service_proxy_mode()

    assert service.restore_session() is True
    assert entitlement.claim_calls == 0
    assert service._controller.state.auth_status.value == "authenticated"


def test_compose_auth_dependencies_proxy_mode_does_not_build_supabase(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NEKO_PROXY_API_URL", "https://proxy.example")
    monkeypatch.delenv("NEKO_AUTH_BRIDGE_URL", raising=False)
    monkeypatch.delenv("NEKO_WEB_AUTH_ONLY", raising=False)
    config = LauncherConfig.from_environment(tmp_path)
    config = replace(
        config,
        supabase_url="",
        supabase_publishable_key="",
    )

    def bomb(*args, **kwargs):
        raise AssertionError("SupabaseGateway must not be constructed")

    monkeypatch.setattr(app_factory, "SupabaseGateway", bomb)

    dependencies = app_factory.compose_auth_dependencies(
        config,
        _store(),
        object(),
    )

    assert dependencies.proxy_api_mode is True
    assert isinstance(dependencies.auth_gateway, ProxyApiAuthGateway)
    assert isinstance(dependencies.entitlement_gateway, ProxyApiEntitlementStub)
    assert dependencies.recovery_gateway is None
    assert dependencies.legacy_gateway is None
