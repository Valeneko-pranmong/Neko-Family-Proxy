from __future__ import annotations

import builtins
import json
from typing import Any

from neko_launcher.infrastructure.core.core_control_channel import NamedPipeCoreControlChannel


class _PipeHandle:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.written = b""

    def __enter__(self) -> _PipeHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def write(self, payload: bytes) -> None:
        self.written = payload

    def readline(self) -> bytes:
        return json.dumps(self._response).encode("utf-8") + b"\n"


def test_pipe_open_retries_transient_os_error(monkeypatch: Any) -> None:
    attempts = 0
    handle = _PipeHandle(
        {
            "type": "challengeResponse",
            "correlationId": "0123456789abcdef0123456789abcdef",
            "challenge": "0123456789012345678901234567890123456789012",
        }
    )

    def transient_open(*_args: object, **_kwargs: object) -> _PipeHandle:
        nonlocal attempts
        attempts += 1
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
    assert len(challenge.value) == 43
    assert handle.written.endswith(b"\n")
