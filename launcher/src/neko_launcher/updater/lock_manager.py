"""Root control lock and process family lease manager."""
from __future__ import annotations

from pathlib import Path


class LockBusyError(OSError):
    """Raised when the root control lock cannot be acquired within timeout."""


class RootLockManager:
    """Manages permanent control.lock and inheritable family.lease for process family tracking."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.control_handle: int | None = None
        self.lease_handle: int | None = None

    def acquire_control_lock(self, timeout_s: float = 10.0) -> int:
        """Acquire exclusive byte 0 lock on state/control.lock."""
        raise NotImplementedError("acquire_control_lock not implemented")

    def probe_family_quiescence(self, timeout_s: float = 30.0) -> bool:
        """Probe whether all prior descendant family lease handles have closed."""
        raise NotImplementedError("probe_family_quiescence not implemented")

    def create_inheritable_family_lease(self) -> int:
        """Open state/family.lease with FILE_SHARE_READ and bInheritHandle=True."""
        raise NotImplementedError("create_inheritable_family_lease not implemented")

    def release_all(self) -> None:
        """Close held lock and lease handles."""
        raise NotImplementedError("release_all not implemented")
