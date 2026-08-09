from __future__ import annotations


class LauncherServiceError(RuntimeError):
    """A safe, customer-facing workflow error."""


class EntitlementUnavailable(LauncherServiceError):
    """The authenticated account does not currently have product access."""


class DeviceAuthorizationDenied(LauncherServiceError):
    """The authenticated account cannot be used from this installation."""


class RecoverySessionInvalid(LauncherServiceError):
    """The recovery credential can no longer be used."""


class RecoveryRetryRequired(LauncherServiceError):
    """The exact same recovery token and password must be retried."""
