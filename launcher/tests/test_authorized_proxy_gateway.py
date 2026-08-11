from threading import Event

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    AuthorizedCoreFailureDomain,
    CoreStatus,
    CoreStatusKind,
    LaunchAccessContext,
    OpaqueStartCommand,
)
from neko_launcher.infrastructure.core.authorized_proxy_gateway import (
    AuthorizedProxyGateway,
)


class StatusReturningOrchestrator:
    def __init__(self, status: CoreStatus) -> None:
        self._status = status

    def start(
        self,
        command: OpaqueStartCommand,
        context: LaunchAccessContext,
        cancellation: Event,
    ) -> CoreStatus:
        del command, context, cancellation
        return self._status

    def has_owned_host(self) -> bool:
        return False

    def stop(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


def gateway_for(status: CoreStatus) -> AuthorizedProxyGateway:
    return AuthorizedProxyGateway(
        orchestrator=StatusReturningOrchestrator(status),  # type: ignore[arg-type]
        access_context_provider=lambda: LaunchAccessContext(
            True, True, "session", "installation", object()
        ),
        command_provider=lambda: OpaqueStartCommand("profile-17", "server-42"),
    )


def test_gateway_defensively_preserves_typed_failed_status() -> None:
    gateway = gateway_for(CoreStatus(CoreStatusKind.FAILED, "ConfigurationMismatch"))

    with pytest.raises(AuthorizedCoreError) as raised:
        gateway.start()

    assert raised.value.code is AuthorizedCoreErrorCode.CONFIGURATION_MISMATCH
    assert raised.value.domain is AuthorizedCoreFailureDomain.CONFIGURATION


def test_gateway_defensively_fails_closed_for_unknown_failed_status() -> None:
    gateway = gateway_for(CoreStatus(CoreStatusKind.FAILED, "raw untrusted detail"))

    with pytest.raises(AuthorizedCoreError) as raised:
        gateway.start()

    assert raised.value.code is AuthorizedCoreErrorCode.ADAPTER_FAILURE
    assert "raw untrusted detail" not in str(raised.value)


def test_gateway_uses_running_not_reached_only_without_typed_failure() -> None:
    gateway = gateway_for(CoreStatus(CoreStatusKind.STOPPED))

    with pytest.raises(AuthorizedCoreError) as raised:
        gateway.start()

    assert raised.value.code is AuthorizedCoreErrorCode.RUNNING_NOT_REACHED


def test_gateway_running_success_is_unchanged() -> None:
    gateway_for(CoreStatus(CoreStatusKind.RUNNING)).start()
