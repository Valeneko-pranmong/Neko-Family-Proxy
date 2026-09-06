"""Windows Credential Manager storage for controlled update distribution capability."""
from __future__ import annotations

DISTRIBUTION_CREDENTIAL_TARGET = "NEKO-FAMILY/SoftwareUpdateDistribution/v1"


def get_distribution_capability() -> str | None:
    """Read the distribution capability from Windows Credential Manager into memory."""
    raise NotImplementedError("get_distribution_capability not implemented")


def set_distribution_capability(capability: str) -> None:
    """Write the distribution capability into Windows Credential Manager under the target."""
    raise NotImplementedError("set_distribution_capability not implemented")


def clear_distribution_capability() -> None:
    """Delete the distribution capability from Windows Credential Manager."""
    raise NotImplementedError("clear_distribution_capability not implemented")
