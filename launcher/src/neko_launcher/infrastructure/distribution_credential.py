"""Windows Credential Manager storage for controlled update distribution capability."""
from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

DISTRIBUTION_CREDENTIAL_TARGET = "NEKO-FAMILY/SoftwareUpdateDistribution/v1"
_USER_KEY = "distribution_capability"


def get_distribution_capability() -> str | None:
    """Read the distribution capability from Windows Credential Manager into memory."""
    try:
        return keyring.get_password(DISTRIBUTION_CREDENTIAL_TARGET, _USER_KEY)
    except KeyringError:
        return None


def set_distribution_capability(capability: str) -> None:
    """Write the distribution capability into Windows Credential Manager under the target."""
    if not isinstance(capability, str) or not capability:
        raise ValueError("Capability must be a non-empty string")
    keyring.set_password(DISTRIBUTION_CREDENTIAL_TARGET, _USER_KEY, capability)


def clear_distribution_capability() -> None:
    """Delete the distribution capability from Windows Credential Manager."""
    try:
        keyring.delete_password(DISTRIBUTION_CREDENTIAL_TARGET, _USER_KEY)
    except (PasswordDeleteError, KeyringError):
        pass
