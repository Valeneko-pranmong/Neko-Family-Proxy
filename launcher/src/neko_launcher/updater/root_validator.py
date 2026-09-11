"""KnownFolder root and process elevation validator."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RootValidationResult:
    valid: bool
    error_code: str | None = None
    reason: str | None = None


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


# FOLDERID_UserProgramFiles = {5CD7AEE2-2219-4A67-B85D-6C9CE15660CB}
FOLDERID_UserProgramFiles = GUID(
    0x5CD7AEE2,
    0x2219,
    0x4A67,
    (ctypes.c_byte * 8)(0xB8, 0x5D, 0x6C, 0x9C, 0xE1, 0x56, 0x60, 0xCB),
)

TOKEN_QUERY = 0x0008
TokenElevation = 20


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


def get_expected_install_root() -> Path:
    """Retrieve the expected installation root under FOLDERID_UserProgramFiles."""
    path_ptr = wintypes.LPWSTR()
    hr = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(FOLDERID_UserProgramFiles),
        0,
        None,
        ctypes.byref(path_ptr),
    )
    if hr != 0 or not path_ptr.value:
        import os
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise OSError(f"SHGetKnownFolderPath failed with HRESULT {hr:#x} and no LOCALAPPDATA fallback")
        return Path(local_app_data) / "Programs" / "NEKO FAMILY"

    base_path = path_ptr.value
    ctypes.windll.ole32.CoTaskMemFree(path_ptr)
    return Path(base_path) / "NEKO FAMILY"


def is_process_elevated() -> bool:
    """Check if the current process token is elevated."""
    token_handle = wintypes.HANDLE()
    current_proc = ctypes.windll.kernel32.GetCurrentProcess()
    ok = ctypes.windll.advapi32.OpenProcessToken(current_proc, TOKEN_QUERY, ctypes.byref(token_handle))
    if not ok:
        return False

    try:
        elevation = TOKEN_ELEVATION()
        ret_len = wintypes.DWORD()
        ok_info = ctypes.windll.advapi32.GetTokenInformation(
            token_handle,
            TokenElevation,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(ret_len),
        )
        if not ok_info:
            return False
        return elevation.TokenIsElevated != 0
    finally:
        ctypes.windll.kernel32.CloseHandle(token_handle)


def validate_install_root(path: Path) -> RootValidationResult:
    """Validate that path conforms to the unelevated NTFS KnownFolder install root requirements."""
    if is_process_elevated():
        return RootValidationResult(
            valid=False,
            error_code="ELEVATION_UNSUPPORTED",
            reason="Elevated process tokens are rejected",
        )

    expected = get_expected_install_root()
    if path.resolve() != expected.resolve():
        return RootValidationResult(
            valid=False,
            error_code="ROOT_UNSUPPORTED",
            reason=f"Path '{path}' does not match expected KnownFolder '{expected}'",
        )

    # Check volume information for NTFS
    volume_root = f"{path.drive}\\" if path.drive else None
    if volume_root:
        fs_buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            volume_root,
            None,
            0,
            None,
            None,
            None,
            fs_buf,
            ctypes.sizeof(fs_buf) // 2,
        )
        if not ok or fs_buf.value != "NTFS":
            fs_name = fs_buf.value if ok else "UNKNOWN"
            return RootValidationResult(
                valid=False,
                error_code="ROOT_UNSUPPORTED",
                reason=f"Volume filesystem '{fs_name}' must be NTFS",
            )

    return RootValidationResult(valid=True)
