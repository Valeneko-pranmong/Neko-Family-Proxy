from __future__ import annotations

import builtins
import json
import os
import struct
import threading
import time
import uuid
from multiprocessing.connection import Listener

from typing import Any

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
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


class _PipeHandle:
    def __init__(self, response: dict[str, Any] | bytes) -> None:
        payload = (
            response
            if isinstance(response, bytes)
            else json.dumps(response, separators=(",", ":")).encode("utf-8")
        )
        self._response = struct.pack(">I", len(payload)) + payload
        self._read_offset = 0
        self.written = b""

    def __enter__(self) -> _PipeHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


    def write(self, payload: bytes) -> None:
        self.written += payload

    def read(self, size: int) -> bytes:
        chunk = self._response[self._read_offset : self._read_offset + size]
        self._read_offset += len(chunk)
        return chunk


def _challenge_response(**overrides: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "version": 2,
        "kind": "challenge",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "succeeded": True,
        "challenge": "0123456789012345678901234567890123456789012",
    }
    response.update(overrides)
    return response


def test_challenge_rejects_unknown_fields(monkeypatch: Any) -> None:
    handle = _PipeHandle(_challenge_response(extra="rejected"))
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(Exception):
        NamedPipeCoreControlChannel().request_challenge(
            "0123456789abcdef0123456789abcdef", 1.0
        )


def test_challenge_rejects_duplicate_json_fields(monkeypatch: Any) -> None:
    payload = (
        b'{"version":2,"version":2,"kind":"challenge",'
        b'"correlationId":"0123456789abcdef0123456789abcdef",'
        b'"succeeded":true,"challenge":"0123456789012345678901234567890123456789012"}'
    )
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: _PipeHandle(payload))

    with pytest.raises(Exception):
        NamedPipeCoreControlChannel().request_challenge(
            "0123456789abcdef0123456789abcdef", 1.0
        )


def test_challenge_rejects_numeric_non_integer_version(monkeypatch: Any) -> None:
    handle = _PipeHandle(_challenge_response(version=2.0))
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(AuthorizedCoreError):
        NamedPipeCoreControlChannel().request_challenge(
            "0123456789abcdef0123456789abcdef", 1.0
        )


def test_challenge_rejects_non_exact_base64url_length(monkeypatch: Any) -> None:
    handle = _PipeHandle(_challenge_response(challenge="a" * 42))
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(Exception):
        NamedPipeCoreControlChannel().request_challenge(
            "0123456789abcdef0123456789abcdef", 1.0
        )


def test_result_rejects_numeric_non_integer_version(monkeypatch: Any) -> None:
    handle = _PipeHandle({
        "version": 2.0, "kind": "result",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "succeeded": True, "status": "Stopped",
    })
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)

    with pytest.raises(AuthorizedCoreError):
        NamedPipeCoreControlChannel().stop(
            "0123456789abcdef0123456789abcdef", 1.0
        )


def test_result_rejects_contradictory_success_fields(monkeypatch: Any) -> None:
    handle = _PipeHandle({
        "version": 2, "kind": "result",
        "correlationId": "0123456789abcdef0123456789abcdef",
        "succeeded": True, "status": "Failed", "errorCode": "AuthorizationInvalid",
    })
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: handle)
    channel = NamedPipeCoreControlChannel()
    with pytest.raises(Exception):
        channel.stop("0123456789abcdef0123456789abcdef", 1.0)


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
        NamedPipeCoreControlChannel().request_challenge(
            "0123456789abcdef0123456789abcdef", 0.02
        )
    assert handle.reads == 1


def test_pipe_open_retries_transient_os_error(monkeypatch: Any) -> None:
    attempts = 0
    handle = _PipeHandle(
        {
            "version": 2,
            "kind": "challenge",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "succeeded": True,
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
    monkeypatch.setattr("neko_launcher.infrastructure.core.core_control_channel.time.sleep", lambda _: None)

    challenge = NamedPipeCoreControlChannel().request_challenge(
        "0123456789abcdef0123456789abcdef",
        1.0,
    )

    assert attempts == 2
    assert opened_paths == [
        r"\\.\pipe\NekoProxyCore.s0-rc1",
        r"\\.\pipe\NekoProxyCore.s0-rc1",
    ]
    assert len(challenge.value) == 43
    payload_size = struct.unpack(">I", handle.written[:4])[0]
    payload = json.loads(handle.written[4:].decode("utf-8"))
    assert payload_size == len(handle.written[4:])
    assert payload == {
        "version": 2,
        "command": "challenge",
        "correlationId": "0123456789abcdef0123456789abcdef",
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
        NamedPipeCoreControlChannel().request_challenge(
            "0123456789abcdef0123456789abcdef", 1.0
        )

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
            NamedPipeCoreControlChannel(pipe_name).request_challenge(
                "0123456789abcdef0123456789abcdef", 0.2
            )
        assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        server.join(timeout=1.0)

    assert server.is_alive() is False
    assert server_errors == []
