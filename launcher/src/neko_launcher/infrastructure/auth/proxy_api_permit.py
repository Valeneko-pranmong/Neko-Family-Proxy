from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreChallenge,
    OpaquePermit,
    PermitDiagnosticCode,
)
from neko_launcher.application.runtime_proxy_config import (
    LaunchAuthorizationBundle,
    OpaqueRuntimeCredential,
    RuntimeProxyConfig,
)

from .proxy_api_gateway import ProxyApiError, ProxyApiGateway
from .proxy_api_session import ProxyApiAccessTokenProvider, call_with_access_token

_RUNTIME_CONFIG_FIELDS = {
    "schema_version",
    "config_version",
    "endpoint_id",
    "host",
    "port",
    "protocol",
    "cipher",
    "credential",
    "issued_at",
    "expires_at",
}


class ProxyApiPermitGateway:
    """Proxy API launch-permit adapter for the frozen Core Runtime Config v1."""

    def __init__(
        self,
        client: ProxyApiGateway,
        tokens: ProxyApiAccessTokenProvider,
        session_id_provider: Callable[[], str],
        *,
        idempotency_key_factory: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._tokens = tokens
        self._session_id_provider = session_id_provider
        self._idempotency_key_factory = (
            idempotency_key_factory or (lambda: uuid4().hex)
        )

    def issue_launch_authorization(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        timeout: float,
    ) -> LaunchAuthorizationBundle:
        del timeout
        if authenticated_transport is None:
            raise self._failure(
                PermitDiagnosticCode.PERMIT_AUTH_SESSION_UNAVAILABLE,
                correlation_id,
            )
        session_id = self._session_id_provider()
        if not session_id:
            raise self._failure(
                PermitDiagnosticCode.PERMIT_AUTH_SESSION_UNAVAILABLE,
                correlation_id,
            )
        idempotency_key = self._idempotency_key_factory()
        try:
            permit = call_with_access_token(
                self._tokens,
                lambda token: self._client.issue_launch_permit(
                    token,
                    session_id=session_id,
                    challenge=challenge.value,
                    correlation_id=correlation_id,
                    idempotency_key=idempotency_key,
                ),
            )
        except ProxyApiError as error:
            raise self._failure(
                _diagnostic_code_for(error),
                correlation_id,
            ) from None
        except Exception:
            raise self._failure(
                PermitDiagnosticCode.PERMIT_UNAVAILABLE,
                correlation_id,
            ) from None
        try:
            runtime_config = _runtime_config(permit.runtime_config)
            bundle = LaunchAuthorizationBundle(
                permit=OpaquePermit(permit.permit),
                runtime_config=runtime_config,
            )
        except Exception:
            raise self._failure(
                PermitDiagnosticCode.PERMIT_INVALID_RESPONSE,
                correlation_id,
            ) from None
        if permit.correlation_id != correlation_id:
            raise self._failure(
                PermitDiagnosticCode.PERMIT_INVALID_RESPONSE,
                correlation_id,
            )
        return bundle

    @staticmethod
    def _failure(
        diagnostic_code: PermitDiagnosticCode,
        correlation_id: str,
    ) -> AuthorizedCoreError:
        return AuthorizedCoreError(
            AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
            diagnostic_code=diagnostic_code,
            diagnostic_context={
                "function": "issue_launch_permit",
                "stage": "PERMIT_REQUEST",
                "correlation_id": correlation_id,
            },
        )


def _diagnostic_code_for(error: ProxyApiError) -> PermitDiagnosticCode:
    if error.code == "timeout":
        return PermitDiagnosticCode.PERMIT_TIMEOUT
    if error.status == 401:
        return PermitDiagnosticCode.PERMIT_HTTP_401
    if error.status == 403:
        return PermitDiagnosticCode.PERMIT_HTTP_403
    if error.status == 404:
        return PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND
    if error.status is not None and 500 <= error.status <= 599:
        return PermitDiagnosticCode.PERMIT_HTTP_500
    if error.code == "invalid_response":
        return PermitDiagnosticCode.PERMIT_INVALID_RESPONSE
    return PermitDiagnosticCode.PERMIT_UNAVAILABLE


def _runtime_config(document: dict[str, object]) -> RuntimeProxyConfig:
    if set(document) != _RUNTIME_CONFIG_FIELDS:
        raise ValueError("runtime config fields do not match Runtime Config v1")
    credential = document["credential"]
    if not isinstance(credential, str):
        raise ValueError("runtime credential is not text")
    return RuntimeProxyConfig(
        schema_version=document["schema_version"],
        config_version=document["config_version"],
        endpoint_id=document["endpoint_id"],
        host=document["host"],
        port=document["port"],
        protocol=document["protocol"],
        cipher=document["cipher"],
        credential=OpaqueRuntimeCredential(credential),
        issued_at=document["issued_at"],
        expires_at=document["expires_at"],
    )
