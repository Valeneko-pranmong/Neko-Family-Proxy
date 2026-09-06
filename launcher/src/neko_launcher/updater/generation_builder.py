"""Build a complete, verified immutable release generation in owned staging."""
from __future__ import annotations

import base64
import binascii
import contextlib
import ctypes
import io
import msvcrt
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
from typing import Mapping

from neko_launcher.updater.canonical_json import canonical_json_loads
from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle
from neko_launcher.updater.manifest_v2 import ReleaseSetV2, verify_release_envelope_v2
from neko_launcher.updater.state_models import Generation, State
from neko_launcher.updater.win32_directory import get_directory_identity, open_directory_guarded
from neko_launcher.updater.zip_extractor import extract_core_bundle

_PROHIBITED_ATTRIBUTES = (
    0x2 |          # FILE_ATTRIBUTE_HIDDEN
    0x200 |        # FILE_ATTRIBUTE_SPARSE_FILE
    0x1000 |       # FILE_ATTRIBUTE_OFFLINE
    0x4000 |       # FILE_ATTRIBUTE_ENCRYPTED
    0x00400000 |   # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
    0x00040000 |   # FILE_ATTRIBUTE_RECALL_ON_OPEN
    0x00080000 |   # FILE_ATTRIBUTE_PINNED
    0x00100000     # FILE_ATTRIBUTE_UNPINNED
)


def _has_ads_by_handle(handle: int) -> bool:
    import struct
    GetFileInformationByHandleEx = ctypes.windll.kernel32.GetFileInformationByHandleEx
    GetFileInformationByHandleEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    GetFileInformationByHandleEx.restype = ctypes.c_int

    buf_size = 65536
    buf = ctypes.create_string_buffer(buf_size)
    FileStreamInfo = 7

    if not GetFileInformationByHandleEx(handle, FileStreamInfo, buf, buf_size):
        err = ctypes.GetLastError()
        if err == 38: # ERROR_HANDLE_EOF
            return False
        raise OSError()

    offset = 0
    raw_bytes = buf.raw
    has_alternate = False

    while True:
        if offset < 0 or offset + 24 > buf_size:
            raise OSError()
        try:
            next_entry_offset, name_length, _, _ = struct.unpack_from("<IIqq", raw_bytes, offset)
        except struct.error:
            raise OSError()

        if name_length < 0 or offset + 24 + name_length > buf_size:
            raise OSError()

        try:
            name_bytes = raw_bytes[offset + 24 : offset + 24 + name_length]
            name = name_bytes.decode("utf-16le")
        except UnicodeDecodeError:
            raise OSError()

        if name != "::$DATA":
            has_alternate = True
            break

        if next_entry_offset == 0:
            break

        if next_entry_offset < 24 or offset + next_entry_offset > buf_size:
            raise OSError()

        offset += next_entry_offset

    return has_alternate

@contextlib.contextmanager
def _open_incoming_guarded(path: Path):
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 1
    OPEN_EXISTING = 3
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

    CreateFileW = ctypes.windll.kernel32.CreateFileW
    CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    CreateFileW.restype = ctypes.c_void_p

    handle = CreateFileW(str(path), GENERIC_READ, FILE_SHARE_READ, None, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, None)
    if not handle or handle == -1 or handle == 0xffffffffffffffff:
        err = ctypes.GetLastError()
        if err in (2, 3):
            _fail("ARTIFACT_MISSING")
        _fail("PATH_REJECTED")

    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except Exception:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        _fail("PATH_REJECTED")

    f = None
    try:
        f = os.fdopen(fd, "rb")
        yield f
    finally:
        if f is not None:
            f.close()
        else:
            os.close(fd)

