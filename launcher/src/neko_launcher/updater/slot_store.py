import ctypes
import ctypes.wintypes
import pathlib
from typing import Mapping

from neko_launcher.updater.binary_frame import (
    SLOT_FRAME_SIZE,
    SlotFrame,
    pack_slot_frame,
    unpack_slot_frame,
)
from neko_launcher.updater.slot_selector import (
    SelectionResult,
    SelectionStatus,
    select_active_slot,
)
from neko_launcher.updater.state_machine import StateTransitionError, validate_transition
from neko_launcher.updater.state_models import State, deserialize_state, serialize_state


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_SPARSE_FILE = 0x00000200
FILE_ATTRIBUTE_ENCRYPTED = 0x00004000
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

FORBIDDEN_ATTRIBUTES = (
    FILE_ATTRIBUTE_REPARSE_POINT
    | FILE_ATTRIBUTE_SPARSE_FILE
    | FILE_ATTRIBUTE_ENCRYPTED
    | FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

FileStreamInfo = 7
FINAL_PATH_BUFFER_CHARS = 32768


class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", ctypes.wintypes.DWORD),
        ("ftCreationTime", ctypes.wintypes.FILETIME),
        ("ftLastAccessTime", ctypes.wintypes.FILETIME),
        ("ftLastWriteTime", ctypes.wintypes.FILETIME),
        ("dwVolumeSerialNumber", ctypes.wintypes.DWORD),
        ("nFileSizeHigh", ctypes.wintypes.DWORD),
        ("nFileSizeLow", ctypes.wintypes.DWORD),
        ("nNumberOfLinks", ctypes.wintypes.DWORD),
        ("nFileIndexHigh", ctypes.wintypes.DWORD),
        ("nFileIndexLow", ctypes.wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateFileW.argtypes = [
    ctypes.c_wchar_p,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
    ctypes.c_void_p,
]
kernel32.CreateFileW.restype = ctypes.c_void_p

kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.wintypes.BOOL

kernel32.GetFileSizeEx.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.wintypes.LARGE_INTEGER),
]
kernel32.GetFileSizeEx.restype = ctypes.wintypes.BOOL

kernel32.FlushFileBuffers.argtypes = [ctypes.c_void_p]
kernel32.FlushFileBuffers.restype = ctypes.wintypes.BOOL

kernel32.SetFilePointerEx.argtypes = [
    ctypes.c_void_p,
    ctypes.wintypes.LARGE_INTEGER,
    ctypes.POINTER(ctypes.wintypes.LARGE_INTEGER),
    ctypes.wintypes.DWORD,
]
kernel32.SetFilePointerEx.restype = ctypes.wintypes.BOOL

kernel32.ReadFile.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD),
    ctypes.c_void_p,
]
kernel32.ReadFile.restype = ctypes.wintypes.BOOL

kernel32.WriteFile.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.DWORD),
    ctypes.c_void_p,
]
kernel32.WriteFile.restype = ctypes.wintypes.BOOL

kernel32.GetFileInformationByHandle.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
]
kernel32.GetFileInformationByHandle.restype = ctypes.wintypes.BOOL

kernel32.GetFileInformationByHandleEx.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.wintypes.DWORD,
]
kernel32.GetFileInformationByHandleEx.restype = ctypes.wintypes.BOOL

kernel32.GetFinalPathNameByHandleW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
]
kernel32.GetFinalPathNameByHandleW.restype = ctypes.wintypes.DWORD


def _is_invalid(h: int | None) -> bool:
    return h is None or h == 0 or h == -1 or h == 0xFFFFFFFF or h == 0xFFFFFFFFFFFFFFFF


def _close_handle(handle: int | None) -> None:
    if handle is not None and not _is_invalid(handle):
        kernel32.CloseHandle(handle)


def _get_file_size(handle: int) -> int:
    size = ctypes.wintypes.LARGE_INTEGER()
    if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
        raise OSError(ctypes.get_last_error(), "GetFileSizeEx failed")
    return size.value


