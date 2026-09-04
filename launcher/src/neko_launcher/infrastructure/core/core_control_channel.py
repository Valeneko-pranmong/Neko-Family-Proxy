from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from typing import Any

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreChallenge,
    CoreControlError,
    CoreControlFailureCode,
    CoreStatus,
    CoreStatusKind,
    OpaquePermit,
    RuntimeConfigurationCandidate,
)

_STATUS_MAP: dict[str, CoreStatusKind] = {
    "Running": CoreStatusKind.RUNNING,
    "Stopped": CoreStatusKind.STOPPED,
    "Failed": CoreStatusKind.FAILED,
}
_CHALLENGE_FIELDS = frozenset({"type", "correlationId", "challenge"})
_RESULT_SUCCESS_FIELDS = frozenset({"type", "correlationId", "succeeded", "status"})
_RESULT_FAILURE_FIELDS = _RESULT_SUCCESS_FIELDS | {"errorCode"}
_CATALOG_FIELDS = frozenset({"type", "correlationId", "succeeded", "candidates"})
_CATALOG_FAILURE_FIELDS = frozenset({"type", "correlationId", "succeeded", "reason"})
_CATALOG_FAILURE_REASONS = frozenset({"CatalogUnavailable", "CatalogTooLarge"})
_CANDIDATE_FIELDS = frozenset(
    {
        "profileReference",
        "serverReference",
        "relationshipValid",
        "processModeMatchCount",
    }
)
_VALIDATE_FIELDS = frozenset(
    {
        "type",
        "correlationId",
        "succeeded",
        "profileReference",
        "serverReference",
        "relationshipValid",
        "processModeMatchCount",
        "valid",
    }
)


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
    }
)


