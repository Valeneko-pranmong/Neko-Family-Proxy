from __future__ import annotations

from types import SimpleNamespace

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    CoreChallenge,
)
from neko_launcher.infrastructure.core.launch_permit_gateway import (
    IssueLaunchPermitGateway,
)


class FakeFunctions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.function_name = ""
        self.invoke_options: dict[str, object] = {}

    def invoke(self, function_name: str, invoke_options: dict[str, object]) -> object:
        self.function_name = function_name
        self.invoke_options = invoke_options
        return self.response


def test_gateway_uses_issue_launch_permit_contract_exactly() -> None:
    functions = FakeFunctions({"permit": "header.payload.signature"})
    transport = SimpleNamespace(functions=functions)

    permit = IssueLaunchPermitGateway().issue_launch_permit(
        transport,
        "0123456789abcdef0123456789abcdef",
        CoreChallenge("a" * 43),
        "b" * 64,
        "pso2.exe",
        4242,
        "ProcessMode",
        "neko-family-proxy",
        "proxy:start",
        10.0,
    )

    assert functions.function_name == "issue_launch_permit"
    assert functions.invoke_options == {
        "body": {
            "challenge": "a" * 43,
            "configuration_digest": "b" * 64,
            "process_name": "pso2.exe",
            "target_pid": 4242,
            "mode": "ProcessMode",
            "product": "neko-family-proxy",
            "scope": "proxy:start",
        },
        "responseType": "json",
    }
    assert permit.reveal_for_transport() == "header.payload.signature"


@pytest.mark.parametrize(
    "response",
    [None, {}, {"permit": ""}, {"permit": 42}, b"not-json"],
)
def test_gateway_rejects_response_without_string_permit(response: object) -> None:
    transport = SimpleNamespace(functions=FakeFunctions(response))

    with pytest.raises(AuthorizedCoreError, match="authorization permit is unavailable"):
        IssueLaunchPermitGateway().issue_launch_permit(
            transport,
            "0123456789abcdef0123456789abcdef",
            CoreChallenge("a" * 43),
            "b" * 64,
            "pso2.exe",
            4242,
            "ProcessMode",
            "neko-family-proxy",
            "proxy:start",
            10.0,
        )