def _flush_handle(handle: int) -> None:
    if not kernel32.FlushFileBuffers(handle):
        raise OSError(ctypes.get_last_error(), "FlushFileBuffers failed")


def _read_exact_at_zero(handle: int, size: int) -> bytes:
    if not kernel32.SetFilePointerEx(handle, ctypes.wintypes.LARGE_INTEGER(0), None, 0):
        raise OSError(ctypes.get_last_error(), "SetFilePointerEx failed")

    buf = ctypes.create_string_buffer(size)
    total = 0
    bytes_read = ctypes.wintypes.DWORD(0)
    while total < size:
        chunk_size = min(size - total, 0xFFFFFFFF)
        bytes_read.value = 0
        if not kernel32.ReadFile(
            handle,
            ctypes.byref(buf, total),
            chunk_size,
            ctypes.byref(bytes_read),
            None,
        ):
            raise OSError(ctypes.get_last_error(), "ReadFile failed")
        if bytes_read.value == 0:
            break
        total += bytes_read.value
    if total != size:
        raise OSError(0, "ReadFile failed")
    return buf.raw[:size]


def _write_all_at_zero(handle: int, data: bytes) -> None:
    if not kernel32.SetFilePointerEx(handle, ctypes.wintypes.LARGE_INTEGER(0), None, 0):
        raise OSError(ctypes.get_last_error(), "SetFilePointerEx failed")

    size = len(data)
    buf = ctypes.create_string_buffer(data, size)
    total = 0
    bytes_written = ctypes.wintypes.DWORD(0)
    while total < size:
        chunk_size = min(size - total, 0xFFFFFFFF)
        bytes_written.value = 0
        if not kernel32.WriteFile(
            handle,
            ctypes.byref(buf, total),
            chunk_size,
            ctypes.byref(bytes_written),
            None,
        ):
            raise OSError(ctypes.get_last_error(), "WriteFile failed")
        if bytes_written.value == 0:
            raise OSError(0, "WriteFile stalled")
        total += bytes_written.value


def _normalize_final_path(path: str) -> str:
    norm = path
    if norm.startswith(("\\\\?\\UNC\\", "\\\\?\\unc\\")):
        norm = "\\\\" + norm[8:]
    elif norm.startswith(("\\\\?\\", "\\\\?\\")):
        norm = norm[4:]
    if len(norm) == 3 and norm[1] == ":" and norm[2] == "\\":
        pass
    else:
        norm = norm.rstrip("\\")
    return norm.casefold()


def _get_final_path(handle: int) -> str:
    buf = ctypes.create_unicode_buffer(FINAL_PATH_BUFFER_CHARS)
    res = kernel32.GetFinalPathNameByHandleW(handle, buf, FINAL_PATH_BUFFER_CHARS, 0)
    if res == 0 or res >= FINAL_PATH_BUFFER_CHARS:
        raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    return _normalize_final_path(buf.value)


