from __future__ import annotations

from threading import Event
from typing import Callable

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreOrchestrator,
    CoreStatusKind,
    LaunchAccessContext,
    OpaqueStartCommand,
)


class AuthorizedProxyGateway:
    """Production ProxyGateway backed by the authorized Core orchestrator.

    Bridges the simple start/stop ProxyGateway protocol to the full
    challenge → permit → start → Running orchestration.  The access
    context and command are resolved lazily so that the gateway can be
    composed at startup while the user is not yet logged in.
    """

    def __init__(
        self,
        orchestrator: AuthorizedCoreOrchestrator,
        access_context_provider: Callable[[], LaunchAccessContext],
        command_provider: Callable[[], OpaqueStartCommand],
    ) -> None:
        self._orchestrator = orchestrator
        self._access_context_provider = access_context_provider
        self._command_provider = command_provider

    def start(self) -> None:
        """Run the full authorized start flow; raise on any failure."""
        context = self._access_context_provider()
        command = self._command_provider()
        cancellation = Event()
        status = self._orchestrator.start(command, context, cancellation)
        if status.kind is not CoreStatusKind.RUNNING:
            raise AuthorizedCoreError("authorized start did not reach Running")

    def stop(self) -> None:
        """Best-effort cleanup of owned Core process."""
        try:
            self._orchestrator._process.stop_gracefully(
                self._orchestrator._timeouts.start
            )
        except Exception:
            pass
