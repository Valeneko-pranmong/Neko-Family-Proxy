from __future__ import annotations

import json
from pathlib import Path

import pytest

from neko_launcher.infrastructure.auth.proxy_api_gateway import (
    SHARED_ERROR_MESSAGES,
    ProxyAccountStatus,
    ProxyApiError,
    ProxyApiGateway,
    ProxyApiHttpResponse,
    ProxyApiTokenSet,
    ProxyApiTransportError,
    UrllibProxyApiTransport,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "proxy_api_contract.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


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


def _response(status: int, document: dict[str, object] | None) -> ProxyApiHttpResponse:
    body = b"" if document is None else json.dumps(document).encode("utf-8")
    return ProxyApiHttpResponse(
        status=status,
        headers={},
        body=body,
        document=document,
    )


def _error_response(code: str) -> ProxyApiHttpResponse:
    fixture = FIXTURE["errors"][code]
    return _response(int(fixture["status"]), fixture["body"])


def _gateway(transport: FakeTransport) -> ProxyApiGateway:
    return ProxyApiGateway(
        proxy_api_base_url="https://proxy.test",
        identity_base_url="https://identity.test",
        timeout=4.5,
        transport=transport,
    )


def test_get_me_uses_bearer_boundary_and_contract_fields() -> None:
    transport = FakeTransport([_response(200, FIXTURE["me_active"])])
    gateway = _gateway(transport)

    account = gateway.get_me("access-fixture")

    assert account == ProxyAccountStatus(
        identity_user_id="11111111-1111-4111-8111-111111111111",
        proxy_account_id="proxy-account-fixture",
        status="active",
        display_name="Neko Tester",
    )
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://proxy.test/v1/me"
    assert call["payload"] is None
    assert call["timeout"] == 4.5
    headers = call["headers"]
    assert headers["Authorization"] == "Bearer access-fixture"
    assert headers["Accept"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert headers["User-Agent"].startswith("NekoLauncher/")


def test_refresh_exchange_uses_identity_endpoint_and_returns_rotated_tokens() -> None:
    transport = FakeTransport([_response(200, FIXTURE["refresh_success"])])
    gateway = _gateway(transport)

    tokens = gateway.refresh_access_token("refresh-fixture")

    assert tokens == ProxyApiTokenSet(
        access_token="access-token-fixture-2",
        refresh_token="refresh-token-fixture-2",
        expires_in=600,
        scope="proxy:launch proxy:read",
    )
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://identity.test/api/launcher/token"
    assert call["payload"] == {
        "grant_type": "refresh_token",
        "client_id": "neko-launcher",
        "refresh_token": "refresh-fixture",
    }
    headers = call["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert headers["Pragma"] == "no-cache"
    assert "Authorization" not in headers


@pytest.mark.parametrize("code", sorted(SHARED_ERROR_MESSAGES))
def test_shared_error_codes_map_to_thai_ui_messages(code: str) -> None:
    transport = FakeTransport([_error_response(code)])
    gateway = _gateway(transport)

    with pytest.raises(ProxyApiError) as captured:
        gateway.get_me("access-fixture")

    error = captured.value
    assert error.code == code
    assert error.user_message == SHARED_ERROR_MESSAGES[code]
    assert str(error) == SHARED_ERROR_MESSAGES[code]
    assert error.request_id == f"req-fixture-{code.replace('_', '-')}"
    assert error.status == FIXTURE["errors"][code]["status"]


def test_rate_limit_and_upstream_failures_are_retryable() -> None:
    for code in ("rate_limited", "upstream_unavailable"):
        error = _error_from_code(code)
        assert error.retryable is True


def test_terminal_errors_are_not_retryable() -> None:
    for code in (
        "invalid_token",
        "token_expired",
        "insufficient_scope",
        "identity_not_linked",
        "account_pending",
        "account_suspended",
        "license_expired",
        "session_conflict",
    ):
        error = _error_from_code(code)
        assert error.retryable is False


def _error_from_code(code: str) -> ProxyApiError:
    gateway = _gateway(FakeTransport([_error_response(code)]))
    with pytest.raises(ProxyApiError) as captured:
        gateway.get_me("access-fixture")
    return captured.value


@pytest.mark.parametrize(
    ("fixture_name", "expected_code"),
    [
        ("me_pending", "account_pending"),
        ("me_suspended", "account_suspended"),
    ],
)
def test_non_active_account_status_maps_to_shared_code(
    fixture_name: str,
    expected_code: str,
) -> None:
    transport = FakeTransport([_response(200, FIXTURE[fixture_name])])

    account = _gateway(transport).get_me("access-fixture")

    with pytest.raises(ProxyApiError) as captured:
        account.require_active()
    assert captured.value.code == expected_code


def test_timeout_is_mapped_to_retryable_proxy_error() -> None:
    transport = FakeTransport([ProxyApiTransportError("timeout")])

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-fixture")

    assert captured.value.code == "timeout"
    assert captured.value.retryable is True
    assert captured.value.status is None


def test_network_error_is_mapped_to_retryable_proxy_error() -> None:
    transport = FakeTransport([ProxyApiTransportError("network_error")])

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-fixture")

    assert captured.value.code == "network_error"
    assert captured.value.retryable is True


def test_malformed_success_json_is_rejected() -> None:
    transport = FakeTransport(
        [
            ProxyApiHttpResponse(
                status=200,
                headers={},
                body=b"{not-json",
                document=None,
            )
        ]
    )

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-fixture")

    assert captured.value.code == "invalid_response"
    assert captured.value.retryable is False


def test_missing_required_account_fields_are_rejected() -> None:
    transport = FakeTransport(
        [
            _response(
                200,
                {
                    "identity_user_id": "11111111-1111-4111-8111-111111111111",
                    "proxy_account_id": "proxy-account-fixture",
                    "status": "active",
                },
            )
        ]
    )

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-fixture")

    assert captured.value.code == "invalid_response"


def test_invalid_account_status_is_rejected() -> None:
    document = dict(FIXTURE["me_active"])
    document["status"] = "unknown"
    transport = FakeTransport([_response(200, document)])

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-fixture")

    assert captured.value.code == "invalid_response"


def test_display_name_accepts_unicode_user_text() -> None:
    document = dict(FIXTURE["me_active"])
    document["display_name"] = "เนโกะ แทดสเตอร์"
    transport = FakeTransport([_response(200, document)])

    account = _gateway(transport).get_me("access-fixture")

    assert account.display_name == "เนโกะ แทดสเตอร์"


def test_invalid_token_response_is_rejected() -> None:
    document = dict(FIXTURE["refresh_success"])
    document["token_type"] = "mac"
    transport = FakeTransport([_response(200, document)])

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).refresh_access_token("refresh-fixture")

    assert captured.value.code == "invalid_response"


def test_oauth_style_refresh_error_is_supported() -> None:
    transport = FakeTransport([_response(400, FIXTURE["oauth_invalid_grant"])])

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).refresh_access_token("refresh-fixture")

    assert captured.value.code == "invalid_grant"
    assert captured.value.user_message == "เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่"


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (401, "invalid_token"),
        (403, "insufficient_scope"),
        (429, "rate_limited"),
        (503, "upstream_unavailable"),
    ],
)
def test_status_fallback_when_error_envelope_is_missing(
    status: int,
    expected_code: str,
) -> None:
    transport = FakeTransport([_response(status, None)])

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-fixture")

    assert captured.value.code == expected_code


