from __future__ import annotations

import builtins
import json
import os
import threading
import time
import uuid
from multiprocessing.connection import Listener
from typing import Any

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreControlError,
    CoreControlFailureCode,
    CoreStatusKind,
    OpaquePermit,
)
from neko_launcher.infrastructure.core.core_control_channel import NamedPipeCoreControlChannel


@pytest.fixture(autouse=True)
def _stub_windows_nonblocking_configuration(
    monkeypatch: Any, request: pytest.FixtureRequest
) -> None:
    if request.node.name == "test_real_windows_pipe_read_is_bounded_by_deadline":
        return
    monkeypatch.setattr(
        NamedPipeCoreControlChannel,
        "_configure_nonblocking",
        staticmethod(lambda _: None),
    )
    monkeypatch.setattr(
        NamedPipeCoreControlChannel,
        "_get_server_process_id",
        staticmethod(lambda _: 1234),
    )


class _PipeHandle:
    def __init__(self, response: dict[str, Any] | bytes) -> None:
        payload = (
            response
            if isinstance(response, bytes)
            else json.dumps(response, separators=(",", ":")).encode("utf-8")
        )
        self._response = payload + b"\n"
        self._read_offset = 0
        self.written = b""

    def __enter__(self) -> _PipeHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def write(self, payload: bytes) -> int:
        self.written += payload
        return len(payload)

    def read(self, size: int) -> bytes:
        chunk = self._response[self._read_offset : self._read_offset + size]
        self._read_offset += len(chunk)
        return chunk


def _channel(
    pipe_name: str = "NekoProxyCoreControl",
    expected_server_pid: int = 1234,
) -> NamedPipeCoreControlChannel:
    return NamedPipeCoreControlChannel(
        pipe_name,
        expected_server_pid=lambda: expected_server_pid,
    )


def test_pipe_server_pid_is_verified_before_any_request_bytes_are_written(
    monkeypatch: Any,
) -> None:
    handle = _PipeHandle(_challenge_response())
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)
    monkeypatch.setattr(
        NamedPipeCoreControlChannel,
        "_get_server_process_id",
        staticmethod(lambda _: 9999),
    )

    with pytest.raises(AuthorizedCoreError) as raised:
        _channel().request_challenge(
            "0123456789abcdef0123456789abcdef",
            1.0,
        )

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
    assert handle.written == b""


def _challenge_response(**overrides: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "type": "challengeResponse",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "challenge": "0123456789012345678901234567890123456789012",
    }
    response.update(overrides)
    return response


def test_challenge_rejects_unknown_fields(monkeypatch: Any) -> None:
    handle = _PipeHandle(_challenge_response(extra="rejected"))
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(Exception):
        _channel().request_challenge("0123456789abcdef0123456789abcdef", 1.0)


def test_challenge_rejects_duplicate_json_fields(monkeypatch: Any) -> None:
    payload = (
        b'{"type":"challengeResponse",'
        b'"correlationId":"0123456789abcdef0123456789abcdef",'
        b'"challenge":"0123456789012345678901234567890123456789012",'
        b'"challenge":"0123456789012345678901234567890123456789012"}'
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: _PipeHandle(payload))

    with pytest.raises(Exception):
        _channel().request_challenge("0123456789abcdef0123456789abcdef", 1.0)


def test_challenge_rejects_numeric_non_integer_version(monkeypatch: Any) -> None:
    handle = _PipeHandle(_challenge_response(version=2.0))
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(AuthorizedCoreError):
        _channel().request_challenge("0123456789abcdef0123456789abcdef", 1.0)


def test_challenge_rejects_non_exact_base64url_length(monkeypatch: Any) -> None:
    handle = _PipeHandle(_challenge_response(challenge="a" * 42))
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(Exception):
        _channel().request_challenge("0123456789abcdef0123456789abcdef", 1.0)


