from __future__ import annotations

from collections.abc import Callable
from threading import Event

from neko_launcher.application.authorized_core import (
    AuthorizedCoreOrchestrator,
    LaunchAccessContext,
    require_core_start_running,
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
    ) -> None:
        self._orchestrator = orchestrator
        self._access_context_provider = access_context_provider

    def start(self) -> None:
        """Run the full authorized start flow; raise on any failure."""
        context = self._access_context_provider()
        cancellation = Event()
        status = self._orchestrator.start(None, context, cancellation)
        require_core_start_running(status)

    def has_owned_host(self) -> bool:
        return self._orchestrator.has_owned_host()

    def stop(self) -> None:
        """Stop proxy runtime only while retaining the owned Core host."""
        self._orchestrator.stop()

    def shutdown(self) -> None:
        """Gracefully close the exact Core host owned by this Launcher."""
        self._orchestrator.shutdown()
