from __future__ import annotations

import builtins
import json
import struct
from typing import Any

from neko_launcher.infrastructure.core.core_control_channel import NamedPipeCoreControlChannel


class _PipeHandle:
    def __init__(self, response: dict[str, Any]) -> None:
        payload = json.dumps(response, separators=(",", ":")).encode("utf-8")
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
