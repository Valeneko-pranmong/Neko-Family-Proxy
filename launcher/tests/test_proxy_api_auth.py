from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

import neko_launcher.bootstrap.app_factory as app_factory
from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.events import GameProcessStateChanged
from neko_launcher.domain.models import (
    AuthenticatedUser,
    AuthStatus,
    CouponRedemption,
    Entitlement,
    EntitlementStatus,
    ProxyStatus,
    SessionClaim,
    SessionTerminationReason,
    entitlement_is_active,
)
from neko_launcher.infrastructure.auth.proxy_api_auth import (
    REFRESH_TOKEN_STORE_KEY,
    ProxyApiAuthGateway,
    ProxyApiTokenStore,
)
from neko_launcher.infrastructure.auth.proxy_api_entitlement import (
    ProxyApiEntitlementGateway,
)
from neko_launcher.infrastructure.auth.proxy_api_gateway import (
    ProxyApiError,
    ProxyApiGateway,
    ProxyApiHttpResponse,
    ProxyApiTransportError,
)
from neko_launcher.infrastructure.auth.web_auth import (
    IdentityTokenSet,
    JsonResponse,
    WebAuthClient,
)
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


class RecordingSupportSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def record_event(
        self, category: str, event: str, **fields: object
    ) -> None:
        self.events.append((category, event, fields))


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
    *,
    event_sink: RecordingSupportSink | None = None,
) -> ProxyApiAuthGateway:
    client = ProxyApiGateway(
        proxy_api_base_url="https://proxy.test",
        identity_base_url="https://identity.test",
        transport=transport,
    )
    return ProxyApiAuthGateway(
        client,
        ProxyApiTokenStore(store),
        event_sink=event_sink,
    )


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


def test_sign_in_uses_safe_display_name_fallback() -> None:
    store = _store()
    transport = FakeTransport([_response(200, FIXTURE["me_null_display"])])
    auth = _auth(transport, store)

    user = auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert user.email == "Neko Family"


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
        "client_id": "neko-launcher-v2",
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


def test_sign_in_accepts_a_pending_account_and_keeps_the_refresh_token() -> None:
    store = _store()
    transport = FakeTransport([_response(200, FIXTURE["me_pending"])])
    auth = _auth(transport, store)

    user = auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert user.user_id == "11111111-1111-4111-8111-111111111111"
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "identity-refresh-fixture"}
    assert auth.account_status is not None
    assert auth.account_status.status == "pending"


def test_suspended_account_status_from_success_response_is_enforced() -> None:
    store = _store()
    transport = FakeTransport([_response(200, FIXTURE["me_suspended"])])
    auth = _auth(transport, store)

    with pytest.raises(ProxyApiError) as captured:
        auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert captured.value.code == "account_suspended"
    assert store.values == {}


def test_login_timeout_clears_refresh_token() -> None:
    store = _store()
    transport = FakeTransport([ProxyApiTransportError("timeout")])
    auth = _auth(transport, store)

    with pytest.raises(ProxyApiError) as captured:
        auth.sign_in_with_web(FakeIdentityAuthenticator(_identity_tokens()))

    assert captured.value.code == "timeout"
    assert store.values == {}


def test_restore_emits_safe_support_events_without_tokens() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport(
        [
            _response(200, FIXTURE["refresh_success"]),
            _response(200, FIXTURE["me_active"]),
        ]
    )
    sink = RecordingSupportSink()
    auth = _auth(transport, store, event_sink=sink)

    assert auth.restore_session() is not None

    assert ("AUTH", "RESTORE_SUCCEEDED", {}) in sink.events
    serialized = repr(sink.events)
    assert "old-refresh-fixture" not in serialized
    assert "refresh-token-fixture-2" not in serialized
    assert "access-token-fixture-2" not in serialized


def test_restore_without_token_logs_only_a_safe_reason() -> None:
    sink = RecordingSupportSink()
    auth = _auth(FakeTransport([]), _store(), event_sink=sink)

    assert auth.restore_session() is None

    assert sink.events == [
        ("AUTH", "RESTORE_SKIPPED", {"reason": "no_saved_session"})
    ]


