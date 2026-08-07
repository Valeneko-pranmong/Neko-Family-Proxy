from __future__ import annotations

from typing import Any

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreChallenge,
    OpaquePermit,
)


class IssueLaunchPermitGateway:
    """Adapter for the canonical issue_launch_permit Edge Function."""

    def issue_launch_permit(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        configuration_digest: str,
        process_name: str,
        target_pid: int,
        mode: str,
        product: str,
        scope: str,
        timeout: float,
    ) -> OpaquePermit:
        del correlation_id, timeout
        try:
            functions = getattr(authenticated_transport, "functions")
            response: Any = functions.invoke(
                "issue_launch_permit",
                {
                    "body": {
                        "challenge": challenge.value,
                        "configuration_digest": configuration_digest,
                        "process_name": process_name,
                        "target_pid": target_pid,
                        "mode": mode,
                        "product": product,
                        "scope": scope,
                    },
                    "responseType": "json",
                },
            )
        except Exception:
            raise AuthorizedCoreError(
                AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE
            ) from None

        if not isinstance(response, dict):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE)
        permit = response.get("permit")
        if not isinstance(permit, str) or not permit:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE)
        return OpaquePermit(permit)
