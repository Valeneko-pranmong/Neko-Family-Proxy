from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    CoreChallenge,
    PermitDiagnosticCode,
)
from neko_launcher.application.runtime_proxy_config import LaunchAuthorizationBundle
from neko_launcher.infrastructure.core.launch_permit_gateway import (
    IssueLaunchPermitGateway,
)

CORRELATION_ID = "0123456789abcdef0123456789abcdef"


class FakeFunctions:
    def __init__(self, response: object) -> None:
        self._client = SimpleNamespace(timeout=httpx.Timeout(10.0))
        self.response = response
        self.access_token = ""
        self.body: object | None = None

    def set_auth(self, access_token: str) -> None:
        self.access_token = access_token

    def invoke(self, _name: str, options: dict[str, object]) -> object:
        self.body = options["body"]
        return self.response


def runtime_config() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "configVersion": 18,
        "endpointId": "japan-vps-1",
        "host": "127.0.0.1",
        "port": 8389,
        "protocol": "shadowsocks",
        "cipher": "aes-256-gcm",
        "credential": "SENTINEL_PROXY_SECRET_42",
        "issuedAt": 1000,
        "expiresAt": 1120,
    }


def success_response(
    *,
    contract_revision: str = "runtime-config-v1",
    runtime_config_value: object | None = None,
) -> dict[str, object]:
    return {
        "version": 1,
        "contractRevision": contract_revision,
        "correlationId": CORRELATION_ID,
        "succeeded": True,
        "permit": "header.payload.signature",
        "expiresInSeconds": 30,
        "runtimeConfig": runtime_config() if runtime_config_value is None else runtime_config_value,
    }


def issue(response: object) -> tuple[object, FakeFunctions]:
    functions = FakeFunctions(response)
    transport = SimpleNamespace(
        functions=functions,
        auth=SimpleNamespace(
            get_session=lambda: SimpleNamespace(access_token="access-token")
        ),
    )
    result = IssueLaunchPermitGateway().issue_launch_authorization(
        transport,
        CORRELATION_ID,
        CoreChallenge("a" * 43),
        10.0,
    )
    return result, functions


def test_public_authorization_accepts_exact_runtime_config_v1_bundle() -> None:
    result, functions = issue(success_response())

    assert isinstance(result, LaunchAuthorizationBundle)
    assert result.permit.reveal_for_transport() == "header.payload.signature"
    assert result.runtime_config.config_version == 18
    assert result.runtime_config.endpoint_id == "japan-vps-1"
    assert result.runtime_config.credential.reveal_for_transport() == "SENTINEL_PROXY_SECRET_42"
    assert functions.access_token == "access-token"
    assert functions.body == {
        "version": 1,
        "contractRevision": "runtime-config-v1",
        "correlationId": CORRELATION_ID,
        "challenge": "a" * 43,
    }


def test_public_authorization_sanitizes_empty_runtime_config() -> None:
    with pytest.raises(AuthorizedCoreError) as raised:
        issue(success_response(runtime_config_value={}))

    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_INVALID_RESPONSE
    assert str(raised.value) == "authorization permit is unavailable"
    assert "runtimeConfig" not in str(raised.value)
    assert "SENTINEL_PROXY_SECRET_42" not in repr(raised.value)


def test_public_authorization_rejects_lite_v1_precisely() -> None:
    with pytest.raises(AuthorizedCoreError) as raised:
        issue(success_response(contract_revision="lite-v1"))

    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_INVALID_RESPONSE
    assert str(raised.value) == "authorization permit is unavailable"
