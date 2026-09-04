from __future__ import annotations

from math import isfinite
from time import monotonic
from typing import Any

import httpx

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreChallenge,
    OpaquePermit,
    PermitDiagnosticCode,
)
from neko_launcher.application.runtime_proxy_config import (
    LaunchAuthorizationBundle,
    RuntimeProxyConfig,
)


_FUNCTION_NAME = "issue_launch_permit"
_CONTRACT_REVISION = "runtime-config-v1"


class IssueLaunchPermitGateway:
    """Authenticated adapter for the canonical launch-permit Edge Function."""

    def issue_launch_authorization(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        timeout: float,
    ) -> LaunchAuthorizationBundle:
        started_at = monotonic()
        try:
            auth = getattr(authenticated_transport, "auth")
            session = auth.get_session()
            access_token = getattr(session, "access_token", None)
            if not isinstance(access_token, str) or not access_token:
                raise self._failure(
                    PermitDiagnosticCode.PERMIT_AUTH_SESSION_UNAVAILABLE,
                    correlation_id,
                    started_at,
                )

            functions = getattr(authenticated_transport, "functions")
            function_http_client = getattr(functions, "_client", None)
            if not self.timeout_is_bounded(function_http_client, timeout):
                raise self._failure(
                    PermitDiagnosticCode.PERMIT_TIMEOUT,
                    correlation_id,
                    started_at,
                )
            set_auth = getattr(functions, "set_auth")
            set_auth(access_token)
            response: Any = functions.invoke(
                _FUNCTION_NAME,
                {
                    "body": {
                        "version": 1,
                        "contractRevision": _CONTRACT_REVISION,
                        "correlationId": correlation_id,
                        "challenge": challenge.value,
                    },
                    "responseType": "json",
                },
            )
        except AuthorizedCoreError:
            raise
        except Exception as exc:
            raise self._failure_for_exception(
                exc,
                correlation_id,
                started_at,
            ) from None

        if not isinstance(response, dict):
            raise self._failure(
                PermitDiagnosticCode.PERMIT_INVALID_RESPONSE,
                correlation_id,
                started_at,
            )
        permit = response.get("permit")
        if not isinstance(permit, str) or not permit:
            raise self._failure(
                PermitDiagnosticCode.PERMIT_MISSING_FIELD,
                correlation_id,
                started_at,
            )
        runtime_config_raw = response.get("runtimeConfig")
        if not isinstance(runtime_config_raw, dict):
            raise self._failure(
                PermitDiagnosticCode.PERMIT_MISSING_FIELD,
                correlation_id,
                started_at,
            )
        if not self._is_valid_success_response(response, correlation_id, permit):
            raise self._failure(
                PermitDiagnosticCode.PERMIT_INVALID_RESPONSE,
                correlation_id,
                started_at,
            )
        try:
            runtime_config = RuntimeProxyConfig.from_dict(runtime_config_raw)
        except Exception:
            raise self._failure(
                PermitDiagnosticCode.PERMIT_INVALID_RESPONSE,
                correlation_id,
                started_at,
            ) from None
        return LaunchAuthorizationBundle(
            permit=OpaquePermit(permit),
            runtime_config=runtime_config,
        )

    def issue_launch_permit(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        timeout: float,
    ) -> OpaquePermit:
        bundle = self.issue_launch_authorization(
            authenticated_transport,
            correlation_id,
            challenge,
            timeout,
        )
        return bundle.permit

    @staticmethod
    def _is_valid_success_response(
        response: dict[object, object],
        correlation_id: str,
        permit: str,
    ) -> bool:
        if set(response) != {
            "version",
            "contractRevision",
            "correlationId",
            "succeeded",
            "permit",
            "expiresInSeconds",
            "runtimeConfig",
        }:
            return False
        return (
            type(response["version"]) is int
            and response["version"] == 1
            and response["contractRevision"] == _CONTRACT_REVISION
            and response["correlationId"] == correlation_id
            and response["succeeded"] is True
            and 1 <= len(permit) <= 4096
            and permit.isascii()
            and type(response["expiresInSeconds"]) is int
            and response["expiresInSeconds"] == 30
            and isinstance(response["runtimeConfig"], dict)
        )

    @staticmethod
    def timeout_is_bounded(http_client: object, deadline: float) -> bool:
        """Confirm the pinned SDK client cannot exceed the operation deadline."""
        if not isinstance(deadline, (int, float)) or not isfinite(deadline):
            return False
        if deadline <= 0:
            return False
        configured = getattr(http_client, "timeout", None)
        values = (
            getattr(configured, "connect", None),
            getattr(configured, "read", None),
            getattr(configured, "write", None),
            getattr(configured, "pool", None),
        )
        return all(
            isinstance(value, (int, float))
            and isfinite(value)
            and 0 < value <= deadline
            for value in values
        )

    @classmethod
    def _failure_for_exception(
        cls,
        exc: Exception,
        correlation_id: str,
        started_at: float,
    ) -> AuthorizedCoreError:
        status = getattr(exc, "status", None)
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            diagnostic_code = PermitDiagnosticCode.PERMIT_TIMEOUT
        elif status == 401:
            diagnostic_code = PermitDiagnosticCode.PERMIT_HTTP_401
        elif status == 403 and cls._is_backend_edge_session_inactive(exc):
            diagnostic_code = PermitDiagnosticCode.BACKEND_EDGE_SESSION_INACTIVE
        elif status == 403:
            diagnostic_code = PermitDiagnosticCode.PERMIT_HTTP_403
        elif status == 404:
            diagnostic_code = PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND
        elif isinstance(status, int) and 500 <= status <= 599:
            diagnostic_code = PermitDiagnosticCode.PERMIT_HTTP_500
        else:
            diagnostic_code = PermitDiagnosticCode.PERMIT_UNAVAILABLE
        return cls._failure(
            diagnostic_code,
            correlation_id,
            started_at,
            http_status=status if isinstance(status, int) else None,
            exception_class=type(exc).__name__,
        )

    @staticmethod
    def _is_backend_edge_session_inactive(exc: Exception) -> bool:
        """Accept only the fixed, safe Edge error needed by the proof harness.

        The Supabase Functions SDK exposes the JSON ``error`` value as the
        exception message.  Do not retain or surface arbitrary response text.
        """
        return getattr(exc, "message", None) == "SessionInactive" or str(exc) == (
            "SessionInactive"
        )

    @staticmethod
    def _failure(
        diagnostic_code: PermitDiagnosticCode,
        correlation_id: str,
        started_at: float,
        *,
        http_status: int | None = None,
        exception_class: str | None = None,
    ) -> AuthorizedCoreError:
        context: dict[str, object] = {
            "function": _FUNCTION_NAME,
            "stage": "PERMIT_REQUEST",
            "correlation_id": correlation_id,
            "elapsed_ms": max(0, round((monotonic() - started_at) * 1000)),
        }
        if http_status is not None:
            context["http_status"] = http_status
        if exception_class:
            context["exception_class"] = exception_class
        return AuthorizedCoreError(
            AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
            diagnostic_code=diagnostic_code,
            diagnostic_context=context,
        )
