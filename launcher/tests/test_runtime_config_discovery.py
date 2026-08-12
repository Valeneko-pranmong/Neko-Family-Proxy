from __future__ import annotations

import builtins
import json
from typing import Any

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    RuntimeConfigurationCandidate,
)
from neko_launcher.infrastructure.core.core_control_channel import NamedPipeCoreControlChannel

CORRELATION = "0123456789abcdef0123456789abcdef"


class PipeHandle:
    def __init__(self, response: dict[str, Any] | bytes) -> None:
        body = response if isinstance(response, bytes) else json.dumps(response).encode()
        self.response = body + b"\n"
        self.offset = 0
        self.written = b""

    def __enter__(self) -> PipeHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def write(self, payload: bytes) -> int:
        self.written += payload
        return len(payload)

    def read(self, size: int) -> bytes:
        result = self.response[self.offset : self.offset + size]
        self.offset += len(result)
        return result


@pytest.fixture(autouse=True)
def channel_identity(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        NamedPipeCoreControlChannel,
        "_configure_nonblocking",
        lambda self, handle: None,
    )
    monkeypatch.setattr(
        NamedPipeCoreControlChannel,
        "_get_server_process_id",
        lambda self, handle: 1234,
    )


def channel() -> NamedPipeCoreControlChannel:
    return NamedPipeCoreControlChannel("NekoProxyCoreControl", expected_server_pid=lambda: 1234)


def catalog_response(**overrides: Any) -> dict[str, Any]:
    response = {
        "type": "runtimeConfigCatalogResponse",
        "correlationId": CORRELATION,
        "succeeded": True,
        "candidates": [
            {
                "profileReference": "profile-17",
                "serverReference": "server-42",
                "relationshipValid": True,
                "processModeMatchCount": 1,
            }
        ],
    }
    response.update(overrides)
    return response


def validate_response(**overrides: Any) -> dict[str, Any]:
    response = {
        "type": "runtimeConfigValidateResponse",
        "correlationId": CORRELATION,
        "succeeded": True,
        "profileReference": "profile-17",
        "serverReference": "server-42",
        "relationshipValid": True,
        "processModeMatchCount": 1,
        "valid": True,
    }
    response.update(overrides)
    return response


def test_catalog_client_sends_exact_request_and_returns_only_opaque_candidates(
    monkeypatch: Any,
) -> None:
    handle = PipeHandle(catalog_response())
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    result = channel().runtime_config_catalog(CORRELATION, 1.0)

    assert result == (RuntimeConfigurationCandidate("profile-17", "server-42"),)
    assert json.loads(handle.written) == {
        "type": "runtimeConfigCatalog",
        "correlationId": CORRELATION,
    }


def test_catalog_success_empty_is_accepted(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        builtins, "open", lambda *_args, **_kwargs: PipeHandle(catalog_response(candidates=[]))
    )

    assert channel().runtime_config_catalog(CORRELATION, 1.0) == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "wrong"},
        {"correlationId": "f" * 32},
        {"candidateCount": 1},
        {"extra": "no"},
        {"candidates": [{"profileReference": "profile-17"}]},
        {
            "candidates": [
                {
                    "profileReference": "profile-17",
                    "serverReference": "server-42",
                    "relationshipValid": True,
                    "processModeMatchCount": 1,
                    "host": "secret",
                }
            ]
        },
        {
            "candidates": [
                {
                    "profileReference": "PROFILE-17",
                    "serverReference": "server-42",
                    "relationshipValid": True,
                    "processModeMatchCount": 1,
                }
            ]
        },
        {
            "candidates": [
                {
                    "profileReference": "profile-17",
                    "serverReference": "server-42",
                    "relationshipValid": False,
                    "processModeMatchCount": 1,
                }
            ]
        },
        {
            "candidates": [
                {
                    "profileReference": "profile-17",
                    "serverReference": "server-42",
                    "relationshipValid": 1,
                    "processModeMatchCount": 1,
                }
            ]
        },
        {
            "candidates": [
                {
                    "profileReference": "profile-17",
                    "serverReference": "server-42",
                    "relationshipValid": True,
                    "processModeMatchCount": True,
                }
            ]
        },
        {
            "candidates": [
                {
                    "profileReference": "profile-17",
                    "serverReference": "server-42",
                    "relationshipValid": True,
                    "processModeMatchCount": 0,
                }
            ]
        },
    ],
)
def test_catalog_rejects_non_exact_or_unsafe_response(
    monkeypatch: Any, overrides: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        builtins, "open", lambda *_args, **_kwargs: PipeHandle(catalog_response(**overrides))
    )
    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(CORRELATION, 1.0)


def test_catalog_rejects_duplicate_candidates(monkeypatch: Any) -> None:
    candidate = {
        "profileReference": "profile-17",
        "serverReference": "server-42",
        "relationshipValid": True,
        "processModeMatchCount": 1,
    }
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: PipeHandle(
            catalog_response(candidates=[candidate, candidate])
        ),
    )
    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(CORRELATION, 1.0)


def test_catalog_accepts_exactly_32_distinct_valid_candidates(monkeypatch: Any) -> None:
    candidates = [
        {
            "profileReference": f"profile-{index}",
            "serverReference": f"server-{index}",
            "relationshipValid": True,
            "processModeMatchCount": 1,
        }
        for index in range(32)
    ]
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: PipeHandle(
            catalog_response(candidates=candidates)
        ),
    )

    assert len(channel().runtime_config_catalog(CORRELATION, 1.0)) == 32


