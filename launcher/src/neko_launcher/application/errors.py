from __future__ import annotations


class LauncherServiceError(RuntimeError):
    """A safe, customer-facing workflow error."""


class EntitlementUnavailable(LauncherServiceError):
    """The authenticated account does not currently have product access."""


class SessionAlreadyActive(LauncherServiceError):
    """Another fresh Launcher session owns this account's application access."""


class DeviceAuthorizationDenied(LauncherServiceError):
    """Legacy compatibility error for deprecated installation authorization."""


class RecoverySessionInvalid(LauncherServiceError):
    """The recovery credential can no longer be used."""


class RecoveryRetryRequired(LauncherServiceError):
    """The exact same recovery token and password must be retried."""
