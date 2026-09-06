"""Duplex framed JSON IPC channel over anonymous pipes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_IPC_FRAME_SIZE = 131_072


class IpcError(Exception):
    """Base exception for IPC channel errors."""


class IpcTimeoutError(IpcError):
    """Raised when an IPC read operation times out."""


class IpcProtocolError(IpcError):
    """Raised when an invalid or malformed frame is received."""


class IpcFrameTooLargeError(IpcError):
    """Raised when a frame exceeds MAX_IPC_FRAME_SIZE."""


@dataclass(frozen=True)
class IpcMessage:
    protocol_version: int
    type: str
    message_id: str
    body: dict[str, Any]


class FramedIpcChannel:
    """Provides duplex framed JSON messaging over pipe handles."""

    def __init__(self, read_handle: int, write_handle: int) -> None:
        self.read_handle = read_handle
        self.write_handle = write_handle

    def send_message(self, msg_type: str, body: dict[str, Any], message_id: str | None = None) -> str:
        """Send a framed message and return the message_id."""
        raise NotImplementedError("send_message not implemented")

    def receive_message(self, timeout_s: float = 5.0) -> IpcMessage:
        """Receive a single framed message within timeout_s."""
        raise NotImplementedError("receive_message not implemented")

    def close(self) -> None:
        """Close open pipe handles."""
        raise NotImplementedError("close not implemented")
