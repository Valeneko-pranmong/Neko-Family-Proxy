import ctypes
import sys

_INSTANCE_MUTEX_NAME = "Local\\NekoFamilyProxyLauncher"
_ERROR_ALREADY_EXISTS = 183


def acquire_instance_mutex(name: str = _INSTANCE_MUTEX_NAME) -> int | None:
    """Hold a named Windows mutex for the lifetime of the launcher."""
    if sys.platform != "win32":
        return -1
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def release_instance_mutex(handle: int) -> None:
    if sys.platform == "win32" and handle != -1:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        kernel32.CloseHandle(handle)


def show_already_running_message() -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(
            None,
            "Neko Launcher เปิดอยู่แล้ว กรุณาใช้หน้าต่างเดิม",
            "Neko Launcher",
            0x40,
        )