def test_response_body_limit_is_enforced() -> None:
    transport = FakeTransport(
        [
            ProxyApiHttpResponse(
                status=200,
                headers={},
                body=b"x" * (65_536 + 1),
                document=None,
            )
        ]
    )

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-fixture")

    assert captured.value.code == "invalid_response"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://proxy.test",
        "https://proxy.test/api",
        "https://user:pass@proxy.test",
    ],
)
def test_proxy_api_base_url_must_be_an_https_origin(base_url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        ProxyApiGateway(
            proxy_api_base_url=base_url,
            identity_base_url="https://identity.test",
            transport=FakeTransport([]),
        )


def test_identity_base_url_must_be_an_https_origin() -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        ProxyApiGateway(
            proxy_api_base_url="https://proxy.test",
            identity_base_url="http://identity.test",
            transport=FakeTransport([]),
        )


def test_urllib_transport_rejects_insecure_urls() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        UrllibProxyApiTransport().request(
            "GET",
            "http://proxy.test/v1/me",
            headers={},
            payload=None,
            timeout=1.0,
        )


def test_error_does_not_expose_tokens(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    transport = FakeTransport([_error_response("invalid_token")])

    with pytest.raises(ProxyApiError) as captured:
        _gateway(transport).get_me("access-secret-fixture")

    rendered = f"{captured.value!r} {captured.value} {caplog.text}"
    assert "access-secret-fixture" not in rendered
    assert "refresh-secret-fixture" not in rendered


def test_token_set_repr_redacts_tokens() -> None:
    tokens = ProxyApiTokenSet(
        access_token="access-secret-fixture",
        refresh_token="refresh-secret-fixture",
        expires_in=600,
    )

    assert "access-secret-fixture" not in repr(tokens)
    assert "refresh-secret-fixture" not in repr(tokens)