def _open_state_dir_guard(state_dir: pathlib.Path | str) -> int:
    h = kernel32.CreateFileW(
        str(state_dir),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if _is_invalid(h):
        err = ctypes.get_last_error()
        if err in (2, 3):
            raise FileNotFoundError(err, "CreateFileW missing")
        raise OSError(err, "CreateFileW failed")

    info = BY_HANDLE_FILE_INFORMATION()
    if not kernel32.GetFileInformationByHandle(h, ctypes.byref(info)):
        _close_handle(h)
        raise OSError(ctypes.get_last_error(), "GetFileInformationByHandle failed")

    attrs = info.dwFileAttributes
    if not (attrs & FILE_ATTRIBUTE_DIRECTORY):
        _close_handle(h)
        raise OSError(0, "Not a directory")

    if attrs & FORBIDDEN_ATTRIBUTES:
        _close_handle(h)
        raise OSError(0, "Directory has forbidden attributes")

    return h


def _open_existing_slot(path: str | pathlib.Path) -> int:
    h = kernel32.CreateFileW(
        str(path),
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        0x80 | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if _is_invalid(h):
        err = ctypes.get_last_error()
        if err in (2, 3):
            raise FileNotFoundError(err, "CreateFileW missing")
        raise OSError(err, "CreateFileW failed")
    return h


def _validate_trusted_leaf(handle: int, expected_parent_handle: int | None = None) -> None:
    info = BY_HANDLE_FILE_INFORMATION()
    if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "GetFileInformationByHandle failed")

    attrs = info.dwFileAttributes
    if attrs & FILE_ATTRIBUTE_DIRECTORY:
        raise OSError(0, "Is directory")

    if attrs & FORBIDDEN_ATTRIBUTES:
        raise OSError(0, "File has forbidden attributes")

    if info.nNumberOfLinks != 1:
        raise OSError(0, "Link count != 1")

    buf = ctypes.create_string_buffer(65536)
    if not kernel32.GetFileInformationByHandleEx(handle, FileStreamInfo, buf, ctypes.sizeof(buf)):
        raise OSError(ctypes.get_last_error(), "GetFileInformationByHandleEx failed")

    offset = 0
    stream_count = 0
    buf_len = len(buf)
    while True:
        if offset + 24 > buf_len:
            raise OSError(0, "Stream info out of bounds")
        next_entry = int.from_bytes(buf[offset : offset + 4], byteorder="little")
        name_len = int.from_bytes(buf[offset + 4 : offset + 8], byteorder="little")
        if name_len % 2 != 0:
            raise OSError(0, "Invalid stream name length")
        if offset + 24 + name_len > buf_len:
            raise OSError(0, "Stream info out of bounds")
        name = buf.raw[offset + 24 : offset + 24 + name_len].decode("utf-16le")
        if name != "::$DATA":
            raise OSError(0, "Alternate data stream detected")
        stream_count += 1
        if next_entry == 0:
            break
        if next_entry < 24 or offset + next_entry >= buf_len:
            raise OSError(0, "Invalid stream info next entry")
        offset += next_entry

    if stream_count < 1:
        raise OSError(0, "No streams found")

    if expected_parent_handle is not None:
        parent_info = BY_HANDLE_FILE_INFORMATION()
        if not kernel32.GetFileInformationByHandle(expected_parent_handle, ctypes.byref(parent_info)):
            raise OSError(ctypes.get_last_error(), "GetFileInformationByHandle parent failed")

        if info.dwVolumeSerialNumber != parent_info.dwVolumeSerialNumber:
            raise OSError(0, "Volume mismatch")

        child_path = _get_final_path(handle)
        parent_path = _get_final_path(expected_parent_handle)

        if "\\" not in child_path:
            raise OSError(0, "Invalid child path format")

        child_parent = _normalize_final_path(str(pathlib.PureWindowsPath(child_path).parent))
        if child_parent != parent_path:
            raise OSError(0, "Parent path mismatch")


class SlotStoreError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SlotStore:
    def __init__(
        self,
        slot_a: pathlib.Path | str,
        slot_b: pathlib.Path | str,
        public_keys: Mapping[str, bytes],
    ):
        self.public_keys = dict(public_keys)
        self.parent_guard: int | None = None
        self.handle_a: int | None = None
        self.handle_b: int | None = None
        self.slot_a_present = False
        self.slot_b_present = False

        state_dir = pathlib.Path(slot_a).parent

        try:
            self.parent_guard = _open_state_dir_guard(state_dir)

            try:
                self.handle_a = _open_existing_slot(slot_a)
                _validate_trusted_leaf(self.handle_a, self.parent_guard)
                if _get_file_size(self.handle_a) != SLOT_FRAME_SIZE:
                    raise SlotStoreError("STATE_CORRUPT")
                self.slot_a_present = True
            except FileNotFoundError:
                pass

            try:
                self.handle_b = _open_existing_slot(slot_b)
                _validate_trusted_leaf(self.handle_b, self.parent_guard)
                if _get_file_size(self.handle_b) != SLOT_FRAME_SIZE:
                    raise SlotStoreError("STATE_CORRUPT")
                self.slot_b_present = True
            except FileNotFoundError:
                pass

        except OSError:
            self.close()
            raise SlotStoreError("IO_FAILED")
        except SlotStoreError:
            self.close()
            raise

    def close(self) -> None:
        if self.handle_a is not None:
            _close_handle(self.handle_a)
            self.handle_a = None
        if self.handle_b is not None:
            _close_handle(self.handle_b)
            self.handle_b = None
        if self.parent_guard is not None:
            _close_handle(self.parent_guard)
            self.parent_guard = None

    @property
    def slot_a_individually_valid(self) -> bool:
        if not self.slot_a_present or self.handle_a is None:
            return False
        try:
            data = _read_exact_at_zero(self.handle_a, SLOT_FRAME_SIZE)
            res = select_active_slot(data, None, self.public_keys)
            return res.status == SelectionStatus.SELECTED
        except (OSError, ValueError, SlotStoreError):
            return False

    @property
    def slot_b_individually_valid(self) -> bool:
        if not self.slot_b_present or self.handle_b is None:
            return False
        try:
            data = _read_exact_at_zero(self.handle_b, SLOT_FRAME_SIZE)
            res = select_active_slot(None, data, self.public_keys)
            return res.status == SelectionStatus.SELECTED
        except (OSError, ValueError, SlotStoreError):
            return False

    def load(self) -> SelectionResult:
        data_a = None
        data_b = None
        try:
            if self.slot_a_present and self.handle_a is not None:
                data_a = _read_exact_at_zero(self.handle_a, SLOT_FRAME_SIZE)
            if self.slot_b_present and self.handle_b is not None:
                data_b = _read_exact_at_zero(self.handle_b, SLOT_FRAME_SIZE)
        except OSError:
            raise SlotStoreError("IO_FAILED")

        return select_active_slot(data_a, data_b, self.public_keys)

    def write_state(self, new_state: State) -> SelectionResult:
        result = self.load()
        if result.status != SelectionStatus.SELECTED or result.state is None:
            raise SlotStoreError("REPAIR_REQUIRED")
        if result.active_slot not in {"a", "b"}:
            raise SlotStoreError("PROTOCOL_INVALID")

        if new_state.revision != result.state.revision + 1:
            raise SlotStoreError("PROTOCOL_INVALID")

        try:
            validate_transition(result.state, new_state)
        except StateTransitionError:
            raise SlotStoreError("PROTOCOL_INVALID")

        target_slot = "b" if result.active_slot == "a" else "a"
        target_handle = self.handle_b if target_slot == "b" else self.handle_a

        if target_handle is None:
            raise SlotStoreError("REPAIR_REQUIRED")

        try:
            frame_bytes = serialize_state(new_state)
            slot_frame = SlotFrame(
                revision=new_state.revision,
                format_version=1,
                body_bytes=frame_bytes,
            )
            raw = pack_slot_frame(slot_frame)
        except ValueError:
            raise SlotStoreError("STATE_CORRUPT")

        try:
            _write_all_at_zero(target_handle, raw)
        except OSError:
            raise SlotStoreError("IO_FAILED")

        try:
            _flush_handle(target_handle)
        except OSError:
            raise SlotStoreError("FLUSH_FAILED")

        try:
            reread = _read_exact_at_zero(target_handle, SLOT_FRAME_SIZE)
        except OSError:
            raise SlotStoreError("IO_FAILED")

        if reread != raw:
            raise SlotStoreError("STATE_CORRUPT")

        try:
            unpacked = unpack_slot_frame(reread)
            deserialized_state = deserialize_state(unpacked.body_bytes)
        except ValueError:
            raise SlotStoreError("STATE_CORRUPT")

        if unpacked.revision != new_state.revision:
            raise SlotStoreError("STATE_CORRUPT")

        if deserialized_state != new_state:
            raise SlotStoreError("STATE_CORRUPT")

        new_result = self.load()
        if (
            new_result.status != SelectionStatus.SELECTED
            or new_result.active_slot != target_slot
            or new_result.state != new_state
        ):
            raise SlotStoreError("REPAIR_REQUIRED")

        return new_result