def test_restore_failure_logs_sanitized_error_category_and_status() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    sink = RecordingSupportSink()
    auth = _auth(
        FakeTransport([_response(400, FIXTURE["oauth_invalid_grant"])]),
        store,
        event_sink=sink,
    )

    assert auth.restore_session() is None

    _, event, fields = next(
        item for item in sink.events if item[1] == "RESTORE_FAILED"
    )
    assert event == "RESTORE_FAILED"
    assert fields["stage"] == "refresh_or_profile"
    assert fields["error_code"] == "invalid_grant"
    assert fields["http_status"] == 400
    serialized = repr(sink.events)
    assert "old-refresh-fixture" not in serialized
    assert "access-token-fixture" not in serialized


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


def test_restore_refresh_failure_clears_ambiguous_token() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport([_error_response("upstream_unavailable")])
    auth = _auth(transport, store)

    assert auth.restore_session() is None
    assert store.values == {}


def test_restore_preflight_transient_after_refresh_keeps_new_token() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport(
        [
            _response(200, FIXTURE["refresh_success"]),
            _error_response("upstream_unavailable"),
        ]
    )
    auth = _auth(transport, store)

    assert auth.restore_session() is None
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "refresh-token-fixture-2"}


def test_refresh_access_token_failure_clears_stored_token() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport([_error_response("upstream_unavailable")])
    auth = _auth(transport, store)

    with pytest.raises(ProxyApiError) as captured:
        auth.refresh_access_token()

    assert captured.value.code == "upstream_unavailable"
    assert store.values == {}


def test_refresh_access_token_rotates_and_returns_memory_token() -> None:
    store = _store()
    store.values[REFRESH_TOKEN_STORE_KEY] = "old-refresh-fixture"
    transport = FakeTransport([_response(200, FIXTURE["refresh_success"])])
    auth = _auth(transport, store)

    assert auth.refresh_access_token() == "access-token-fixture-2"
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "refresh-token-fixture-2"}


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


class FakeClaimEntitlement:
    def __init__(self) -> None:
        self.claim_calls = 0
        self.released: list[str] = []
        self.heartbeat_interval_seconds = 45

    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
        self.claim_calls += 1
        return SessionClaim(
            session_id="77777777-7777-4777-8777-777777777777",
            entitlement=Entitlement(
                product_code=product_code,
                status=EntitlementStatus.ACTIVE,
                valid_until=None,
            ),
            installation_id="22222222-2222-4222-8222-222222222222",
            runtime_config_version=42,
            heartbeat_interval_seconds=45,
        )

    def heartbeat_session(self, session_id: str) -> bool:
        return True

    def session_termination_reason(self, session_id: str):
        return SessionTerminationReason.REVOKED

    def release_session(self, session_id: str) -> bool:
        self.released.append(session_id)
        return True

    def redeem_coupon(self, code: str) -> CouponRedemption:
        raise LauncherServiceError("coupon is a later slice")


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


def _service() -> tuple[LauncherService, FakeClaimEntitlement]:
    entitlement = FakeClaimEntitlement()
    service = LauncherService(
        ApplicationController(EventBus()),
        FakeWebAuthGateway(),
        entitlement,
        SimpleNamespace(key_hash="a" * 64, display_name="Test PC"),
        "neko-family-proxy",
        web_auth_only=True,
    )
    return service, entitlement


def test_service_claims_after_web_login_with_injected_gateway() -> None:
    service, entitlement = _service()

    service.sign_in_with_web(object())

    assert entitlement.claim_calls == 1
    assert service._controller.state.auth_status.value == "authenticated"
    assert service._controller.state.session_id == (
        "77777777-7777-4777-8777-777777777777"
    )
    assert service.heartbeat_interval_seconds == 45


def test_service_claims_on_restore_with_injected_gateway() -> None:
    service, entitlement = _service()

    assert service.restore_session() is True
    assert entitlement.claim_calls == 1
    assert service._controller.state.auth_status.value == "authenticated"