def test_catalog_rejects_more_than_32_candidates(monkeypatch: Any) -> None:
    candidates = [
        {
            "profileReference": f"profile-{index}",
            "serverReference": f"server-{index}",
            "relationshipValid": True,
            "processModeMatchCount": 1,
        }
        for index in range(33)
    ]
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: PipeHandle(
            catalog_response(candidates=candidates)
        ),
    )

    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(CORRELATION, 1.0)


@pytest.mark.parametrize("reason", ["CatalogUnavailable", "CatalogTooLarge"])
def test_catalog_typed_failure_envelope_fails_as_configuration_infrastructure(
    monkeypatch: Any, reason: str
) -> None:
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: PipeHandle(
            {
                "type": "runtimeConfigCatalogResponse",
                "correlationId": CORRELATION,
                "succeeded": False,
                "reason": reason,
            }
        ),
    )

    with pytest.raises(AuthorizedCoreError) as raised:
        channel().runtime_config_catalog(CORRELATION, 1.0)

    assert raised.value.code.value == "RUNTIME_CONFIGURATION_UNAVAILABLE"


@pytest.mark.parametrize(
    "response",
    [
        {"type": "runtimeConfigCatalogResponse", "correlationId": CORRELATION, "succeeded": False, "reason": "UnknownReason"},
        {"type": "runtimeConfigCatalogResponse", "correlationId": CORRELATION, "succeeded": False},
        {"type": "runtimeConfigCatalogResponse", "correlationId": CORRELATION, "succeeded": False, "reason": "CatalogUnavailable", "errorCode": "legacy"},
    ],
)
def test_catalog_failure_rejects_unknown_missing_or_legacy_schema(
    monkeypatch: Any, response: dict[str, Any]
) -> None:
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: PipeHandle(response))

    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(CORRELATION, 1.0)


def test_catalog_success_rejects_legacy_candidate_count_extra(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        builtins, "open", lambda *_args, **_kwargs: PipeHandle(catalog_response(candidateCount=1))
    )

    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(CORRELATION, 1.0)


def test_catalog_rejects_duplicate_json_fields(monkeypatch: Any) -> None:
    payload = (
        b'{"type":"runtimeConfigCatalogResponse",'
        b'"correlationId":"0123456789abcdef0123456789abcdef",'
        b'"candidates":[],"candidates":[]}'
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: PipeHandle(payload))
    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(CORRELATION, 1.0)


@pytest.mark.parametrize("missing", ["type", "correlationId", "succeeded", "candidates"])
def test_catalog_rejects_every_missing_field(monkeypatch: Any, missing: str) -> None:
    response = catalog_response()
    del response[missing]
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: PipeHandle(response))
    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(CORRELATION, 1.0)


def test_validate_client_requires_exact_positive_attestation(monkeypatch: Any) -> None:
    handle = PipeHandle(validate_response())
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)
    candidate = RuntimeConfigurationCandidate("profile-17", "server-42")

    result = channel().runtime_config_validate(candidate, CORRELATION, 1.0)

    assert result is candidate
    assert json.loads(handle.written) == {
        "type": "runtimeConfigValidate",
        "correlationId": CORRELATION,
        "profileReference": "profile-17",
        "serverReference": "server-42",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"relationshipValid": False, "valid": False},
        {"processModeMatchCount": 0, "valid": False},
        {"succeeded": False},
        {"valid": False},
    ],
)
def test_validate_rejects_failed_or_invalid_candidate(monkeypatch: Any, overrides: dict[str, Any]) -> None:
    monkeypatch.setattr(
        builtins, "open", lambda *_args, **_kwargs: PipeHandle(validate_response(**overrides))
    )

    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_validate(
            RuntimeConfigurationCandidate("profile-17", "server-42"), CORRELATION, 1.0
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "wrong"},
        {"correlationId": "f" * 32},
        {"profileReference": "profile-18"},
        {"serverReference": "server-43"},
        {"relationshipValid": False},
        {"relationshipValid": 1},
        {"processModeMatchCount": 0},
        {"processModeMatchCount": True},
        {"valid": False},
        {"extra": "no"},
    ],
)
def test_validate_rejects_every_non_exact_attestation(
    monkeypatch: Any, overrides: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        builtins, "open", lambda *_args, **_kwargs: PipeHandle(validate_response(**overrides))
    )
    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_validate(
            RuntimeConfigurationCandidate("profile-17", "server-42"), CORRELATION, 1.0
        )


@pytest.mark.parametrize("missing", list(validate_response()))
def test_validate_rejects_every_missing_field(monkeypatch: Any, missing: str) -> None:
    response = validate_response()
    del response[missing]
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: PipeHandle(response))
    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_validate(
            RuntimeConfigurationCandidate("profile-17", "server-42"), CORRELATION, 1.0
        )


@pytest.mark.parametrize("correlation", ["A" * 32, "a" * 31, "g" * 32, 7])
def test_discovery_rejects_non_lowercase_hex_correlation_before_transport(
    monkeypatch: Any, correlation: object
) -> None:
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: pytest.fail("transport used"))
    with pytest.raises(AuthorizedCoreError):
        channel().runtime_config_catalog(correlation, 1.0)  # type: ignore[arg-type]
