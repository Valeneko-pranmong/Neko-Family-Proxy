from __future__ import annotations

import json
import os
import re
import struct
import time
from typing import Any

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreChallenge,
    CoreStatus,
    CoreStatusKind,
    OpaquePermit,
)


_STATUS_MAP: dict[str, CoreStatusKind] = {
    "Running": CoreStatusKind.RUNNING,
    "Stopped": CoreStatusKind.STOPPED,
    "Failed": CoreStatusKind.FAILED,
}
_CHALLENGE_FIELDS = frozenset(
    {"version", "kind", "correlationId", "succeeded", "challenge"}
)
_RESULT_SUCCESS_FIELDS = frozenset(
    {"version", "kind", "correlationId", "succeeded", "status"}
)
_RESULT_FAILURE_FIELDS = _RESULT_SUCCESS_FIELDS | {"errorCode"}


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


_ERROR_CODES = frozenset(
    {
        "AuthorizationRequired",
        "AuthorizationInvalid",
        "AuthorizationExpired",
        "AuthorizationReplay",
        "AuthorizationUnavailable",
        "SessionInactive",
        "ProcessNotFound",
        "ProcessExited",
        "AlreadyRunning",
        "ProtocolInvalid",
        "Timeout",
        "Cancelled",
        "StartFailed",
        "StopFailed",
    }
)


