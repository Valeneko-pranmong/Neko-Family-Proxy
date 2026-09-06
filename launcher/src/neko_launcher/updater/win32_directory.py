"""Win32 DirectoryIdentity and handle-safe directory operations."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from neko_launcher.updater.state_models import DirectoryIdentity

GENERIC_READ = 0x80000000
FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

FileIdInfo = 18


class FILE_ID_128(ctypes.Structure):
    _fields_ = [("Identifier", ctypes.c_ubyte * 16)]


class FILE_ID_INFO(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_ulonglong),
        ("FileId", FILE_ID_128),
    ]


_CreateFileW = ctypes.windll.kernel32.CreateFileW
_CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_CreateFileW.restype = wintypes.HANDLE

_GetFileInformationByHandleEx = ctypes.windll.kernel32.GetFileInformationByHandleEx
_GetFileInformationByHandleEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
]
_GetFileInformationByHandleEx.restype = wintypes.BOOL

_CloseHandle = ctypes.windll.kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL


def open_directory_guarded(path: Path) -> int:
    """Open a directory with FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, denying delete/rename sharing."""
    abs_path = str(path.resolve())
    handle = _CreateFileW(
        abs_path,
        GENERIC_READ | FILE_LIST_DIRECTORY,
        FILE_SHARE_READ | FILE_SHARE_WRITE,  # Denies FILE_SHARE_DELETE
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle == 0:
        err = ctypes.GetLastError()
        raise OSError(f"Failed to open directory '{abs_path}' (WinError {err})")
    return int(handle)


def get_directory_identity(dir_handle: int) -> DirectoryIdentity:
    """Retrieve 64-bit volume serial, 128-bit file ID, and parent file ID from directory handle."""
    info = FILE_ID_INFO()
    ok = _GetFileInformationByHandleEx(
        wintypes.HANDLE(dir_handle),
        FileIdInfo,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        err = ctypes.GetLastError()
        raise OSError(f"GetFileInformationByHandleEx failed (WinError {err})")

    vol_hex = f"{info.VolumeSerialNumber:016x}"
    file_id_bytes = bytes(info.FileId.Identifier)
    file_id_hex = file_id_bytes.hex()

    # Query parent file ID if possible by getting final path name or default to zeros
    parent_file_id_hex = "0" * 32
    buffer_len = 1024
    path_buf = ctypes.create_unicode_buffer(buffer_len)
    _GetFinalPathNameByHandleW = getattr(ctypes.windll.kernel32, "GetFinalPathNameByHandleW", None)
    if _GetFinalPathNameByHandleW is not None:
        _GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        _GetFinalPathNameByHandleW.restype = wintypes.DWORD
        ret_len = _GetFinalPathNameByHandleW(wintypes.HANDLE(dir_handle), path_buf, buffer_len, 0)
        if 0 < ret_len < buffer_len:
            final_path = path_buf.value
            if final_path.startswith("\\\\?\\"):
                final_path = final_path[4:]
            parent_path = Path(final_path).parent
            if parent_path.exists():
                try:
                    p_handle = open_directory_guarded(parent_path)
                    try:
                        p_info = FILE_ID_INFO()
                        if _GetFileInformationByHandleEx(
                            wintypes.HANDLE(p_handle), FileIdInfo, ctypes.byref(p_info), ctypes.sizeof(p_info)
                        ):
                            parent_file_id_hex = bytes(p_info.FileId.Identifier).hex()
                    finally:
                        _CloseHandle(wintypes.HANDLE(p_handle))
                except Exception:
                    pass

    return DirectoryIdentity(
        volume_serial=vol_hex,
        file_id=file_id_hex,
        parent_file_id=parent_file_id_hex,
    )


def create_incoming_container(root_dir: Path, request_id: str) -> tuple[int, DirectoryIdentity, Path]:
    """Exclusively create incoming/<request-id> directory and return (handle, identity, path)."""
    incoming_parent = root_dir / "incoming"
    incoming_parent.mkdir(parents=True, exist_ok=True)
    container_dir = incoming_parent / request_id
    container_dir.mkdir(parents=False, exist_ok=False)  # Exclusive create!

    handle = open_directory_guarded(container_dir)
    try:
        identity = get_directory_identity(handle)
        return handle, identity, container_dir
    except Exception:
        _CloseHandle(wintypes.HANDLE(handle))
        raise
