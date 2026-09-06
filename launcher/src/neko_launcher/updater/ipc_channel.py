"""Duplex framed JSON IPC channel over anonymous pipes."""
from __future__ import annotations

from dataclasses import dataclass
import os
import secrets
import struct
import time
from typing import Any

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads

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

    def _read_exact(self, count: int, timeout_s: float) -> bytes:
        deadline = time.monotonic() + timeout_s
        buf = bytearray()
        while len(buf) < count:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise IpcTimeoutError("IPC read timed out")
            try:
                chunk = os.read(self.read_handle, count - len(buf))
                if not chunk:
                    raise IpcProtocolError("EOF reached on IPC read handle")
                buf.extend(chunk)
            except BlockingIOError:
                time.sleep(0.01)
            except OSError as err:
                raise IpcProtocolError(f"OS error reading IPC: {err}") from err
        return bytes(buf)

    def send_message(self, msg_type: str, body: dict[str, Any], message_id: str | None = None) -> str:
        """Send a framed message and return the message_id."""
        msg_id = message_id or secrets.token_hex(16)
        msg_obj = {
            "protocol_version": 1,
            "type": msg_type,
            "message_id": msg_id,
            "body": body,
        }
        raw_payload = canonical_json_dumps(msg_obj)
        if len(raw_payload) > MAX_IPC_FRAME_SIZE:
            raise IpcFrameTooLargeError(f"Frame size {len(raw_payload)} exceeds maximum {MAX_IPC_FRAME_SIZE}")

        prefix = struct.pack("<I", len(raw_payload))
        full_packet = prefix + raw_payload

        try:
            total_written = 0
            while total_written < len(full_packet):
                n = os.write(self.write_handle, full_packet[total_written:])
                if n == 0:
                    raise IpcProtocolError("Zero bytes written to IPC write handle")
                total_written += n
        except OSError as err:
            raise IpcProtocolError(f"Failed to write IPC frame: {err}") from err

        return msg_id

    def receive_message(self, timeout_s: float = 5.0) -> IpcMessage:
        """Receive a single framed message within timeout_s."""
        prefix_bytes = self._read_exact(4, timeout_s)
        (length,) = struct.unpack("<I", prefix_bytes)

        if length == 0:
            raise IpcProtocolError("Empty IPC frame received")
        if length > MAX_IPC_FRAME_SIZE:
            raise IpcFrameTooLargeError(f"Incoming frame length {length} exceeds maximum {MAX_IPC_FRAME_SIZE}")

        payload_bytes = self._read_exact(length, timeout_s)
        try:
            obj = canonical_json_loads(payload_bytes)
        except ValueError as err:
            raise IpcProtocolError(f"Invalid canonical JSON frame: {err}") from err

        if not isinstance(obj, dict):
            raise IpcProtocolError("IPC frame payload must be a JSON object")

        if set(obj.keys()) != {"protocol_version", "type", "message_id", "body"}:
            raise IpcProtocolError("Invalid IPC frame structure")

        if obj["protocol_version"] != 1:
            raise IpcProtocolError(f"Unsupported protocol version: {obj['protocol_version']}")
        if not isinstance(obj["type"], str):
            raise IpcProtocolError("IPC message type must be a string")
        if not isinstance(obj["message_id"], str):
            raise IpcProtocolError("IPC message_id must be a string")
        if not isinstance(obj["body"], dict):
            raise IpcProtocolError("IPC message body must be a dictionary")

        return IpcMessage(
            protocol_version=obj["protocol_version"],
            type=obj["type"],
            message_id=obj["message_id"],
            body=obj["body"],
        )

    def close(self) -> None:
        """Close open pipe handles."""
        if self.read_handle is not None and self.read_handle != -1:
            try:
                os.close(self.read_handle)
            except OSError:
                pass
            self.read_handle = -1

        if self.write_handle is not None and self.write_handle != -1:
            try:
                os.close(self.write_handle)
            except OSError:
                pass
            self.write_handle = -1
