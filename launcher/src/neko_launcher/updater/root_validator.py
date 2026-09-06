"""KnownFolder root and process elevation validator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RootValidationResult:
    valid: bool
    error_code: str | None = None
    reason: str | None = None


def get_expected_install_root() -> Path:
    """Retrieve the expected installation root under FOLDERID_UserProgramFiles."""
    raise NotImplementedError("get_expected_install_root not implemented")


def is_process_elevated() -> bool:
    """Check if the current process token is elevated."""
    raise NotImplementedError("is_process_elevated not implemented")


def validate_install_root(path: Path) -> RootValidationResult:
    """Validate that path conforms to the unelevated NTFS KnownFolder install root requirements."""
    raise NotImplementedError("validate_install_root not implemented")