class NamedPipeCoreControlChannel:
    """Protocol v2, newline-delimited JSON over Windows Named Pipes.

    Pipe name: ``NekoProxyCoreControl`` (Core = server, Launcher = client).
    The permit is serialized *only* inside the ``start`` frame and is never
    logged, cached, or stored.
    """

    _MAX_PAYLOAD_BYTES = 8192
    _WRITE_CHUNK_SIZE = 256
    _CLOSED_PIPE_ERRORS = frozenset({109, 233})

    def __init__(
        self,
        pipe_name: str,
        *,
        expected_server_pid: Callable[[], int | None],
    ) -> None:
        self._pipe_name = pipe_name
        self._pipe_path = rf"\\.\pipe\{pipe_name}"
        self._expected_server_pid = expected_server_pid

    # ------------------------------------------------------------------
    # Wire helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CoreControlError(CoreControlFailureCode.OPERATION_TIMEOUT)
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

    @staticmethod
    def _get_server_process_id(handle: Any) -> int:
        if os.name != "nt":
            raise OSError("named-pipe server identity is Windows-only")
        import ctypes
        import msvcrt

        native_handle = msvcrt.get_osfhandle(handle.fileno())
        server_pid = ctypes.c_uint32()
        if not ctypes.windll.kernel32.GetNamedPipeServerProcessId(
            ctypes.c_void_p(native_handle), ctypes.byref(server_pid)
        ):
            raise OSError(ctypes.get_last_error(), "cannot identify named-pipe server")
        return int(server_pid.value)

    def _require_owned_server(self, handle: Any) -> None:
        expected_pid = self._expected_server_pid()
        try:
            actual_pid = self._get_server_process_id(handle)
        except OSError:
            raise CoreControlError(CoreControlFailureCode.PIPE_IDENTITY_MISMATCH) from None
        if expected_pid is None or actual_pid != expected_pid:
            raise CoreControlError(CoreControlFailureCode.PIPE_IDENTITY_MISMATCH)

    @classmethod
    def _read_frame(cls, handle: Any, deadline: float) -> bytes:
        payload = bytearray()
        while len(payload) <= cls._MAX_PAYLOAD_BYTES:
            cls._remaining(deadline)
            try:
                chunk = handle.read(1)
            except BlockingIOError:
                time.sleep(min(0.01, cls._remaining(deadline)))
                continue
            except OSError as exc:
                error_code = getattr(exc, "winerror", None) or exc.errno
                if error_code in cls._CLOSED_PIPE_ERRORS:
                    raise CoreControlError(CoreControlFailureCode.PIPE_CLOSED) from None
                time.sleep(min(0.01, cls._remaining(deadline)))
                continue
            if not chunk:
                # A PIPE_NOWAIT Windows handle may report an empty read while
                # the verified server is still preparing its response.
                time.sleep(min(0.01, cls._remaining(deadline)))
                continue
            if chunk == b"\n":
                if not payload:
                    raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)
                return bytes(payload)
            payload.extend(chunk)
        raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)

    @classmethod
    def _write_all(cls, handle: Any, payload: bytes, deadline: float) -> None:
        offset = 0
        while offset < len(payload):
            cls._remaining(deadline)
            chunk_size = min(len(payload) - offset, cls._WRITE_CHUNK_SIZE)
            try:
                written = handle.write(payload[offset : offset + chunk_size])
            except BlockingIOError:
                time.sleep(min(0.005, cls._remaining(deadline)))
                continue
            except OSError as exc:
                error_code = getattr(exc, "winerror", None) or exc.errno
                if error_code in cls._CLOSED_PIPE_ERRORS:
                    raise CoreControlError(CoreControlFailureCode.PIPE_CLOSED) from None
                time.sleep(min(0.005, cls._remaining(deadline)))
                continue
            if written is None:
                # Raw non-blocking I/O returns None when it would block; no
                # request bytes have been accepted yet.
                time.sleep(min(0.005, cls._remaining(deadline)))
                continue
            if written <= 0:
                raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)
            offset += written

    def _send_and_receive(
        self,
        message: dict[str, Any],
        timeout: float,
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
                raise CoreControlError(CoreControlFailureCode.PIPE_UNAVAILABLE)

            with handle:
                self._configure_nonblocking(handle)
                self._require_owned_server(handle)
                payload = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode(
                    "utf-8"
                )
                if not 1 <= len(payload) <= self._MAX_PAYLOAD_BYTES:
                    raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)
                self._write_all(handle, payload + b"\n", deadline)

                response_bytes = self._read_frame(handle, deadline)

                try:
                    response = json.loads(
                        response_bytes.decode("utf-8"),
                        object_pairs_hook=_reject_duplicate_fields,
                    )
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)

                if not isinstance(response, dict):
                    raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)
                return response

        except AuthorizedCoreError:
            raise
        except Exception:
            raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)

    @staticmethod
    def _require_correlation(res: dict[str, Any], expected: str) -> None:
        if res.get("correlationId") != expected:
            raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)

    @staticmethod
    def _require_request_correlation(correlation_id: str) -> None:
        if (
            not isinstance(correlation_id, str)
            or re.fullmatch(r"[0-9a-f]{32}", correlation_id) is None
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

    # ------------------------------------------------------------------
    # Public protocol
    # ------------------------------------------------------------------

    def runtime_config_catalog(
        self, correlation_id: str, timeout: float
    ) -> tuple[RuntimeConfigurationCandidate, ...]:
        self._require_request_correlation(correlation_id)
        res = self._send_and_receive(
            {
                "type": "runtimeConfigCatalog",
                "correlationId": correlation_id,
            },
            timeout,
        )
        self._require_correlation(res, correlation_id)
        if frozenset(res) == _CATALOG_FAILURE_FIELDS:
            if (
                res.get("type") == "runtimeConfigCatalogResponse"
                and res.get("succeeded") is False
                and res.get("reason") in _CATALOG_FAILURE_REASONS
            ):
                raise AuthorizedCoreError(
                    AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE,
                    retry_safe=res.get("reason") == "CatalogUnavailable",
                )
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        if (
            frozenset(res) != _CATALOG_FIELDS
            or res.get("type") != "runtimeConfigCatalogResponse"
            or res.get("succeeded") is not True
            or not isinstance(res.get("candidates"), list)
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        values = res["candidates"]
        candidate_count = len(values)
        if candidate_count > 32:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        candidates: list[RuntimeConfigurationCandidate] = []
        for value in values:
            if not isinstance(value, dict) or frozenset(value) != _CANDIDATE_FIELDS:
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
            if (
                value.get("relationshipValid") is not True
                or isinstance(value.get("processModeMatchCount"), bool)
                or value.get("processModeMatchCount") != 1
            ):
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
            try:
                candidate = RuntimeConfigurationCandidate(
                    value["profileReference"], value["serverReference"]
                )
            except (KeyError, AuthorizedCoreError):
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE) from None
            if candidate in candidates:
                raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
            candidates.append(candidate)
        return tuple(candidates)

    def runtime_config_validate(
        self,
        candidate: RuntimeConfigurationCandidate,
        correlation_id: str,
        timeout: float,
    ) -> RuntimeConfigurationCandidate:
        if not isinstance(candidate, RuntimeConfigurationCandidate):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_request_correlation(correlation_id)
        res = self._send_and_receive(
            {
                "type": "runtimeConfigValidate",
                "correlationId": correlation_id,
                "profileReference": candidate.profile_reference,
                "serverReference": candidate.server_reference,
            },
            timeout,
        )
        if frozenset(res) != _VALIDATE_FIELDS or res.get("type") != "runtimeConfigValidateResponse":
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_correlation(res, correlation_id)
        if (
            res.get("succeeded") is not True
            or res.get("profileReference") != candidate.profile_reference
            or res.get("serverReference") != candidate.server_reference
            or not isinstance(res.get("relationshipValid"), bool)
            or not isinstance(res.get("processModeMatchCount"), int)
            or isinstance(res.get("processModeMatchCount"), bool)
            or not isinstance(res.get("valid"), bool)
            or res.get("valid")
            != (
                res.get("relationshipValid") is True
                and res.get("processModeMatchCount") == 1
            )
            or res.get("valid") is not True
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        return candidate

    def request_challenge(self, correlation_id: str, timeout: float) -> CoreChallenge:
        msg = {
            "type": "challenge",
            "correlationId": correlation_id,
        }
        res = self._send_and_receive(msg, timeout)

        if frozenset(res) != _CHALLENGE_FIELDS or res.get("type") != "challengeResponse":
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_correlation(res, correlation_id)

        challenge_val = res.get("challenge")
        if (
            not isinstance(challenge_val, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge_val) is None
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

        return CoreChallenge(value=challenge_val)

    def start_authorized(
        self,
        command: object,
        authorization: object,
        correlation_id: str,
        timeout: float,
    ) -> CoreStatus:
        # command is TargetBoundStartCommand — accessed via duck-typing to
        # avoid a circular import.
        if not hasattr(command, "mode"):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        from neko_launcher.application.runtime_proxy_config import (
            LaunchAuthorizationBundle,
        )
        if not isinstance(authorization, LaunchAuthorizationBundle):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)

        cfg = authorization.runtime_config
        msg = {
            "type": "start",
            "correlationId": correlation_id,
            "protocolVersion": 3,
            "mode": command.mode,  # type: ignore[attr-defined]
            "processName": command.process_name,  # type: ignore[attr-defined]
            "targetPid": command.target_pid,  # type: ignore[attr-defined]
            "profileReference": command.profile_reference,  # type: ignore[attr-defined]
            "serverReference": command.server_reference,  # type: ignore[attr-defined]
            "permit": authorization.permit.reveal_for_transport(),
            "runtimeConfig": {
                "schemaVersion": cfg.schema_version,
                "configVersion": cfg.config_version,
                "endpointId": cfg.endpoint_id,
                "host": cfg.host,
                "port": cfg.port,
                "protocol": cfg.protocol,
                "cipher": cfg.cipher,
                "credential": cfg.credential.reveal_for_transport(),
                "issuedAt": cfg.issued_at,
                "expiresAt": cfg.expires_at,
            },
        }

        res = self._send_and_receive(msg, timeout)

        if res.get("type") != "startResponse":
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_correlation(res, correlation_id)

        return self._parse_status(res)

    def stop(self, correlation_id: str, timeout: float) -> CoreStatus:
        msg = {"type": "stop", "correlationId": correlation_id}
        res = self._send_and_receive(msg, timeout)

        if res.get("type") != "stopResponse":
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.ADAPTER_FAILURE)
        self._require_correlation(res, correlation_id)

        return self._parse_status(res)

    def status(self, correlation_id: str, timeout: float) -> CoreStatus:
        msg = {"type": "status", "correlationId": correlation_id}
        res = self._send_and_receive(msg, timeout)

        if res.get("type") != "statusResponse":
            raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)
        self._require_correlation(res, correlation_id)

        return self._parse_status(res)

    def shutdown(self, correlation_id: str, timeout: float) -> CoreStatus:
        msg = {"type": "shutdown", "correlationId": correlation_id}
        res = self._send_and_receive(msg, timeout)

        if res.get("type") != "shutdownResponse":
            raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)
        self._require_correlation(res, correlation_id)
        if res.get("succeeded") is not True:
            raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)

        status = self._parse_status(res)
        if status.kind is not CoreStatusKind.STOPPED:
            raise CoreControlError(CoreControlFailureCode.RESPONSE_REJECTED)
        return status

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
