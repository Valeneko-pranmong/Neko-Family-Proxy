from __future__ import annotations

import pytest
from types import SimpleNamespace

import httpx

from neko_launcher.application.authorized_core import CoreChallenge
from neko_launcher.infrastructure.core.launch_permit_gateway import (
    IssueLaunchPermitGateway,
)


class FakeFunctions:
    def __init__(self) -> None:
        self._client = SimpleNamespace(timeout=httpx.Timeout(10.0))
        self.access_token = ""
        self.body: object | None = None

    def set_auth(self, access_token: str) -> None:
        self.access_token = access_token

    def invoke(self, _name: str, options: dict[str, object]) -> object:
        self.body = options["body"]
        return {
            "version": 1,
            "contractRevision": "lite-v1",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
            "permit": "header.payload.signature",
            "expiresInSeconds": 30,
        }


def test_lite_gateway_sends_only_contract_fields() -> None:
    functions = FakeFunctions()
    transport = SimpleNamespace(
        functions=functions,
        auth=SimpleNamespace(
            get_session=lambda: SimpleNamespace(access_token="access-token")
        ),
    )

    with pytest.raises(Exception):
        permit = IssueLaunchPermitGateway().issue_launch_permit(
            transport,
            "0123456789abcdef0123456789abcdef",
            CoreChallenge("a" * 43),
            10.0,
        )

    assert functions.access_token == "access-token"
    assert functions.body == {
        "version": 1,
        "contractRevision": "runtime-config-v1",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "challenge": "a" * 43,
    }


def test_lite_gateway_accepts_only_lite_success_envelope() -> None:
    # Test file originally named for 'lite-v1', but we are testing 'runtime-config-v1' response validation now.
    # It must fail on lite-v1 and pass on runtime-config-v1 with runtimeConfig.
    assert not IssueLaunchPermitGateway._is_valid_success_response(
        {
            "version": 1,
            "contractRevision": "lite-v1",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
            "permit": "header.payload.signature",
            "expiresInSeconds": 30,
        },
        "0123456789abcdef0123456789abcdef",
        "header.payload.signature",
    )
    assert IssueLaunchPermitGateway._is_valid_success_response(
        {
            "version": 1,
            "contractRevision": "runtime-config-v1",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
            "permit": "header.payload.signature",
            "expiresInSeconds": 30,
            "runtimeConfig": {},
        },
        "0123456789abcdef0123456789abcdef",
        "header.payload.signature",
    )
    assert not IssueLaunchPermitGateway._is_valid_success_response(
        {
            "version": 1,
            "contractRevision": "lite-v1",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
            "permit": "header.payload.signature",
            "expiresInSeconds": 30,
            "configurationDigest": "b" * 64,
        },
        "0123456789abcdef0123456789abcdef",
        "header.payload.signature",
    )