def test_result_rejects_numeric_non_integer_version(monkeypatch: Any) -> None:
    handle = _PipeHandle(
        {
            "version": 2.0,
            "kind": "result",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
            "status": "Stopped",
        }
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(AuthorizedCoreError):
        _channel().stop("0123456789abcdef0123456789abcdef", 1.0)


def test_result_rejects_contradictory_success_fields(monkeypatch: Any) -> None:
    handle = _PipeHandle(
        {
            "type": "stopResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
            "status": "Failed",
            "errorCode": "AuthorizationInvalid",
        }
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)
    channel = _channel()
    with pytest.raises(Exception):
        channel.stop("0123456789abcdef0123456789abcdef", 1.0)


def test_stop_sends_runtime_only_wire_request(monkeypatch: Any) -> None:
    handle = _PipeHandle(
        {
            "type": "stopResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
            "status": "Stopped",
        }
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    status = _channel().stop("0123456789abcdef0123456789abcdef", 1.0)

    assert status.kind is CoreStatusKind.STOPPED
    assert json.loads(handle.written.decode("utf-8").removesuffix("\n")) == {
        "type": "stop",
        "correlationId": "0123456789abcdef0123456789abcdef",
    }


def _shutdown_response(**overrides: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "type": "shutdownResponse",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "succeeded": True,
        "status": "Stopped",
    }
    response.update(overrides)
    return response


def test_shutdown_uses_exact_released_wire_contract(monkeypatch: Any) -> None:
    handle = _PipeHandle(_shutdown_response())
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    status = _channel().shutdown("0123456789abcdef0123456789abcdef", 1.0)

    assert status.kind is CoreStatusKind.STOPPED
    assert json.loads(handle.written.decode("utf-8").removesuffix("\n")) == {
        "type": "shutdown",
        "correlationId": "0123456789abcdef0123456789abcdef",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "stopResponse"},
        {"correlationId": "fedcba9876543210fedcba9876543210"},
        {"succeeded": False, "status": "Failed", "errorCode": "StopFailed"},
        {"status": "Running"},
        {"extra": "rejected"},
    ],
)
def test_shutdown_rejects_non_exact_response(monkeypatch: Any, overrides: dict[str, Any]) -> None:
    handle = _PipeHandle(_shutdown_response(**overrides))
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(AuthorizedCoreError):
        _channel().shutdown("0123456789abcdef0123456789abcdef", 1.0)


def test_shutdown_pipe_pid_mismatch_is_rejected_before_write(
    monkeypatch: Any,
) -> None:
    handle = _PipeHandle(_shutdown_response())
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)
    monkeypatch.setattr(
        NamedPipeCoreControlChannel,
        "_get_server_process_id",
        staticmethod(lambda _: 9999),
    )

    with pytest.raises(AuthorizedCoreError):
        _channel().shutdown("0123456789abcdef0123456789abcdef", 1.0)

    assert handle.written == b""


def test_read_timeout_uses_one_total_operation_deadline(monkeypatch: Any) -> None:
    class BlockingReadHandle(_PipeHandle):
        reads = 0

        def read(self, size: int) -> bytes:
            self.reads += 1
            raise BlockingIOError

    handle = BlockingReadHandle(_challenge_response())
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: handle,
    )

    times = iter([0.0, 0.0, 0.0, 0.0, 0.0, 0.03])
    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_control_channel.time.monotonic",
        lambda: next(times),
    )
    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_control_channel.time.sleep",
        lambda _: None,
    )
    with pytest.raises(Exception):
        _channel().request_challenge("0123456789abcdef0123456789abcdef", 0.02)
    assert handle.reads == 1


def test_closed_pipe_is_distinct_from_response_timeout(monkeypatch: Any) -> None:
    class ClosedPipeHandle(_PipeHandle):
        def read(self, size: int) -> bytes:
            raise OSError(109, "pipe has ended")

    handle = ClosedPipeHandle(_challenge_response())
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(CoreControlError) as raised:
        _channel().request_challenge("0123456789abcdef0123456789abcdef", 1.0)

    assert raised.value.control_code is CoreControlFailureCode.PIPE_CLOSED