def test_v2_web_login_pending_account_redeems_coupon_without_another_login() -> None:
    class LoginTransport(FakeTransport):
        def post_json(self, url, payload, headers, timeout) -> JsonResponse:
            response = self.request(
                "POST", url, headers=headers, payload=payload, timeout=timeout
            )
            return JsonResponse(
                status=response.status,
                headers=response.headers,
                body=response.body,
                document=response.document,
            )

    valid_until = datetime.now(timezone.utc) + timedelta(days=30)
    transport = LoginTransport(
        [
            _response(200, FIXTURE["identity_tokens"]),
            _response(200, FIXTURE["me_pending"]),
            _error_response("account_pending"),
            _response(200, {**FIXTURE["coupon_success"], "valid_until": valid_until.isoformat()}),
            _response(
                200,
                {**FIXTURE["claim_success"], "license_valid_until": valid_until.isoformat()},
            ),
        ]
    )
    store = _store()
    auth = _auth(transport, store)
    entitlement = ProxyApiEntitlementGateway(auth._client, auth)
    proxy_starts: list[bool] = []
    controller = ApplicationController(
        EventBus(), proxy_gateway=SimpleNamespace(start=lambda: proxy_starts.append(True))
    )
    service = LauncherService(
        controller,
        auth,
        entitlement,
        SimpleNamespace(key_hash="a" * 64, display_name="Test PC"),
        "neko-family-proxy",
        web_auth_only=True,
    )
    authorize_urls: list[str] = []

    def browser_opener(url: str) -> bool:
        authorize_urls.append(url)
        query = parse_qs(urlparse(url).query)
        redirect = urlparse(query["redirect_uri"][0])
        assert redirect.scheme == "http"
        assert redirect.hostname == "127.0.0.1"
        assert redirect.port is not None and redirect.port > 0
        assert redirect.path == "/auth/callback"
        assert query["state"][0]
        connection = HTTPConnection("127.0.0.1", redirect.port, timeout=2)
        try:
            # Exercise the real state check before delivering the valid callback.
            for state, code, status in (
                ("wrong-state", "rejected-code", 400),
                (query["state"][0], "authorization-code-fixture", 200),
            ):
                params = urlencode({"state": state, "code": code})
                connection.request("GET", f"{redirect.path}?{params}")
                response = connection.getresponse()
                response.read()
                assert response.status == status
        finally:
            connection.close()
        return True

    web_auth = WebAuthClient(
        identity_base_url="https://identity.test",
        bridge_exchange_url="",
        loopback_port=0,
        callback_timeout=2,
        transport=transport,
        browser_opener=browser_opener,
    )
    try:
        service.sign_in_with_web(web_auth)
    finally:
        web_auth._await_previous_teardown()

    assert len(authorize_urls) == 1
    authorize = urlparse(authorize_urls[0])
    assert (authorize.scheme, authorize.netloc, authorize.path) == (
        "https", "identity.test", "/launcher/authorize"
    )
    query = parse_qs(authorize.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["neko-launcher-v2"]
    assert query["code_challenge_method"] == ["S256"]
    exchange = transport.calls[0]["payload"]
    verifier = exchange["code_verifier"]
    assert 43 <= len(verifier) <= 128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    assert query["code_challenge"] == [challenge.rstrip(b"=").decode("ascii")]
    assert exchange == {
        "grant_type": "authorization_code",
        "client_id": "neko-launcher-v2",
        "code": "authorization-code-fixture",
        "code_verifier": verifier,
        "redirect_uri": query["redirect_uri"][0],
    }
    pending = controller.state
    assert pending.auth_status is AuthStatus.AUTHENTICATED
    assert pending.user_id == FIXTURE["me_pending"]["identity_user_id"]
    assert pending.user_email == "Neko Tester"
    assert pending.session_id is None
    assert pending.entitlement is None
    assert auth.account_status is not None and auth.account_status.status == "pending"
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "identity-refresh-fixture"}
    assert len(transport.calls) == 3

    controller.dispatch(GameProcessStateChanged(True))
    service.start_proxy()
    assert controller.state.proxy_status is ProxyStatus.FAILED
    assert controller.state.last_error == "บัญชีนี้ยังไม่มีวันใช้งาน กรุณาเติมคูปองก่อน"
    assert proxy_starts == []
    assert len(transport.calls) == 3

    redemption = service.redeem_coupon("VALID-COUPON-FIXTURE")

    assert redemption == CouponRedemption("neko-family-proxy", 30, valid_until)
    active = controller.state
    assert active.auth_status is AuthStatus.AUTHENTICATED
    assert active.user_id == pending.user_id
    assert active.session_id == FIXTURE["claim_success"]["session_id"]
    assert active.entitlement == Entitlement(
        "neko-family-proxy", EntitlementStatus.ACTIVE, valid_until
    )
    assert entitlement_is_active(active.entitlement)
    assert active.last_error is None
    assert store.values == {REFRESH_TOKEN_STORE_KEY: "identity-refresh-fixture"}
    assert len(authorize_urls) == 1
    assert [(call["method"], call["url"]) for call in transport.calls] == [
        ("POST", "https://identity.test/api/launcher/token"),
        ("GET", "https://proxy.test/v1/me"),
        ("POST", "https://proxy.test/v1/session/claim"),
        ("POST", "https://proxy.test/v1/coupons/redeem"),
        ("POST", "https://proxy.test/v1/session/claim"),
    ]
    assert transport.calls[3]["payload"] == {"code": "VALID-COUPON-FIXTURE"}
    assert transport.calls[2]["payload"] == transport.calls[4]["payload"] == {
        "installation_key_hash": "a" * 64,
        "display_name": "Test PC",
    }
    assert all(
        call["headers"]["Authorization"] == "Bearer identity-access-fixture"
        for call in transport.calls[1:]
    )
    assert transport.responses == []


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

    dependencies = app_factory.compose_auth_dependencies(
        config,
        _store(),
        object(),
    )

    assert isinstance(dependencies.auth_gateway, ProxyApiAuthGateway)
    assert isinstance(dependencies.entitlement_gateway, ProxyApiEntitlementGateway)
    assert dependencies.proxy_auth_gateway is dependencies.auth_gateway
    assert dependencies.proxy_entitlement_gateway is dependencies.entitlement_gateway
    assert dependencies.proxy_client is not None
    assert dependencies.recovery_gateway is None
    assert dependencies.legacy_gateway is None


