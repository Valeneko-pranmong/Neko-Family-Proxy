import ctypes
from pathlib import Path
import sys

import pytest

from neko_launcher.updater.lock_manager import LockBusyError, RootLockManager


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 locks require Windows")
def test_control_lock_contention(tmp_path: Path) -> None:
    mgr1 = RootLockManager(tmp_path)
    mgr2 = RootLockManager(tmp_path)
    mgr1.acquire_control_lock(timeout_s=1.0)
    try:
        with pytest.raises(LockBusyError):
            mgr2.acquire_control_lock(timeout_s=0.2)
    finally:
        mgr1.release_all()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 locks require Windows")
def test_family_lease_quiescence_detects_open_handles(tmp_path: Path) -> None:
    mgr = RootLockManager(tmp_path)
    mgr.acquire_control_lock()
    lease_h = mgr.create_inheritable_family_lease()
    try:
        # While lease_h is open, probe_family_quiescence must fail/timeout
        assert not mgr.probe_family_quiescence(timeout_s=0.2)
    finally:
        ctypes.windll.kernel32.CloseHandle(lease_h)
        # Now that lease handle is closed, probe_family_quiescence must succeed immediately
        assert mgr.probe_family_quiescence(timeout_s=1.0)
        mgr.release_all()
