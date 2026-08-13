from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    CoreChallenge,
    PermitDiagnosticCode,
)
from neko_launcher.infrastructure.core.launch_permit_gateway import (
    IssueLaunchPermitGateway,
)


class FakeFunctions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.function_name = ""
        self.invoke_options: dict[str, object] = {}
        self.access_token: str | None = None
        self._client = SimpleNamespace(timeout=httpx.Timeout(10.0))

    def set_auth(self, access_token: str) -> None:
        self.access_token = access_token

    def invoke(self, function_name: str, invoke_options: dict[str, object]) -> object:
        self.function_name = function_name
        self.invoke_options = invoke_options
        return self.response


class FakeAuth:
    def __init__(self, access_token: str | None = "authenticated-access-token") -> None:
        self.access_token = access_token

    def get_session(self) -> object | None:
        if self.access_token is None:
            return None
        return SimpleNamespace(access_token=self.access_token)


def transport_for(
    functions: FakeFunctions,
    *,
    access_token: str | None = "authenticated-access-token",
) -> object:
    return SimpleNamespace(functions=functions, auth=FakeAuth(access_token))


def success_response(
    *,
    correlation_id: str = "0123456789abcdef0123456789abcdef",
    permit: object = "header.payload.signature",
    **overrides: object,
) -> dict[str, object]:
    response: dict[str, object] = {
        "version": 1,
        "contractRevision": "s0-rc1",
        "correlationId": correlation_id,
        "succeeded": True,
        "permit": permit,
        "expiresInSeconds": 30,
    }
    response.update(overrides)
    return response


def issue(transport: object, timeout: float = 10.0) -> object:
    return IssueLaunchPermitGateway().issue_launch_permit(
        transport,
        "0123456789abcdef0123456789abcdef",
        CoreChallenge("a" * 43),
        "b" * 64,
        "pso2.exe",
        4242,
        "ProcessMode",
        "neko-family-proxy",
        "proxy:start",
        timeout,
    )


def test_gateway_uses_authenticated_issue_launch_permit_contract_exactly() -> None:
    functions = FakeFunctions(success_response())

    permit = issue(transport_for(functions))

    assert functions.access_token == "authenticated-access-token"
    assert functions.function_name == "issue_launch_permit"
    assert functions.invoke_options == {
        "body": {
            "version": 1,
            "contractRevision": "s0-rc1",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "challenge": "a" * 43,
            "configurationDigest": "b" * 64,
            "processName": "pso2.exe",
            "targetPid": 4242,
            "mode": "ProcessMode",
            "product": "neko-family-proxy",
            "scope": "proxy:start",
        },
        "responseType": "json",
    }
    assert permit.reveal_for_transport() == "header.payload.signature"


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (None, PermitDiagnosticCode.PERMIT_INVALID_RESPONSE),
        (b"not-json", PermitDiagnosticCode.PERMIT_INVALID_RESPONSE),
        ({}, PermitDiagnosticCode.PERMIT_MISSING_FIELD),
        (success_response(permit=""), PermitDiagnosticCode.PERMIT_MISSING_FIELD),
        (success_response(permit=42), PermitDiagnosticCode.PERMIT_MISSING_FIELD),
    ],
)
def test_gateway_rejects_malformed_or_missing_permit(
    response: object,
    expected: PermitDiagnosticCode,
) -> None:
    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(FakeFunctions(response)))

    assert raised.value.diagnostic_code is expected
    assert str(raised.value) == "authorization permit is unavailable"


class FunctionFailure(RuntimeError):
    def __init__(self, status: int, message: str = "sensitive backend response must not be logged") -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, PermitDiagnosticCode.PERMIT_HTTP_401),
        (403, PermitDiagnosticCode.PERMIT_HTTP_403),
        (404, PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND),
        (500, PermitDiagnosticCode.PERMIT_HTTP_500),
    ],
)
def test_gateway_classifies_http_failure_without_exposing_backend_detail(
    status: int,
    expected: PermitDiagnosticCode,
) -> None:
    functions = FakeFunctions(None)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise FunctionFailure(status)

    functions.invoke = fail  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(functions))

    assert raised.value.diagnostic_code is expected
    assert raised.value.diagnostic_context["http_status"] == status
    assert raised.value.diagnostic_context["function"] == "issue_launch_permit"
    assert str(raised.value) == "authorization permit is unavailable"
    assert "sensitive backend response" not in str(raised.value)


def test_gateway_classifies_only_the_fixed_edge_session_inactive_response() -> None:
    functions = FakeFunctions(None)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise FunctionFailure(403, "SessionInactive")

    functions.invoke = fail  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(functions))

    assert (
        raised.value.diagnostic_code
        is PermitDiagnosticCode.BACKEND_EDGE_SESSION_INACTIVE
    )
    assert raised.value.diagnostic_context["http_status"] == 403


def test_gateway_does_not_misclassify_another_403_as_session_inactive() -> None:
    functions = FakeFunctions(None)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise FunctionFailure(403, "sensitive backend response must not be logged")

    functions.invoke = fail  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(functions))

    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_HTTP_403


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("sensitive timeout detail"), httpx.ReadTimeout("sensitive timeout detail")],
)
def test_gateway_classifies_timeout(failure: Exception) -> None:
    functions = FakeFunctions(None)

    def timeout(*_args: object, **_kwargs: object) -> object:
        raise failure

    functions.invoke = timeout  # type: ignore[method-assign]

    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(functions))

    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_TIMEOUT
    assert "sensitive timeout detail" not in str(raised.value)


def test_gateway_rejects_missing_authenticated_session_before_invocation() -> None:
    functions = FakeFunctions({"permit": "must-not-be-returned"})

    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(functions, access_token=None))

    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_AUTH_SESSION_UNAVAILABLE
    assert functions.function_name == ""


def test_gateway_rejects_function_client_timeout_above_deadline() -> None:
    functions = FakeFunctions({"permit": "must-not-be-returned"})

    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(functions), timeout=2.5)

    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_TIMEOUT
    assert functions.function_name == ""


@pytest.mark.parametrize(
    "response",
    [
        success_response(version=2),
        success_response(contractRevision="s0-rc2"),
        success_response(correlation_id="fedcba9876543210fedcba9876543210"),
        success_response(succeeded=False),
        success_response(expiresInSeconds=29),
        success_response(unexpected=True),
        success_response(permit="x" * 4097),
    ],
)
def test_gateway_rejects_response_outside_s0_rc1_schema(
    response: dict[str, object],
) -> None:
    with pytest.raises(AuthorizedCoreError) as raised:
        issue(transport_for(FakeFunctions(response)))

    assert raised.value.diagnostic_code is PermitDiagnosticCode.PERMIT_INVALID_RESPONSE
