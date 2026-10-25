from __future__ import annotations

import base64
from collections.abc import Mapping
import hashlib
from http.client import HTTPConnection
import threading
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

import pytest

from neko_launcher.infrastructure.auth.web_auth import (
    BridgeSession,
    IdentityTokenSet,
    JsonResponse,
    LoopbackCallbackServer,
    UrllibJsonTransport,
    WebAuthClient,
    WebAuthError,
    build_authorize_url,
    generate_pkce,
)


class FakeTransport:
    def __init__(self, responses: list[JsonResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float,
    ) -> JsonResponse:
        self.calls.append(
            {
                "url": url,
                "payload": dict(payload),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected transport call")
        return self.responses.pop(0)


def _response(status: int, document: dict[str, object] | None = None) -> JsonResponse:
    return JsonResponse(status=status, headers={}, body=b"", document=document)


def _browser_sends_callback(
    *,
    code: str | None = "code-123",
    error: str | None = None,
    wrong_state: bool = False,
) -> tuple[object, threading.Event]:
    opened = threading.Event()

    def opener(url: str) -> bool:
        query = parse_qs(urlparse(url).query)
        redirect_uri = query["redirect_uri"][0]
        state = "wrong-state" if wrong_state else query["state"][0]
        params: dict[str, str] = {"state": state}
        if error is not None:
            params["error"] = error
        elif code is not None:
            params["code"] = code
        target = f"{redirect_uri}?{urlencode(params)}"

        def send() -> None:
            try:
                with urlopen(target, timeout=2) as response:
                    response.read()
            except Exception:
                pass

        threading.Thread(target=send, daemon=True).start()
        opened.set()
        return True

    return opener, opened


def _client(
    transport: FakeTransport,
    *,
    bridge_exchange_url: str = "https://bridge.test/auth/launcher/exchange",
    browser_opener=None,
    callback_timeout: float = 2.0,
) -> WebAuthClient:
    return WebAuthClient(
        identity_base_url="https://identity.test",
        bridge_exchange_url=bridge_exchange_url,
        loopback_port=0,
        callback_timeout=callback_timeout,
        transport=transport,
        browser_opener=browser_opener,
    )


def _token_response() -> JsonResponse:
    return _response(
        200,
        {
            "token_type": "Bearer",
            "access_token": "identity-token",
            "expires_in": 300,
            "user": {"id": "identity-id", "username": "discord-user"},
        },
    )


def _bridge_response() -> JsonResponse:
    return _response(
        200,
        {
            "token_type": "Bearer",
            "access_token": "supabase-access",
            "refresh_token": "supabase-refresh",
            "expires_in": 3600,
        },
    )


def _identity_token_response() -> JsonResponse:
    return _response(
        200,
        {
            "token_type": "Bearer",
            "access_token": "identity-access",
            "refresh_token": "identity-refresh",
            "expires_in": 600,
            "scope": "proxy:launch proxy:read",
        },
    )


def test_pkce_uses_s256_and_bounded_random_values() -> None:
    first = generate_pkce()
    second = generate_pkce()

    assert 43 <= len(first.verifier) <= 128
    assert first.state != second.state
    expected = (
        base64.urlsafe_b64encode(
            hashlib.sha256(first.verifier.encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    assert first.challenge == expected
    assert "=" not in first.challenge
    assert first.challenge != first.verifier


def test_authorize_url_uses_exact_loopback_contract() -> None:
    pkce = generate_pkce()
    url = build_authorize_url(
        "https://identity.test",
        "http://127.0.0.1:53682/auth/callback",
        pkce,
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "identity.test"
    assert parsed.path == "/launcher/authorize"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["neko-launcher"]
    assert query["redirect_uri"] == ["http://127.0.0.1:53682/auth/callback"]
    assert query["state"] == [pkce.state]
    assert query["code_challenge"] == [pkce.challenge]
    assert query["code_challenge_method"] == ["S256"]


def test_authorize_url_rejects_non_https_or_path_base() -> None:
    pkce = generate_pkce()
    for base in ("http://identity.test", "https://identity.test/extra"):
        with pytest.raises(WebAuthError, match="ที่อยู่ระบบล็อกอินไม่ถูกต้อง"):
            build_authorize_url(base, "http://127.0.0.1:53682/auth/callback", pkce)


def test_loopback_accepts_one_matching_callback() -> None:
    state = generate_pkce().state
    server = LoopbackCallbackServer(expected_state=state, port=0)
    server.start()
    try:
        with urlopen(
            f"{server.redirect_uri}?{urlencode({'code': 'opaque-code', 'state': state})}",
            timeout=2,
        ) as response:
            assert response.status == 200
        result = server.wait(1)
        assert result.code == "opaque-code"
        assert result.error is None
    finally:
        server.close()


def test_loopback_rejects_wrong_state_then_accepts_correct_one() -> None:
    state = generate_pkce().state
    server = LoopbackCallbackServer(expected_state=state, port=0)
    server.start()
    try:
        with pytest.raises(HTTPError) as wrong:
            urlopen(
                f"{server.redirect_uri}?{urlencode({'code': 'bad', 'state': 'wrong'})}",
                timeout=2,
            )
        assert wrong.value.code == 400

        with urlopen(
            f"{server.redirect_uri}?{urlencode({'code': 'good', 'state': state})}",
            timeout=2,
        ) as response:
            assert response.status == 200
        assert server.wait(1).code == "good"
    finally:
        server.close()


def test_loopback_rejects_duplicate_query_parameters() -> None:
    state = generate_pkce().state
    server = LoopbackCallbackServer(expected_state=state, port=0)
    server.start()
    try:
        with pytest.raises(HTTPError) as duplicate:
            urlopen(
                f"{server.redirect_uri}?code=one&code=two&state={state}",
                timeout=2,
            )
        assert duplicate.value.code == 400
    finally:
        server.close()


def test_loopback_rejects_wrong_host_header() -> None:
    state = generate_pkce().state
    server = LoopbackCallbackServer(expected_state=state, port=0)
    server.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.port, timeout=2)
        try:
            connection.putrequest(
                "GET",
                f"/auth/callback?code=opaque&state={state}",
                skip_host=True,
            )
            connection.putheader("Host", "evil.test")
            connection.endheaders()
            response = connection.getresponse()
            assert response.status == 400
        finally:
            connection.close()
    finally:
        server.close()


def test_loopback_returns_error_callback() -> None:
    state = generate_pkce().state
    server = LoopbackCallbackServer(expected_state=state, port=0)
    server.start()
    try:
        with urlopen(
            f"{server.redirect_uri}?{urlencode({'error': 'access_denied', 'state': state})}",
            timeout=2,
        ) as response:
            assert response.status == 200
        result = server.wait(1)
        assert result.error == "access_denied"
        assert result.code is None
    finally:
        server.close()


def test_loopback_times_out_and_can_be_cancelled() -> None:
    state = generate_pkce().state
    timeout_server = LoopbackCallbackServer(expected_state=state, port=0)
    timeout_server.start()
    try:
        with pytest.raises(WebAuthError) as timeout:
            timeout_server.wait(0.02)
        assert timeout.value.code == "callback_timeout"
    finally:
        timeout_server.close()

    cancel_server = LoopbackCallbackServer(expected_state=state, port=0)
    cancel_server.start()
    try:
        cancel_server.cancel()
        with pytest.raises(WebAuthError) as cancelled:
            cancel_server.wait(0.2)
        assert cancelled.value.code == "cancelled"
    finally:
        cancel_server.close()


def test_client_exchanges_code_and_bridge_session() -> None:
    transport = FakeTransport([_token_response(), _bridge_response()])
    opener, opened = _browser_sends_callback()
    client = _client(transport, browser_opener=opener)

    session = client.authenticate()

    assert opened.is_set()
    assert session == BridgeSession(
        access_token="supabase-access",
        refresh_token="supabase-refresh",
        expires_in=3600,
    )
    assert len(transport.calls) == 2
    token_call, bridge_call = transport.calls
    assert token_call["url"] == "https://identity.test/api/launcher/token"
    assert token_call["payload"]["grant_type"] == "authorization_code"
    assert token_call["payload"]["client_id"] == "neko-launcher"
    assert token_call["payload"]["code"] == "code-123"
    assert token_call["payload"]["redirect_uri"].startswith("http://127.0.0.1:")
    assert token_call["payload"]["code_verifier"]
    assert bridge_call["url"] == "https://bridge.test/auth/launcher/exchange"
    assert bridge_call["headers"]["Authorization"] == "Bearer identity-token"
    assert bridge_call["payload"] == {}


def test_client_identity_exchange_requires_no_bridge() -> None:
    transport = FakeTransport([_identity_token_response()])
    opener, opened = _browser_sends_callback()
    client = _client(transport, bridge_exchange_url="", browser_opener=opener)

    tokens = client.authenticate_identity()

    assert opened.is_set()
    assert tokens == IdentityTokenSet(
        access_token="identity-access",
        refresh_token="identity-refresh",
        expires_in=600,
        scope="proxy:launch proxy:read",
    )
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == "https://identity.test/api/launcher/token"
    assert transport.calls[0]["payload"]["grant_type"] == "authorization_code"


def test_identity_exchange_requires_refresh_token() -> None:
    transport = FakeTransport([_token_response()])
    opener, _ = _browser_sends_callback()
    client = _client(transport, bridge_exchange_url="", browser_opener=opener)

    with pytest.raises(WebAuthError) as error:
        client.authenticate_identity()

    assert error.value.code == "invalid_token_response"
    assert len(transport.calls) == 1


def test_identity_token_set_repr_redacts_tokens() -> None:
    tokens = IdentityTokenSet(
        access_token="identity-access-secret",
        refresh_token="identity-refresh-secret",
        expires_in=600,
    )

    assert "identity-access-secret" not in repr(tokens)
    assert "identity-refresh-secret" not in repr(tokens)


def test_client_maps_access_denied_without_exchange() -> None:
    transport = FakeTransport([])
    opener, _ = _browser_sends_callback(error="access_denied")
    client = _client(transport, browser_opener=opener)

    with pytest.raises(WebAuthError) as error:
        client.authenticate()

    assert error.value.code == "access_denied"
    assert transport.calls == []


def test_client_maps_invalid_grant_and_does_not_call_bridge() -> None:
    transport = FakeTransport(
        [_response(400, {"error": "invalid_grant", "error_description": "bad"})]
    )
    opener, _ = _browser_sends_callback()
    client = _client(transport, browser_opener=opener)

    with pytest.raises(WebAuthError) as error:
        client.authenticate()

    assert error.value.code == "invalid_grant"
    assert len(transport.calls) == 1


def test_client_maps_bridge_errors() -> None:
    cases = [
        (401, {"error": "invalid_token"}, "invalid_token"),
        (409, {"error": "token_replayed"}, "token_replayed"),
        (409, {"error": "identity_not_linked"}, "identity_not_linked"),
        (429, {"error": "rate_limited"}, "rate_limited"),
        (503, {"error": "upstream_unavailable"}, "bridge_unavailable"),
    ]
    for status, document, expected_code in cases:
        transport = FakeTransport([_token_response(), _response(status, document)])
        opener, _ = _browser_sends_callback()
        client = _client(transport, browser_opener=opener)

        with pytest.raises(WebAuthError) as error:
            client.authenticate()

        assert error.value.code == expected_code


def test_client_rejects_insecure_bridge_url() -> None:
    with pytest.raises(WebAuthError) as error:
        WebAuthClient(
            identity_base_url="https://identity.test",
            bridge_exchange_url="http://bridge.test/auth/launcher/exchange",
        )
    assert error.value.code == "bridge_endpoint_invalid"


def test_client_requires_bridge_configuration() -> None:
    transport = FakeTransport([])
    opener, opened = _browser_sends_callback()
    client = _client(transport, bridge_exchange_url="", browser_opener=opener)

    with pytest.raises(WebAuthError) as error:
        client.authenticate()

    assert error.value.code == "bridge_not_configured"
    assert not opened.is_set()


def test_client_reports_browser_open_failure() -> None:
    transport = FakeTransport([])
    client = _client(transport, browser_opener=lambda _url: False)

    with pytest.raises(WebAuthError) as error:
        client.authenticate()

    assert error.value.code == "browser_open_failed"


def test_client_cancel_stops_waiting_for_callback() -> None:
    transport = FakeTransport([])
    opened = threading.Event()

    def opener(_url: str) -> bool:
        opened.set()
        return True

    client = _client(transport, browser_opener=opener, callback_timeout=5.0)
    outcome: list[BaseException] = []

    def run() -> None:
        try:
            client.authenticate()
        except BaseException as error:
            outcome.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert opened.wait(2)
        client.cancel()
        thread.join(2)
        assert outcome
        assert isinstance(outcome[0], WebAuthError)
        assert outcome[0].code == "cancelled"
    finally:
        client.cancel()
        thread.join(2)


def test_urllib_transport_rejects_insecure_endpoint() -> None:
    with pytest.raises(WebAuthError) as error:
        UrllibJsonTransport().post_json(
            "http://identity.test/token", {}, {}, 1.0
        )
    assert error.value.code == "insecure_endpoint"