def test_app_factory_imports_supabase_gateway_only_inside_legacy_branch() -> None:
    source = Path(app_factory.__file__).read_text(encoding="utf-8")
    top_level_imports = [
        line
        for line in source.splitlines()
        if line.startswith(
            "from neko_launcher.infrastructure.auth.supabase_gateway import"
        )
    ]
    assert top_level_imports == []
    assert "    from neko_launcher.infrastructure.auth.supabase_gateway import" in (
        source
    )


def test_app_factory_import_does_not_load_supabase_gateway() -> None:
    launcher_root = Path(__file__).parents[1]
    code = (
        "import sys; import neko_launcher.bootstrap.app_factory; "
        "assert 'neko_launcher.infrastructure.auth.supabase_gateway' "
        "not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=launcher_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_proxy_api_modules_have_no_supabase_or_bridge_dependency() -> None:
    auth_dir = Path(__file__).parents[1] / (
        "src/neko_launcher/infrastructure/auth"
    )
    for name in (
        "proxy_api_gateway.py",
        "proxy_api_auth.py",
        "proxy_api_entitlement.py",
        "proxy_api_permit.py",
        "proxy_api_session.py",
    ):
        source = (auth_dir / name).read_text(encoding="utf-8").lower()
        for forbidden in (
            "import supabase",
            "from supabase",
            "supabase_gateway",
            "supabaseauthstorage",
            "launcher_bridge",
            "web_sessions",
        ):
            assert forbidden not in source
