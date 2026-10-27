from __future__ import annotations

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreChallenge,
    PermitDiagnosticCode,
)
from neko_launcher.application.runtime_proxy_config import RuntimeProxyConfig
from neko_launcher.infrastructure.auth.proxy_api_gateway import (
    ProxyApiError,
    ProxyLaunchPermit,
)
from neko_launcher.infrastructure.auth.proxy_api_permit import ProxyApiPermitGateway

SESSION_ID = "77777777-7777-4777-8777-777777777777"
CORRELATION_ID = "0123456789abcdef0123456789abcdef"
CHALLENGE = "a" * 43
IDEMPOTENCY_KEY = "idem-permit-fixture-1234"

RUNTIME_CONFIG = {
    "schema_version": 1,
    "config_version": 42,
    "endpoint_id": "jp-01",
    "host": "proxy.example.invalid",
    "port": 8388,
    "protocol": "shadowsocks",
    "cipher": "aes-256-gcm",
    "credential": "runtime-credential-fixture",
    "issued_at": 1792931696,
    "expires_at": 1792931816,
}


class FakeTokens:
    def __init__(self) -> None:
        self.token = "access-fixture"
        self.refresh_count = 0

    def access_token(self) -> str:
        return self.token

    def refresh_access_token(self) -> str:
        self.refresh_count += 1
        self.token = "refreshed-access-fixture"
        return self.token


class FakeClient:
    def __init__(self) -> None:
        self.errors: list[Exception] = []
        self.calls: list[dict[str, object]] = []
        self.permit = "header-fixture.payload-fixture.signature-fixture"
        self.runtime_config = dict(RUNTIME_CONFIG)

    def issue_launch_permit(self, access_token: str, **kwargs):
        self.calls.append({"token": access_token, **kwargs})
        if self.errors:
            raise self.errors.pop(0)
        return ProxyLaunchPermit(
            permit=self.permit,
            expires_in_seconds=30,
            correlation_id=kwargs["correlation_id"],
            runtime_config=dict(self.runtime_config),
        )


def _gateway(
    client: FakeClient | None = None,
    tokens: FakeTokens | None = None,
    *,
    session_id: str = SESSION_ID,
) -> tuple[ProxyApiPermitGateway, FakeClient, FakeTokens]:
    client = client or FakeClient()
    tokens = tokens or FakeTokens()
    gateway = ProxyApiPermitGateway(
        client,
        tokens,
        lambda: session_id,
        idempotency_key_factory=lambda: IDEMPOTENCY_KEY,
    )
    return gateway, client, tokens


def _issue(gateway: ProxyApiPermitGateway):
    return gateway.issue_launch_authorization(
        object(),
        CORRELATION_ID,
        CoreChallenge(CHALLENGE),
        10.0,
    )


def test_permit_maps_runtime_config_v1_and_preserves_permit() -> None:
    gateway, client, _ = _gateway()

    bundle = _issue(gateway)

    assert bundle.permit.reveal_for_transport() == (
        "header-fixture.payload-fixture.signature-fixture"
    )
    assert bundle.runtime_config.canonical_digest == RuntimeProxyConfig.from_dict(
        {
            "schemaVersion": 1,
            "configVersion": 42,
            "endpointId": "jp-01",
            "host": "proxy.example.invalid",
            "port": 8388,
            "protocol": "shadowsocks",
            "cipher": "aes-256-gcm",
            "credential": "runtime-credential-fixture",
            "issuedAt": 1792931696,
            "expiresAt": 1792931816,
        }
    ).canonical_digest
    assert bundle.runtime_config.credential.reveal_for_transport() == (
        "runtime-credential-fixture"
    )
    assert client.calls == [
        {
            "token": "access-fixture",
            "session_id": SESSION_ID,
            "challenge": CHALLENGE,
            "correlation_id": CORRELATION_ID,
            "idempotency_key": IDEMPOTENCY_KEY,
        }
    ]


def test_permit_refreshes_once_after_401() -> None:
    client = FakeClient()
    client.errors = [ProxyApiError("invalid_token", status=401)]
    tokens = FakeTokens()
    keys: list[str] = []

    def next_key() -> str:
        keys.append(f"idem-permit-{len(keys) + 1}")
        return keys[-1]

    gateway = ProxyApiPermitGateway(
        client,
        tokens,
        lambda: SESSION_ID,
        idempotency_key_factory=next_key,
    )

    bundle = _issue(gateway)

    assert bundle.permit.reveal_for_transport()
    assert tokens.refresh_count == 1
    assert client.calls[0]["token"] == "access-fixture"
    assert client.calls[1]["token"] == "refreshed-access-fixture"
    assert len(keys) == 1
    assert (
        client.calls[0]["idempotency_key"]
        == client.calls[1]["idempotency_key"]
        == "idem-permit-1"
    )


def test_permit_without_session_fails_closed_before_network() -> None:
    gateway, client, _ = _gateway(session_id="")

    with pytest.raises(AuthorizedCoreError) as captured:
        _issue(gateway)

    assert captured.value.code is AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE
    assert captured.value.diagnostic_code is (
        PermitDiagnosticCode.PERMIT_AUTH_SESSION_UNAVAILABLE
    )
    assert client.calls == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda config: config.pop("expires_at"),
        lambda config: config.update({"expires_at": config["issued_at"] + 121}),
        lambda config: config.update({"protocol": "http"}),
        lambda config: config.update({"credential": ""}),
        lambda config: config.update({"extra": "field"}),
    ],
)
def test_permit_rejects_runtime_config_contract_violations(mutate) -> None:
    client = FakeClient()
    mutate(client.runtime_config)
    gateway, _, _ = _gateway(client)

    with pytest.raises(AuthorizedCoreError) as captured:
        _issue(gateway)

    assert captured.value.diagnostic_code is (
        PermitDiagnosticCode.PERMIT_INVALID_RESPONSE
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProxyApiError("invalid_token", status=401), PermitDiagnosticCode.PERMIT_HTTP_401),
        (ProxyApiError("insufficient_scope", status=403), PermitDiagnosticCode.PERMIT_HTTP_403),
        (ProxyApiError("not_found", status=404), PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND),
        (ProxyApiError("upstream_unavailable", status=503), PermitDiagnosticCode.PERMIT_HTTP_500),
        (ProxyApiError("runtime_config_unavailable", status=503), PermitDiagnosticCode.PERMIT_HTTP_500),
        (ProxyApiError("timeout"), PermitDiagnosticCode.PERMIT_TIMEOUT),
        (ProxyApiError("invalid_response"), PermitDiagnosticCode.PERMIT_INVALID_RESPONSE),
    ],
)
def test_permit_maps_api_errors_to_core_diagnostics(
    error: ProxyApiError,
    expected: PermitDiagnosticCode,
) -> None:
    client = FakeClient()
    client.errors = [error, error]
    gateway, _, _ = _gateway(client)

    with pytest.raises(AuthorizedCoreError) as captured:
        _issue(gateway)

    assert captured.value.code is AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE
    assert captured.value.diagnostic_code is expected


def test_permit_repr_redacts_secrets() -> None:
    permit = ProxyLaunchPermit(
        permit="header-fixture.payload-fixture.signature-fixture",
        expires_in_seconds=30,
        correlation_id=CORRELATION_ID,
        runtime_config=dict(RUNTIME_CONFIG),
    )

    rendered = repr(permit)
    assert "header-fixture" not in rendered
    assert "runtime-credential-fixture" not in rendered