@contextlib.contextmanager
def _open_final_guarded(path: Path):
    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 1
    OPEN_EXISTING = 3
    FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000

    CreateFileW = ctypes.windll.kernel32.CreateFileW
    CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    CreateFileW.restype = ctypes.c_void_p

    handle = CreateFileW(str(path), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, None, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, None)
    if not handle or handle == -1 or handle == 0xffffffffffffffff:
        err = ctypes.GetLastError()
        if err in (2, 3):
            _fail("ARTIFACT_MISSING")
        _fail("PATH_REJECTED")

    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR)
    except Exception:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        _fail("PATH_REJECTED")

    f = None
    try:
        f = os.fdopen(fd, "r+b")
        yield f
    finally:
        if f is not None:
            f.close()
        else:
            os.close(fd)

def _verify_guarded_stream(f: io.BufferedReader, expected_size: int, expected_sha: str) -> None:
    try:
        fd = f.fileno()
        st = os.fstat(fd)
        if st.st_file_attributes & _REPARSE_ATTRIBUTE:
            _fail("REPARSE_REJECTED")
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            _fail("LINK_OR_ADS_REJECTED")
        if st.st_file_attributes & _PROHIBITED_ATTRIBUTES:
            _fail("LINK_OR_ADS_REJECTED")

        handle = msvcrt.get_osfhandle(fd)
        if _has_ads_by_handle(handle):
            _fail("LINK_OR_ADS_REJECTED")

        if st.st_size != expected_size:
            _fail("SIZE_MISMATCH")

        f.seek(0)
        digest = hashlib.sha256(f.read()).hexdigest()
        if digest != expected_sha:
            _fail("HASH_MISMATCH")

        f.seek(0)
    except GenerationBuildError:
        raise
    except OSError:
        _fail("IO_FAILED")

class _WIN32_FIND_STREAM_DATA(ctypes.Structure):
    _fields_ = [
        ("StreamSize", ctypes.c_longlong),
        ("cStreamName", ctypes.c_wchar * 296)
    ]

def _has_ads(path: Path) -> bool:
    FindFirstStreamW = ctypes.windll.kernel32.FindFirstStreamW
    FindFirstStreamW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(_WIN32_FIND_STREAM_DATA), ctypes.c_uint32]
    FindFirstStreamW.restype = ctypes.c_void_p

    FindNextStreamW = ctypes.windll.kernel32.FindNextStreamW
    FindNextStreamW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WIN32_FIND_STREAM_DATA)]
    FindNextStreamW.restype = ctypes.c_int

    FindClose = ctypes.windll.kernel32.FindClose
    FindClose.argtypes = [ctypes.c_void_p]
    FindClose.restype = ctypes.c_int

    data = _WIN32_FIND_STREAM_DATA()
    handle = FindFirstStreamW(str(path), 0, ctypes.byref(data), 0)
    # -1 is INVALID_HANDLE_VALUE, which in 64-bit c_void_p is often just None or 0xffffffffffffffff
    if not handle or handle == -1 or handle == 0xffffffffffffffff:
        if ctypes.GetLastError() == 38:
            return False
        raise OSError()

    has_alternate = False
    try:
        while True:
            if data.cStreamName != "::$DATA":
                has_alternate = True
                break
            if not FindNextStreamW(handle, ctypes.byref(data)):
                if ctypes.GetLastError() == 38:
                    break
                raise OSError()
    finally:
        FindClose(handle)
    return has_alternate

_REPARSE_ATTRIBUTE = stat.FILE_ATTRIBUTE_REPARSE_POINT


