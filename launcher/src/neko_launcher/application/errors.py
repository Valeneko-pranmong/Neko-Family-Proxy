from __future__ import annotations


class LauncherServiceError(RuntimeError):
    """A safe, customer-facing workflow error."""


class EntitlementUnavailable(LauncherServiceError):
    """The authenticated account does not currently have product access."""