def test_pipe_open_retries_transient_os_error(monkeypatch: Any) -> None:
    attempts = 0
    handle = _PipeHandle(
        {
            "type": "challengeResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "challenge": "0123456789012345678901234567890123456789012",
        }
    )
    opened_paths: list[str] = []

    def transient_open(path: str, *_args: object, **_kwargs: object) -> _PipeHandle:
        nonlocal attempts
        attempts += 1
        opened_paths.append(path)
        if attempts == 1:
            raise OSError(22, "pipe server is between instances")
        return handle

    monkeypatch.setattr(builtins, "open", transient_open)
    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_control_channel.time.sleep",
        lambda _: None,
    )

    challenge = _channel().request_challenge(
        "0123456789abcdef0123456789abcdef",
        1.0,
    )

    assert attempts == 2
    assert opened_paths == [
        r"\\.\pipe\NekoProxyCoreControl",
        r"\\.\pipe\NekoProxyCoreControl",
    ]
    assert len(challenge.value) == 43
    payload = json.loads(handle.written.decode("utf-8").removesuffix("\n"))
    assert payload == {
        "type": "challenge",
        "correlationId": "0123456789abcdef0123456789abcdef",
    }


@pytest.mark.parametrize(
    "error_code",
    [
        "AuthorizationRequired",
        "AuthorizationInvalid",
        "AuthorizationExpired",
        "AuthorizationReplay",
        "AuthorizationUnavailable",
        "SessionInactive",
        "EntitlementInactive",
        "HeartbeatStale",
        "ProcessNotFound",
        "ProcessExited",
        "ConfigurationMismatch",
        "AlreadyRunning",
        "ProtocolInvalid",
        "StartTimeout",
        "Cancelled",
        "StartFailed",
        "StopFailed",
    ],
)
def test_start_accepts_every_released_core_failure_code(
    monkeypatch: Any,
    error_code: str,
) -> None:
    handle = _PipeHandle(
        {
            "type": "startResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "status": "Failed",
            "succeeded": False,
            "errorCode": error_code,
        }
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    class Command:
        mode = "ProcessMode"
        process_name = "pso2.exe"
        target_pid = 1234
        profile_reference = "profile-0"
        server_reference = "server-0"

    status = _channel().start_authorized(
        Command(),
        OpaquePermit("header.payload.signature"),
        "0123456789abcdef0123456789abcdef",
        1.0,
    )

    assert status.kind is CoreStatusKind.FAILED
    assert status.error_code == error_code


def test_start_rejects_removed_timeout_error_code(monkeypatch: Any) -> None:
    handle = _PipeHandle(
        {
            "type": "startResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "status": "Failed",
            "succeeded": False,
            "errorCode": "Timeout",
        }
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    class Command:
        mode = "ProcessMode"
        process_name = "pso2.exe"
        target_pid = 1234
        profile_reference = "profile-0"
        server_reference = "server-0"

    with pytest.raises(AuthorizedCoreError) as raised:
        _channel().start_authorized(
            Command(),
            OpaquePermit("header.payload.signature"),
            "0123456789abcdef0123456789abcdef",
            1.0,
        )

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE


@pytest.mark.parametrize(
    "response",
    [
        {
            "type": "startResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "status": "Failed",
            "succeeded": False,
        },
        {
            "type": "startResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "status": "Failed",
            "succeeded": False,
            "errorCode": "UnknownCoreError",
        },
        {
            "type": "startResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "status": "Failed",
            "succeeded": False,
            "errorCode": "AuthorizationInvalid",
            "extra": "rejected",
        },
        {
            "type": "startResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "status": "Running",
            "succeeded": False,
            "errorCode": "AuthorizationInvalid",
        },
    ],
)
def test_start_failure_response_fails_closed_when_not_exact(
    monkeypatch: Any,
    response: dict[str, Any],
) -> None:
    handle = _PipeHandle(response)
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    class Command:
        mode = "ProcessMode"
        process_name = "pso2.exe"
        target_pid = 1234
        profile_reference = "profile-0"
        server_reference = "server-0"

    with pytest.raises(AuthorizedCoreError) as raised:
        _channel().start_authorized(
            Command(),
            OpaquePermit("header.payload.signature"),
            "0123456789abcdef0123456789abcdef",
            1.0,
        )

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE


def test_start_rejects_malformed_json_response(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        builtins,
        "open",
        lambda *_args, **_kwargs: _PipeHandle(b'{"type":"startResponse"'),
    )

    class Command:
        mode = "ProcessMode"
        process_name = "pso2.exe"
        target_pid = 1234
        profile_reference = "profile-0"
        server_reference = "server-0"

    with pytest.raises(AuthorizedCoreError) as raised:
        _channel().start_authorized(
            Command(),
            OpaquePermit("header.payload.signature"),
            "0123456789abcdef0123456789abcdef",
            1.0,
        )

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE


def test_start_uses_released_core_wire_contract(monkeypatch: Any) -> None:
    handle = _PipeHandle(
        {
            "type": "startResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "status": "Running",
            "succeeded": True,
        }
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    class Command:
        mode = "ProcessMode"
        process_name = "pso2.exe"
        target_pid = 1234
        profile_reference = "profile-0"
        server_reference = "server-0"

    status = _channel().start_authorized(
        Command(),
        OpaquePermit("header.payload.signature"),
        "0123456789abcdef0123456789abcdef",
        1.0,
    )

    assert status.kind is CoreStatusKind.RUNNING
    payload = json.loads(handle.written.decode("utf-8").removesuffix("\n"))
    assert payload == {
        "type": "start",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "protocolVersion": 2,
        "mode": "ProcessMode",
        "processName": "pso2.exe",
        "targetPid": 1234,
        "profileReference": "profile-0",
        "serverReference": "server-0",
        "permit": "header.payload.signature",
    }


def test_pipe_open_retry_sleep_is_clamped_to_total_deadline(monkeypatch: Any) -> None:
    sleeps: list[float] = []
    times = iter([0.0, 0.0, 0.99, 1.0])

    def fail_open(*_args: object, **_kwargs: object) -> object:
        raise OSError

    monkeypatch.setattr(builtins, "open", fail_open)
    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_control_channel.time.monotonic",
        lambda: next(times),
    )
    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_control_channel.time.sleep",
        sleeps.append,
    )

    with pytest.raises(Exception):
        _channel().request_challenge("0123456789abcdef0123456789abcdef", 1.0)

    assert sleeps == [pytest.approx(0.01)]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows named pipes")
def test_real_windows_pipe_read_is_bounded_by_deadline() -> None:
    pipe_name = f"NekoLauncherDeadline.{uuid.uuid4().hex}"
    pipe_path = rf"\\.\pipe\{pipe_name}"
    ready = threading.Event()
    release = threading.Event()
    server_errors: list[BaseException] = []

    def withhold_response() -> None:
        try:
            with Listener(pipe_path, family="AF_PIPE") as listener:
                ready.set()
                connection = listener.accept()
                try:
                    release.wait(timeout=2.0)
                finally:
                    connection.close()
        except BaseException as exc:
            server_errors.append(exc)
            ready.set()

    server = threading.Thread(target=withhold_response, daemon=True)
    server.start()
    assert ready.wait(timeout=1.0)
    assert server_errors == []

    started = time.monotonic()
    try:
        with pytest.raises(AuthorizedCoreError) as raised:
            _channel(pipe_name, expected_server_pid=os.getpid()).request_challenge(
                "0123456789abcdef0123456789abcdef", 0.2
            )
        assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        server.join(timeout=1.0)

    assert server.is_alive() is False
    assert server_errors == []