class GenerationBuildError(RuntimeError):
    """Safe closed-code failure from generation construction."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class GenerationBuildResult:
    changed: dict[str, bool]
    generation_id: str
    generation_dir: Path
    generation: Generation


def _fail(code: str) -> None:
    raise GenerationBuildError(code) from None


def _flush_file(path: Path) -> None:
    """Flush one completed regular file through the narrow OS boundary."""
    try:
        attrs = path.stat(follow_symlinks=False).st_file_attributes
        if attrs & _PROHIBITED_ATTRIBUTES:
            _fail("LINK_OR_ADS_REJECTED")
        if _has_ads(path):
            _fail("LINK_OR_ADS_REJECTED")
    except OSError:
        _fail("IO_FAILED")
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _is_reparse(path: Path) -> bool:
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & _REPARSE_ATTRIBUTE)
    except OSError:
        return False


def _decode_evidence(encoded: str) -> bytes:
    try:
        raw = base64.b64decode(encoded, validate=True)
        if base64.b64encode(raw).decode("ascii") != encoded:
            _fail("SCHEMA_INVALID")
        return raw
    except (binascii.Error, ValueError, TypeError):
        _fail("SCHEMA_INVALID")


def _authenticate_envelope(
    raw: bytes,
    public_keys: Mapping[str, bytes],
) -> tuple[ReleaseSetV2, str]:
    try:
        document = canonical_json_loads(raw)
        release, payload_sha = verify_release_envelope_v2(document, public_keys)
        return release, payload_sha
    except GenerationBuildError:
        raise
    except ValueError as error:
        message = str(error)
        if message.startswith("Unknown key_id:"):
            _fail("UNKNOWN_KEY")
        if message == "Invalid signature":
            _fail("SIGNATURE_INVALID")
        _fail("SCHEMA_INVALID")


def _matches_generation(release: ReleaseSetV2, payload_sha: str, generation: Generation) -> bool:
    return (
        payload_sha == generation.binding.payload_sha256
        and release.release_sequence == generation.binding.release_sequence
        and release.release_id == generation.binding.release_id
        and release.components["launcher"].installed_identity_sha256
        == generation.launcher_identity_sha256
        and release.components["core"].installed_identity_sha256
        == generation.core_identity_sha256
    )


def _validate_authority(
    state: State,
    public_keys: Mapping[str, bytes],
) -> tuple[ReleaseSetV2, bytes, ReleaseSetV2]:
    transaction = state.transaction
    if (
        state.phase != "PREPARING"
        or transaction is None
        or transaction.stage != "BUILDING"
        or transaction.staging is None
        or transaction.mutation is None
        or transaction.mutation.kind != "WRITE_CANDIDATE"
        or transaction.mutation.target != "stage"
        or transaction.mutation.status != "INTENT"
    ):
        _fail("PROTOCOL_INVALID")

    old = transaction.old
    candidate = transaction.candidate
    if (
        state.committed is None
        or old is None
        or old != state.committed
        or state.observed != candidate.binding
    ):
        _fail("STATE_CORRUPT")

    if not (state.committed.binding.release_sequence <= state.highwater.release_sequence <= state.observed.release_sequence):
        _fail("STATE_CORRUPT")

    if candidate.binding.release_sequence <= state.highwater.release_sequence:
        _fail("STATE_CORRUPT")

    required = {
        state.committed.binding.payload_sha256,
        state.highwater.payload_sha256,
        state.observed.payload_sha256,
        old.binding.payload_sha256,
        candidate.binding.payload_sha256,
    }
    if state.previous is not None:
        if state.previous.binding.payload_sha256 == state.committed.binding.payload_sha256:
            _fail("STATE_CORRUPT")
        required.add(state.previous.binding.payload_sha256)

    if set(state.evidence) != required:
        _fail("STATE_CORRUPT")

    authenticated: dict[str, tuple[ReleaseSetV2, str, bytes]] = {}
    for evidence_key, encoded in state.evidence.items():
        raw = _decode_evidence(encoded)
        release, payload_sha = _authenticate_envelope(raw, public_keys)
        if payload_sha != evidence_key:
            _fail("STATE_CORRUPT")
        authenticated[evidence_key] = (release, payload_sha, raw)

    old_release, old_sha, _ = authenticated[old.binding.payload_sha256]
    candidate_release, candidate_sha, candidate_raw = authenticated[
        candidate.binding.payload_sha256
    ]
    if not _matches_generation(old_release, old_sha, old):
        _fail("STATE_CORRUPT")
    if not _matches_generation(candidate_release, candidate_sha, candidate):
        _fail("STATE_CORRUPT")
    if state.previous is not None:
        prev_release, prev_sha, _ = authenticated[state.previous.binding.payload_sha256]
        if not _matches_generation(prev_release, prev_sha, state.previous):
            _fail("STATE_CORRUPT")
    if not (
        candidate_release.updater_protocol.minimum
        <= state.helper_protocol
        <= candidate_release.updater_protocol.maximum
    ):
        _fail("PROTOCOL_UNSUPPORTED")
    return candidate_release, candidate_raw, old_release


def _validate_owned_directory(path: Path, expected: object) -> int:
    if _is_reparse(path):
        _fail("REPARSE_REJECTED")
    try:
        handle = open_directory_guarded(path)
    except OSError:
        _fail("PATH_REJECTED")
    try:
        actual = get_directory_identity(handle)
        if actual != expected:
            _fail("PATH_REJECTED")
        return handle
    except OSError:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        _fail("PATH_REJECTED")
    except Exception:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise


def _validate_source_file(path: Path) -> None:
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        _fail("ARTIFACT_MISSING")
    except OSError:
        _fail("PATH_REJECTED")
    if _is_reparse(path):
        _fail("REPARSE_REJECTED")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail("LINK_OR_ADS_REJECTED")
    if info.st_file_attributes & _PROHIBITED_ATTRIBUTES:
        _fail("LINK_OR_ADS_REJECTED")
    try:
        has_ads = _has_ads(path)
    except OSError:
        _fail("IO_FAILED")
    if has_ads:
        _fail("LINK_OR_ADS_REJECTED")

def _guard_old_core(old_core_path: Path, stack: contextlib.ExitStack) -> tuple[dict, dict]:
    dir_identities = {}
    file_objects = {}

    def _scan_dir(current_dir: Path):
        if _is_reparse(current_dir):
            _fail("REPARSE_REJECTED")

        try:
            d_handle = open_directory_guarded(current_dir)
        except OSError:
            _fail("PATH_REJECTED")

        stack.callback(ctypes.windll.kernel32.CloseHandle, ctypes.c_void_p(d_handle))

        try:
            identity = get_directory_identity(d_handle)
        except OSError:
            _fail("PATH_REJECTED")

        dir_identities[current_dir] = identity

        try:
            entries = list(current_dir.iterdir())
        except OSError:
            _fail("PATH_REJECTED")

        for entry in entries:
            if _is_reparse(entry):
                _fail("REPARSE_REJECTED")
            if entry.is_dir():
                _scan_dir(entry)
            elif entry.is_file():
                _validate_source_file(entry)

                f = stack.enter_context(_open_incoming_guarded(entry))
                try:
                    fd = f.fileno()
                    st = os.fstat(fd)
                    if st.st_file_attributes & _REPARSE_ATTRIBUTE:
                        _fail("REPARSE_REJECTED")
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                        _fail("LINK_OR_ADS_REJECTED")
                    if st.st_file_attributes & _PROHIBITED_ATTRIBUTES:
                        _fail("LINK_OR_ADS_REJECTED")
                    handle = msvcrt.get_osfhandle(fd)
                    if _has_ads_by_handle(handle):
                        _fail("LINK_OR_ADS_REJECTED")
                except GenerationBuildError:
                    raise
                except OSError:
                    _fail("IO_FAILED")

                file_objects[entry] = (f, st.st_dev, st.st_ino)
            else:
                _fail("PATH_REJECTED")

    _scan_dir(old_core_path)
    return dir_identities, file_objects

def _verify_old_core_inventory_second_pass(old_core_path: Path, dir_identities: dict, file_objects: dict):
    seen_dirs = set()
    seen_files = set()

    def _scan_dir_again(current_dir: Path):
        if _is_reparse(current_dir):
            _fail("REPARSE_REJECTED")

        try:
            d_handle = open_directory_guarded(current_dir)
        except OSError:
            _fail("PATH_REJECTED")

        try:
            identity = get_directory_identity(d_handle)
        except OSError:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(d_handle))
            _fail("PATH_REJECTED")

        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(d_handle))

        if current_dir not in dir_identities or dir_identities[current_dir] != identity:
            _fail("PATH_REJECTED")

        seen_dirs.add(current_dir)

        try:
            entries = list(current_dir.iterdir())
        except OSError:
            _fail("PATH_REJECTED")

        for entry in entries:
            if _is_reparse(entry):
                _fail("REPARSE_REJECTED")
            if entry.is_dir():
                _scan_dir_again(entry)
            elif entry.is_file():
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    _fail("PATH_REJECTED")

                if entry not in file_objects:
                    _fail("PATH_REJECTED")

                f, expected_dev, expected_ino = file_objects[entry]
                if st.st_dev != expected_dev or st.st_ino != expected_ino:
                    _fail("PATH_REJECTED")
                seen_files.add(entry)
            else:
                _fail("PATH_REJECTED")

    _scan_dir_again(old_core_path)

    if len(seen_dirs) != len(dir_identities) or len(seen_files) != len(file_objects):
        _fail("PATH_REJECTED")


def _verify_core(path: Path, identity: str) -> None:
    if not path.is_dir() or not (path / "NekoProxyCore.exe").is_file():
        _fail("ARTIFACT_MISSING")
    try:
        result = verify_canonical_core_bundle(path)
    except FileNotFoundError:
        _fail("ARTIFACT_MISSING")
    except OSError:
        _fail("IO_FAILED")
    except Exception:
        _fail("CORE_INVENTORY_INVALID")
    if not result.valid or result.manifest_sha256 != identity:
        _fail("CORE_INVENTORY_INVALID")


def build_generation(
    root: Path,
    state: State,
    public_keys: Mapping[str, bytes],
) -> GenerationBuildResult:
    """Build and verify the transaction candidate under its owned stage."""
    release, envelope, old_release = _validate_authority(state, public_keys)
    transaction = state.transaction
    assert transaction is not None and transaction.old is not None and transaction.staging is not None

    incoming = root / "incoming" / transaction.request_id
    staging = root / "staging" / transaction.id

    incoming_handle = None
    staging_handle = None
    try:
        incoming_handle = _validate_owned_directory(incoming, transaction.incoming)
        staging_handle = _validate_owned_directory(staging, transaction.staging)

        old = transaction.old
        candidate = transaction.candidate
        launcher_changed = candidate.launcher_identity_sha256 != old.launcher_identity_sha256
        core_changed = candidate.core_identity_sha256 != old.core_identity_sha256
        expected_names = set()
        if launcher_changed:
            expected_names.add("launcher.artifact")
        if core_changed:
            expected_names.add("core.artifact.zip")
        try:
            actual_names = {path.name for path in incoming.iterdir()}
        except OSError:
            _fail("PATH_REJECTED")
        if actual_names - expected_names:
            _fail("PACKAGE_INVALID")
        if expected_names - actual_names:
            _fail("ARTIFACT_MISSING")

        launcher_component = release.components["launcher"]
        core_component = release.components["core"]
        launcher_source = incoming / "launcher.artifact"
        core_source = incoming / "core.artifact.zip"

        old_id = f"g-{old.binding.release_sequence:020d}-{old.binding.payload_sha256}"
        old_dir = root / "releases" / old_id
        old_launcher = old_dir / "NekoLauncher.exe"
        old_core = old_dir / "ProxyCore"

        generation_dir = staging / "generation"
        try:
            generation_dir.mkdir(exist_ok=False)
        except FileExistsError:
            _fail("IO_FAILED")
        except OSError:
            _fail("IO_FAILED")

        try:
            (generation_dir / "release-envelope.json").write_bytes(envelope)

            with contextlib.ExitStack() as stack:
                old_launcher_f = stack.enter_context(_open_incoming_guarded(old_launcher))
                _verify_guarded_stream(old_launcher_f, old_release.components["launcher"].artifact_size, old.launcher_identity_sha256)

                if not old_core.is_dir() or not (old_core / "NekoProxyCore.exe").is_file():
                    _fail("ARTIFACT_MISSING")

                dir_identities, file_objects = _guard_old_core(old_core, stack)

                _verify_core(old_core, old.core_identity_sha256)

                _verify_old_core_inventory_second_pass(old_core, dir_identities, file_objects)

                if launcher_changed:
                    launcher_f = stack.enter_context(_open_incoming_guarded(launcher_source))
                    _verify_guarded_stream(launcher_f, launcher_component.artifact_size, launcher_component.artifact_sha256)

                    dest_launcher = generation_dir / "NekoLauncher.exe"
                    with dest_launcher.open("xb") as outgoing:
                        shutil.copyfileobj(launcher_f, outgoing)
                else:
                    dest_launcher = generation_dir / "NekoLauncher.exe"
                    old_launcher_f.seek(0)
                    with dest_launcher.open("xb") as outgoing:
                        shutil.copyfileobj(old_launcher_f, outgoing)

                destination_core = generation_dir / "ProxyCore"
                if core_changed:
                    core_f = stack.enter_context(_open_incoming_guarded(core_source))
                    _verify_guarded_stream(core_f, core_component.artifact_size, core_component.artifact_sha256)

                    temp_archive = staging / "core_temp.zip"
                    try:
                        with temp_archive.open("xb") as temp_out:
                            shutil.copyfileobj(core_f, temp_out)
                            temp_out.flush()
                            os.fsync(temp_out.fileno())
                    except OSError:
                        _fail("IO_FAILED")

                    class _TempCleaner:
                        def __enter__(self): pass
                        def __exit__(self, exc_type, exc_val, exc_tb):
                            try:
                                temp_archive.unlink()
                            except FileNotFoundError:
                                pass
                            except OSError:
                                if exc_type is None or not issubclass(exc_type, GenerationBuildError):
                                    _fail("IO_FAILED")

                    with _TempCleaner(), _open_incoming_guarded(temp_archive) as temp_f:
                        _verify_guarded_stream(temp_f, core_component.artifact_size, core_component.artifact_sha256)

                        try:
                            import zipfile
                            temp_f.seek(0)
                            with zipfile.ZipFile(temp_f, "r") as zf:
                                for info in zf.infolist():
                                    if info.is_dir() or (info.external_attr >> 16) & stat.S_IFLNK == stat.S_IFLNK:
                                        _fail("PACKAGE_INVALID")
                            extract_core_bundle(temp_archive, destination_core)
                        except OSError:
                            _fail("IO_FAILED")
                        except GenerationBuildError:
                            raise
                        except Exception:
                            _fail("PACKAGE_INVALID")
                else:
                    destination_core.mkdir()
                    for d_path in sorted(dir_identities.keys()):
                        if d_path == old_core:
                            continue
                        rel_path = d_path.relative_to(old_core)
                        (destination_core / rel_path).mkdir(parents=True, exist_ok=True)

                    for f_path, (f_obj, _, _) in sorted(file_objects.items()):
                        rel_path = f_path.relative_to(old_core)
                        f_obj.seek(0)
                        with (destination_core / rel_path).open("xb") as outgoing:
                            shutil.copyfileobj(f_obj, outgoing)

            _verify_core(destination_core, candidate.core_identity_sha256)
            for path in sorted(generation_dir.rglob("*")):
                if path.is_file():
                    try:
                        _flush_file(path)
                    except GenerationBuildError:
                        raise
                    except Exception:
                        _fail("FLUSH_FAILED")

            with contextlib.ExitStack() as final_stack:
                final_dirs = {}
                final_files = {}

                def _pin_dir(current_dir: Path):
                    if _is_reparse(current_dir):
                        _fail("REPARSE_REJECTED")
                    try:
                        d_handle = open_directory_guarded(current_dir)
                    except OSError:
                        _fail("PATH_REJECTED")
                    final_stack.callback(ctypes.windll.kernel32.CloseHandle, ctypes.c_void_p(d_handle))
                    try:
                        identity = get_directory_identity(d_handle)
                    except OSError:
                        _fail("PATH_REJECTED")

                    final_dirs[current_dir] = identity

                    try:
                        entries = list(current_dir.iterdir())
                    except OSError:
                        _fail("PATH_REJECTED")

                    for entry in entries:
                        if _is_reparse(entry):
                            _fail("REPARSE_REJECTED")
                        if entry.is_dir():
                            _pin_dir(entry)
                        elif entry.is_file():
                            f = final_stack.enter_context(_open_final_guarded(entry))
                            try:
                                fd = f.fileno()
                                st = os.fstat(fd)
                                if st.st_file_attributes & _REPARSE_ATTRIBUTE:
                                    _fail("REPARSE_REJECTED")
                                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                                    _fail("LINK_OR_ADS_REJECTED")
                                if st.st_file_attributes & _PROHIBITED_ATTRIBUTES:
                                    _fail("LINK_OR_ADS_REJECTED")
                                handle = msvcrt.get_osfhandle(fd)
                                if _has_ads_by_handle(handle):
                                    _fail("LINK_OR_ADS_REJECTED")
                            except GenerationBuildError:
                                raise
                            except OSError:
                                _fail("IO_FAILED")

                            final_files[entry] = (f, st.st_dev, st.st_ino)
                        else:
                            _fail("PATH_REJECTED")

                _pin_dir(generation_dir)

                seen_inodes = set()
                for entry, (f, st_dev, st_ino) in final_files.items():
                    ident = (st_dev, st_ino)
                    if ident in seen_inodes:
                        _fail("LINK_OR_ADS_REJECTED")
                    seen_inodes.add(ident)

                expected_root_files = {"release-envelope.json", "NekoLauncher.exe"}
                expected_root_dirs = {"ProxyCore"}
                actual_root_files = {p.name for p in final_files if p.parent == generation_dir}
                actual_root_dirs = {p.name for p in final_dirs if p.parent == generation_dir}
                if actual_root_files != expected_root_files or actual_root_dirs != expected_root_dirs:
                    _fail("PATH_REJECTED")

                for entry, (f, st_dev, st_ino) in final_files.items():
                    try:
                        f.flush()
                        os.fsync(f.fileno())
                    except OSError:
                        _fail("FLUSH_FAILED")
                    try:
                        st = os.fstat(f.fileno())
                        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                            _fail("LINK_OR_ADS_REJECTED")
                        if st.st_file_attributes & _PROHIBITED_ATTRIBUTES:
                            _fail("LINK_OR_ADS_REJECTED")
                    except OSError:
                        _fail("IO_FAILED")

                env_path = generation_dir / "release-envelope.json"
                env_f = final_files[env_path][0]
                env_f.seek(0)
                if env_f.read() != envelope:
                    _fail("HASH_MISMATCH")

                launcher_path = generation_dir / "NekoLauncher.exe"
                launcher_f = final_files[launcher_path][0]
                launcher_f.seek(0)
                if hashlib.sha256(launcher_f.read()).hexdigest() != candidate.launcher_identity_sha256:
                    _fail("HASH_MISMATCH")

                launcher_f.seek(0)
                try:
                    st = os.fstat(launcher_f.fileno())
                    if st.st_size != launcher_component.artifact_size:
                        _fail("SIZE_MISMATCH")
                except OSError:
                    _fail("IO_FAILED")

                _verify_core(destination_core, candidate.core_identity_sha256)
                _verify_old_core_inventory_second_pass(generation_dir, final_dirs, final_files)

                generation_id = (
                    f"g-{candidate.binding.release_sequence:020d}-{candidate.binding.payload_sha256}"
                )
                return GenerationBuildResult(
                    changed={"launcher": launcher_changed, "core": core_changed},
                    generation_id=generation_id,
                    generation_dir=generation_dir,
                    generation=candidate,
                )
        except GenerationBuildError:
            raise
        except OSError:
            _fail("IO_FAILED")
    finally:
        if incoming_handle is not None:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(incoming_handle))
        if staging_handle is not None:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(staging_handle))