class NamedPipeCoreControlChannel:
    """Protocol v2, length-prefixed JSON over Windows Named Pipes.

    Pipe name: ``NekoProxyCore.s0-rc1`` (Core = server, Launcher = client).
    The permit is serialized *only* inside the ``start`` frame and is never
    logged, cached, or stored.
    """

    _MAX_PAYLOAD_BYTES = 8192

    def __init__(self, pipe_name: str = "NekoProxyCore.s0-rc1") -> None:
        self._pipe_name = pipe_name
        self._pipe_path = rf"\\.\pipe\{pipe_name}"

    # ------------------------------------------------------------------
    # Wire helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        return remaining

    @staticmethod
    def _configure_nonblocking(handle: Any) -> None:
        if os.name != "nt":
            return
        import ctypes
        import msvcrt

        pipe_nowait = ctypes.c_uint32(0x00000001)
        native_handle = msvcrt.get_osfhandle(handle.fileno())
        if not ctypes.windll.kernel32.SetNamedPipeHandleState(
            ctypes.c_void_p(native_handle), ctypes.byref(pipe_nowait), None, None
        ):
            raise OSError(ctypes.get_last_error(), "cannot bound named pipe I/O")

    @classmethod
    def _read_exact(cls, handle: Any, size: int, deadline: float) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            cls._remaining(deadline)
            try:
                chunk = handle.read(size - len(chunks))
            except (BlockingIOError, OSError):
                time.sleep(min(0.01, cls._remaining(deadline)))
                continue
            if not chunk:
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
            chunks.extend(chunk)
        return bytes(chunks)

    @classmethod
    def _write_all(cls, handle: Any, payload: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(payload):
            cls._remaining(deadline)
            try:
                written = handle.write(payload[offset:])
            except (BlockingIOError, OSError):
                time.sleep(min(0.01, cls._remaining(deadline)))
                continue
            if written is None:
                # Buffered Python file objects conventionally return the count,
                # while lightweight/test pipe handles may consume all bytes.
                return
            if written <= 0:
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
            offset += written

    def _send_and_receive(
        self, message: dict[str, Any], timeout: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        try:
            handle = None
            while time.monotonic() < deadline:
                try:
                    handle = open(self._pipe_path, "r+b", buffering=0)  # noqa: SIM115
                    break
                except OSError:
                    # Windows may report a transient invalid/busy pipe while the
                    # single-instance Core server is recreating its next handle.
                    time.sleep(min(0.05, self._remaining(deadline)))

            if handle is None:
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

            with handle:
                self._configure_nonblocking(handle)
                payload = json.dumps(
                    message, separators=(",", ":"), ensure_ascii=True
                ).encode("utf-8")
                if not 1 <= len(payload) <= self._MAX_PAYLOAD_BYTES:
                    raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
                self._write_all(
                    handle, struct.pack(">I", len(payload)) + payload, deadline
                )

                response_size = struct.unpack(
                    ">I", self._read_exact(handle, 4, deadline)
                )[0]
                if not 1 <= response_size <= self._MAX_PAYLOAD_BYTES:
                    raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
                response_bytes = self._read_exact(handle, response_size, deadline)

                try:
                    response = json.loads(
                        response_bytes.decode("utf-8"),
                        object_pairs_hook=_reject_duplicate_fields,
                    )
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

                if not isinstance(response, dict):
                    raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
                return response

        except AuthorizedCoreError:
            raise
        except Exception:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

    @staticmethod
    def _require_correlation(res: dict[str, Any], expected: str) -> None:
        if res.get("correlationId") != expected:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

    # ------------------------------------------------------------------
    # Public protocol
    # ------------------------------------------------------------------

    def request_challenge(self, correlation_id: str, timeout: float) -> CoreChallenge:
        msg = {
            "version": 2,
            "command": "challenge",
            "correlationId": correlation_id,
        }
        res = self._send_and_receive(msg, timeout)

        if (
            frozenset(res) != _CHALLENGE_FIELDS
            or type(res.get("version")) is not int
            or res.get("version") != 2
            or res.get("kind") != "challenge"
            or res.get("succeeded") is not True
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_correlation(res, correlation_id)

        challenge_val = res.get("challenge")
        if not isinstance(challenge_val, str) or re.fullmatch(
            r"[A-Za-z0-9_-]{43}", challenge_val
        ) is None:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

        return CoreChallenge(value=challenge_val)

    def start_authorized(
        self,
        command: object,
        permit: OpaquePermit,
        correlation_id: str,
        timeout: float,
    ) -> CoreStatus:
        # command is TargetBoundStartCommand — accessed via duck-typing to
        # avoid a circular import.
        if not hasattr(command, "mode"):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        msg = {
            "version": 2,
            "command": "start",
            "correlationId": correlation_id,
            "mode": command.mode,  # type: ignore[attr-defined]
            "processName": command.process_name,  # type: ignore[attr-defined]
            "targetPid": command.target_pid,  # type: ignore[attr-defined]
            "profileReference": command.profile_reference,  # type: ignore[attr-defined]
            "serverReference": command.server_reference,  # type: ignore[attr-defined]
            "permit": permit.reveal_for_transport(),
        }

        res = self._send_and_receive(msg, timeout)

        if (
            type(res.get("version")) is not int
            or res.get("version") != 2
            or res.get("kind") != "result"
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_correlation(res, correlation_id)

        return self._parse_status(res)

    def stop(self, correlation_id: str, timeout: float) -> CoreStatus:
        msg = {"version": 2, "command": "stop", "correlationId": correlation_id}
        res = self._send_and_receive(msg, timeout)

        if (
            type(res.get("version")) is not int
            or res.get("version") != 2
            or res.get("kind") != "result"
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_correlation(res, correlation_id)

        return self._parse_status(res)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_status(res: dict[str, object]) -> CoreStatus:
        status_str = res.get("status")
        if not isinstance(status_str, str):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        kind = _STATUS_MAP.get(status_str)
        if kind is None:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        error_code = res.get("errorCode")
        succeeded = res.get("succeeded")
        if succeeded is True:
            if frozenset(res) != _RESULT_SUCCESS_FIELDS or kind is CoreStatusKind.FAILED:
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
            return CoreStatus(kind=kind)
        if (
            succeeded is not False
            or frozenset(res) != _RESULT_FAILURE_FIELDS
            or kind is not CoreStatusKind.FAILED
            or not isinstance(error_code, str)
            or error_code not in _ERROR_CODES
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        return CoreStatus(
            kind=kind,
            error_code=error_code,
        )
