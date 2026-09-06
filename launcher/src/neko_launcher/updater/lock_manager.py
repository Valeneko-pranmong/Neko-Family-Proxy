"""Root control lock and process family lease manager."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import time

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_ALWAYS = 4
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
LOCKFILE_EXCLUSIVE_LOCK = 0x00000002

ERROR_LOCK_VIOLATION = 33
ERROR_SHARING_VIOLATION = 32


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", wintypes.LPVOID),
        ("InternalHigh", wintypes.LPVOID),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_CreateFileW = ctypes.windll.kernel32.CreateFileW
_CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(SECURITY_ATTRIBUTES),
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_CreateFileW.restype = wintypes.HANDLE

_LockFileEx = ctypes.windll.kernel32.LockFileEx
_LockFileEx.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(OVERLAPPED),
]
_LockFileEx.restype = wintypes.BOOL

_CloseHandle = ctypes.windll.kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL


class LockBusyError(OSError):
    """Raised when the root control lock cannot be acquired within timeout."""


class RootLockManager:
    """Manages permanent control.lock and inheritable family.lease for process family tracking."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.state_dir = root_dir / "state"
        self.control_path = self.state_dir / "control.lock"
        self.lease_path = self.state_dir / "family.lease"
        self.control_handle: int | None = None
        self.lease_handle: int | None = None

    def acquire_control_lock(self, timeout_s: float = 10.0) -> int:
        """Acquire exclusive byte 0 lock on state/control.lock."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        abs_path = str(self.control_path.resolve())

        handle = _CreateFileW(
            abs_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,  # Deny share-delete
            None,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle == INVALID_HANDLE_VALUE or handle == 0:
            err = ctypes.GetLastError()
            raise LockBusyError(f"Failed to open control.lock at '{abs_path}' (WinError {err})")

        start_time = time.monotonic()
        overlapped = OVERLAPPED()
        overlapped.Offset = 0
        overlapped.OffsetHigh = 0

        while True:
            ok = _LockFileEx(
                handle,
                LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY,
                0,
                1,  # nNumberOfBytesToLockLow = 1 byte
                0,  # nNumberOfBytesToLockHigh = 0
                ctypes.byref(overlapped),
            )
            if ok:
                self.control_handle = int(handle)
                return self.control_handle

            err = ctypes.GetLastError()
            if err == ERROR_LOCK_VIOLATION:
                if time.monotonic() - start_time >= timeout_s:
                    _CloseHandle(handle)
                    raise LockBusyError(f"Control lock at '{abs_path}' is busy (timed out after {timeout_s}s)")
                time.sleep(0.05)
            else:
                _CloseHandle(handle)
                raise OSError(f"LockFileEx failed on '{abs_path}' (WinError {err})")

    def probe_family_quiescence(self, timeout_s: float = 30.0) -> bool:
        """Probe whether all prior descendant family lease handles have closed."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        abs_path = str(self.lease_path.resolve())
        start_time = time.monotonic()

        while True:
            # Attempt to open exclusively (dwShareMode = 0)
            h = _CreateFileW(
                abs_path,
                GENERIC_READ | GENERIC_WRITE,
                0,  # Exclusive share mode!
                None,
                OPEN_ALWAYS,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if h != INVALID_HANDLE_VALUE and h != 0:
                # Success! No prior family lease references exist
                _CloseHandle(h)
                return True

            err = ctypes.GetLastError()
            if err == ERROR_SHARING_VIOLATION:
                if time.monotonic() - start_time >= timeout_s:
                    return False
                time.sleep(0.05)
            else:
                raise OSError(f"Failed to probe family.lease at '{abs_path}' (WinError {err})")

    def create_inheritable_family_lease(self) -> int:
        """Open state/family.lease with FILE_SHARE_READ and bInheritHandle=True."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        abs_path = str(self.lease_path.resolve())

        sa = SECURITY_ATTRIBUTES()
        sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
        sa.lpSecurityDescriptor = None
        sa.bInheritHandle = True

        h = _CreateFileW(
            abs_path,
            GENERIC_READ,
            FILE_SHARE_READ,  # Only shared reads allowed
            ctypes.byref(sa),
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if h == INVALID_HANDLE_VALUE or h == 0:
            err = ctypes.GetLastError()
            raise OSError(f"Failed to open inheritable family.lease at '{abs_path}' (WinError {err})")

        self.lease_handle = int(h)
        return self.lease_handle

    def release_all(self) -> None:
        """Close held lock and lease handles."""
        if self.lease_handle is not None:
            _CloseHandle(wintypes.HANDLE(self.lease_handle))
            self.lease_handle = None
        if self.control_handle is not None:
            _CloseHandle(wintypes.HANDLE(self.control_handle))
            self.control_handle = None
