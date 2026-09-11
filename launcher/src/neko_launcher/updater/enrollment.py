import base64
import binascii
import ctypes
import ctypes.wintypes
import pathlib
from typing import Mapping

from neko_launcher.updater.binary_frame import (
    MARKER_FRAME_SIZE,
    SLOT_FRAME_SIZE,
    SlotFrame,
    pack_slot_frame,
    unpack_marker_frame,
    unpack_slot_frame,
)
from neko_launcher.updater.canonical_json import canonical_json_loads
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from neko_launcher.updater.slot_selector import (
    SelectionResult,
    SelectionStatus,
    select_active_slot,
)
from neko_launcher.updater.slot_store import (
    SlotStore,
    SlotStoreError,
    _close_handle,
    _flush_handle,
    _get_file_size,
    _is_invalid,
    _open_state_dir_guard,
    _read_exact_at_zero,
    _validate_trusted_leaf,
    _write_all_at_zero,
    kernel32,
)
from neko_launcher.updater.state_models import (
    EnrollmentMarker,
    RootIdentity,
    State,
    deserialize_marker,
    deserialize_state,
    serialize_state,
)


GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
CREATE_NEW = 1
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000


kernel32.SetEndOfFile.argtypes = [ctypes.c_void_p]
kernel32.SetEndOfFile.restype = ctypes.wintypes.BOOL


class EnrollmentError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _create_exclusive_fixed(path: str | pathlib.Path, size: int) -> int:
    h = kernel32.CreateFileW(
        str(path),
        0x80000000 | 0x40000000,
        0,
        None,
        CREATE_NEW,
        0x80 | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if _is_invalid(h):
        raise OSError(ctypes.get_last_error(), "CreateFileW failed")
    if not kernel32.SetFilePointerEx(h, ctypes.wintypes.LARGE_INTEGER(size), None, 0):
        _close_handle(h)
        raise OSError(ctypes.get_last_error(), "SetFilePointerEx failed")
    if not kernel32.SetEndOfFile(h):
        _close_handle(h)
        raise OSError(ctypes.get_last_error(), "SetEndOfFile failed")
    if not kernel32.SetFilePointerEx(h, ctypes.wintypes.LARGE_INTEGER(0), None, 0):
        _close_handle(h)
        raise OSError(ctypes.get_last_error(), "SetFilePointerEx failed")
    return h


def _open_existing_readonly(path: str | pathlib.Path) -> int:
    h = kernel32.CreateFileW(
        str(path),
        GENERIC_READ,
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


def _validate_bootstrap_state(
    state: State,
    marker: EnrollmentMarker,
    public_keys: Mapping[str, bytes],
) -> None:
    if state.helper_protocol != 1:
        raise EnrollmentError("PROTOCOL_UNSUPPORTED")
    if state.revision != 1:
        raise EnrollmentError("PROTOCOL_INVALID")
    if state.phase != "ENROLLING":
        raise EnrollmentError("PROTOCOL_INVALID")
    if state.enrollment_complete is not False:
        raise EnrollmentError("PROTOCOL_INVALID")
    if state.installation_id != marker.installation_id:
        raise EnrollmentError("PROTOCOL_INVALID")
    if state.helper_protocol != marker.helper_protocol:
        raise EnrollmentError("PROTOCOL_INVALID")

    if (
        state.committed is not None
        or state.previous is not None
        or state.highwater is not None
        or state.observed is not None
        or state.failed is not None
        or state.transaction is not None
        or state.cleanup is not None
        or state.rollback is not None
        or state.last_error is not None
    ):
        raise EnrollmentError("STATE_CORRUPT")

    if len(state.evidence) != 1:
        raise EnrollmentError("STATE_CORRUPT")

    p_sha = marker.bootstrap_payload_sha256
    if p_sha not in state.evidence:
        raise EnrollmentError("STATE_CORRUPT")

    envelope_b64 = state.evidence[p_sha]
    try:
        envelope_bytes = base64.b64decode(envelope_b64, validate=True)
        if base64.b64encode(envelope_bytes).decode("ascii") != envelope_b64:
            raise EnrollmentError("SCHEMA_INVALID")
    except (binascii.Error, ValueError):
        raise EnrollmentError("SCHEMA_INVALID") from None

    if len(envelope_bytes) > 65536:
        raise EnrollmentError("PROTOCOL_INVALID")

    try:
        envelope_doc = canonical_json_loads(envelope_bytes)
    except ValueError:
        raise EnrollmentError("SCHEMA_INVALID") from None

    if not isinstance(envelope_doc, dict):
        raise EnrollmentError("SCHEMA_INVALID")

    try:
        _, returned_sha = verify_release_envelope_v2(envelope_doc, public_keys)
    except ValueError as exc:
        msg = str(exc)
        if "Unknown key_id" in msg:
            raise EnrollmentError("UNKNOWN_KEY") from None
        if "Invalid signature" in msg:
            raise EnrollmentError("SIGNATURE_INVALID") from None
        raise EnrollmentError("SCHEMA_INVALID") from None

    if returned_sha != p_sha:
        raise EnrollmentError("SIGNATURE_INVALID")


def enroll_state_directory(
    state_dir: pathlib.Path,
    marker: EnrollmentMarker,
    initial_state: State,
    public_keys: Mapping[str, bytes],
) -> SelectionResult:
    key_snapshot = dict(public_keys)
    if not state_dir.is_dir():
        raise EnrollmentError("ROOT_UNSUPPORTED")

    marker_path = state_dir / "enrollment.bin"
    slot_a_path = state_dir / "slot-a.bin"
    slot_b_path = state_dir / "slot-b.bin"

    if marker.helper_protocol != 1:
        raise EnrollmentError("PROTOCOL_UNSUPPORTED")
    if marker.schema_version != 1:
        raise EnrollmentError("SCHEMA_INVALID")
    if marker.enrollment_status != "PREPARED":
        raise EnrollmentError("PROTOCOL_INVALID")

    _validate_bootstrap_state(initial_state, marker, key_snapshot)

    try:
        state_frame = SlotFrame(
            revision=1,
            format_version=1,
            body_bytes=serialize_state(initial_state),
        )
        state_raw = pack_slot_frame(state_frame)
    except ValueError:
        raise EnrollmentError("STATE_CORRUPT")

    guard_handle = None
    marker_handle = None
    slot_a_handle = None
    slot_b_handle = None
    try:
        guard_handle = _open_state_dir_guard(state_dir)

        try:
            marker_handle = _open_existing_readonly(marker_path)
            _validate_trusted_leaf(marker_handle, guard_handle)
            if _get_file_size(marker_handle) != MARKER_FRAME_SIZE:
                raise EnrollmentError("STATE_CORRUPT")
            reread_marker = _read_exact_at_zero(marker_handle, MARKER_FRAME_SIZE)
        except FileNotFoundError:
            raise EnrollmentError("REPAIR_REQUIRED")

        try:
            unpacked_marker = unpack_marker_frame(reread_marker)
            deserialized_marker = deserialize_marker(unpacked_marker.body_bytes)
        except ValueError:
            raise EnrollmentError("STATE_CORRUPT")

        if deserialized_marker != marker:
            raise EnrollmentError("PROTOCOL_INVALID")

        store = None
        try:
            store = SlotStore(slot_a_path, slot_b_path, key_snapshot)

            if not store.slot_a_present and not store.slot_b_present:
                slot_a_handle = _create_exclusive_fixed(slot_a_path, SLOT_FRAME_SIZE)
                _validate_trusted_leaf(slot_a_handle, guard_handle)
                _write_all_at_zero(slot_a_handle, state_raw)
                try:
                    _flush_handle(slot_a_handle)
                except OSError:
                    raise EnrollmentError("FLUSH_FAILED")
                reread_a = _read_exact_at_zero(slot_a_handle, SLOT_FRAME_SIZE)
                if reread_a != state_raw:
                    raise EnrollmentError("STATE_CORRUPT")
                try:
                    unpacked_a = unpack_slot_frame(reread_a)
                    deserialized_a = deserialize_state(unpacked_a.body_bytes)
                except ValueError:
                    raise EnrollmentError("STATE_CORRUPT")
                if unpacked_a.revision != 1 or deserialized_a != initial_state:
                    raise EnrollmentError("STATE_CORRUPT")

                slot_b_handle = _create_exclusive_fixed(slot_b_path, SLOT_FRAME_SIZE)
                _validate_trusted_leaf(slot_b_handle, guard_handle)
                _write_all_at_zero(slot_b_handle, state_raw)
                try:
                    _flush_handle(slot_b_handle)
                except OSError:
                    raise EnrollmentError("FLUSH_FAILED")
                reread_b = _read_exact_at_zero(slot_b_handle, SLOT_FRAME_SIZE)
                if reread_b != state_raw:
                    raise EnrollmentError("STATE_CORRUPT")
                try:
                    unpacked_b = unpack_slot_frame(reread_b)
                    deserialized_b = deserialize_state(unpacked_b.body_bytes)
                except ValueError:
                    raise EnrollmentError("STATE_CORRUPT")
                if unpacked_b.revision != 1 or deserialized_b != initial_state:
                    raise EnrollmentError("STATE_CORRUPT")

                result = select_active_slot(reread_a, reread_b, key_snapshot)
                if result.status != SelectionStatus.SELECTED or result.state != initial_state:
                    raise EnrollmentError("REPAIR_REQUIRED")
                return result

            elif store.slot_a_present and not store.slot_b_present:
                if not store.slot_a_individually_valid:
                    raise EnrollmentError("REPAIR_REQUIRED")
                reread_a = _read_exact_at_zero(store.handle_a, SLOT_FRAME_SIZE)
                try:
                    unpacked_a = unpack_slot_frame(reread_a)
                    deserialized_a = deserialize_state(unpacked_a.body_bytes)
                except ValueError:
                    raise EnrollmentError("REPAIR_REQUIRED")
                if unpacked_a.revision != 1 or deserialized_a != initial_state:
                    raise EnrollmentError("REPAIR_REQUIRED")

                slot_b_handle = _create_exclusive_fixed(slot_b_path, SLOT_FRAME_SIZE)
                _validate_trusted_leaf(slot_b_handle, guard_handle)
                _write_all_at_zero(slot_b_handle, state_raw)
                try:
                    _flush_handle(slot_b_handle)
                except OSError:
                    raise EnrollmentError("FLUSH_FAILED")
                reread_b = _read_exact_at_zero(slot_b_handle, SLOT_FRAME_SIZE)
                if reread_b != state_raw:
                    raise EnrollmentError("STATE_CORRUPT")
                try:
                    unpacked_b = unpack_slot_frame(reread_b)
                    deserialized_b = deserialize_state(unpacked_b.body_bytes)
                except ValueError:
                    raise EnrollmentError("STATE_CORRUPT")
                if unpacked_b.revision != 1 or deserialized_b != initial_state:
                    raise EnrollmentError("STATE_CORRUPT")

                result = select_active_slot(reread_a, reread_b, key_snapshot)
                if result.status != SelectionStatus.SELECTED or result.state != initial_state:
                    raise EnrollmentError("REPAIR_REQUIRED")
                return result

            elif store.slot_b_present and not store.slot_a_present:
                if not store.slot_b_individually_valid:
                    raise EnrollmentError("REPAIR_REQUIRED")
                reread_b = _read_exact_at_zero(store.handle_b, SLOT_FRAME_SIZE)
                try:
                    unpacked_b = unpack_slot_frame(reread_b)
                    deserialized_b = deserialize_state(unpacked_b.body_bytes)
                except ValueError:
                    raise EnrollmentError("REPAIR_REQUIRED")
                if unpacked_b.revision != 1 or deserialized_b != initial_state:
                    raise EnrollmentError("REPAIR_REQUIRED")

                slot_a_handle = _create_exclusive_fixed(slot_a_path, SLOT_FRAME_SIZE)
                _validate_trusted_leaf(slot_a_handle, guard_handle)
                _write_all_at_zero(slot_a_handle, state_raw)
                try:
                    _flush_handle(slot_a_handle)
                except OSError:
                    raise EnrollmentError("FLUSH_FAILED")
                reread_a = _read_exact_at_zero(slot_a_handle, SLOT_FRAME_SIZE)
                if reread_a != state_raw:
                    raise EnrollmentError("STATE_CORRUPT")
                try:
                    unpacked_a = unpack_slot_frame(reread_a)
                    deserialized_a = deserialize_state(unpacked_a.body_bytes)
                except ValueError:
                    raise EnrollmentError("STATE_CORRUPT")
                if unpacked_a.revision != 1 or deserialized_a != initial_state:
                    raise EnrollmentError("STATE_CORRUPT")

                result = select_active_slot(reread_a, reread_b, key_snapshot)
                if result.status != SelectionStatus.SELECTED or result.state != initial_state:
                    raise EnrollmentError("REPAIR_REQUIRED")
                return result

            else:
                if store.slot_a_individually_valid and store.slot_b_individually_valid:
                    res = store.load()
                    if res.status == SelectionStatus.SELECTED and res.state == initial_state:
                        return res
                    raise EnrollmentError("REPAIR_REQUIRED")

                if not store.slot_a_individually_valid and not store.slot_b_individually_valid:
                    raise EnrollmentError("REPAIR_REQUIRED")

                if store.slot_a_individually_valid:
                    anchor_handle = store.handle_a
                    peer_handle = store.handle_b
                    anchor_is_a = True
                else:
                    anchor_handle = store.handle_b
                    peer_handle = store.handle_a
                    anchor_is_a = False

                if anchor_handle is None or peer_handle is None:
                    raise EnrollmentError("REPAIR_REQUIRED")

                try:
                    reread_anchor = _read_exact_at_zero(anchor_handle, SLOT_FRAME_SIZE)
                except OSError:
                    raise EnrollmentError("IO_FAILED")

                try:
                    unpacked_anchor = unpack_slot_frame(reread_anchor)
                    deserialized_anchor = deserialize_state(unpacked_anchor.body_bytes)
                except ValueError:
                    raise EnrollmentError("REPAIR_REQUIRED")

                if unpacked_anchor.revision != 1 or deserialized_anchor != initial_state:
                    raise EnrollmentError("REPAIR_REQUIRED")

                try:
                    _write_all_at_zero(peer_handle, state_raw)
                except OSError:
                    raise EnrollmentError("IO_FAILED")

                try:
                    _flush_handle(peer_handle)
                except OSError:
                    raise EnrollmentError("FLUSH_FAILED")

                try:
                    reread_peer = _read_exact_at_zero(peer_handle, SLOT_FRAME_SIZE)
                except OSError:
                    raise EnrollmentError("IO_FAILED")

                if reread_peer != state_raw:
                    raise EnrollmentError("STATE_CORRUPT")

                try:
                    unpacked_peer = unpack_slot_frame(reread_peer)
                    deserialized_peer = deserialize_state(unpacked_peer.body_bytes)
                except ValueError:
                    raise EnrollmentError("STATE_CORRUPT")

                if unpacked_peer.revision != 1 or deserialized_peer != initial_state:
                    raise EnrollmentError("STATE_CORRUPT")

                reread_a = reread_anchor if anchor_is_a else reread_peer
                reread_b = reread_peer if anchor_is_a else reread_anchor

                result = select_active_slot(reread_a, reread_b, key_snapshot)
                if result.status != SelectionStatus.SELECTED or result.state != initial_state:
                    raise EnrollmentError("REPAIR_REQUIRED")
                return result
        finally:
            if store is not None:
                store.close()

    except EnrollmentError:
        raise
    except OSError:
        raise EnrollmentError("IO_FAILED")
    except SlotStoreError as e:
        if e.code == "IO_FAILED":
            raise EnrollmentError("IO_FAILED")
        raise EnrollmentError("REPAIR_REQUIRED")
    finally:
        _close_handle(marker_handle)
        _close_handle(slot_a_handle)
        _close_handle(slot_b_handle)
        _close_handle(guard_handle)


def load_enrollment(
    state_dir: pathlib.Path,
    expected_root: RootIdentity,
    expected_helper_sha256: str,
    expected_keyset_sha256: str,
    expected_bootstrap_payload_sha256: str,
    public_keys: Mapping[str, bytes],
) -> tuple[EnrollmentMarker, SelectionResult]:
    key_snapshot = dict(public_keys)
    marker_path = state_dir / "enrollment.bin"
    slot_a_path = state_dir / "slot-a.bin"
    slot_b_path = state_dir / "slot-b.bin"

    guard_handle = None
    marker_handle = None
    store = None
    try:
        try:
            guard_handle = _open_state_dir_guard(state_dir)
            marker_handle = _open_existing_readonly(marker_path)
            _validate_trusted_leaf(marker_handle, guard_handle)
            if _get_file_size(marker_handle) != MARKER_FRAME_SIZE:
                raise EnrollmentError("STATE_CORRUPT")
            marker_raw = _read_exact_at_zero(marker_handle, MARKER_FRAME_SIZE)
        except FileNotFoundError:
            raise EnrollmentError("REPAIR_REQUIRED")
        except OSError:
            raise EnrollmentError("IO_FAILED")

        try:
            marker_frame = unpack_marker_frame(marker_raw)
            marker = deserialize_marker(marker_frame.body_bytes)
        except ValueError:
            raise EnrollmentError("STATE_CORRUPT")

        if marker.root != expected_root:
            raise EnrollmentError("ROOT_UNSUPPORTED")
        if marker.helper_sha256 != expected_helper_sha256:
            raise EnrollmentError("PROTOCOL_UNSUPPORTED")
        if marker.keyset_sha256 != expected_keyset_sha256:
            raise EnrollmentError("UNKNOWN_KEY")
        if marker.bootstrap_payload_sha256 != expected_bootstrap_payload_sha256:
            raise EnrollmentError("PROTOCOL_INVALID")
        if marker.helper_protocol != 1:
            raise EnrollmentError("PROTOCOL_UNSUPPORTED")

        try:
            store = SlotStore(slot_a_path, slot_b_path, key_snapshot)
        except SlotStoreError as exc:
            if exc.code == "IO_FAILED":
                raise EnrollmentError("IO_FAILED")
            raise EnrollmentError("REPAIR_REQUIRED")

        try:
            result = store.load()
        except SlotStoreError as exc:
            if exc.code == "IO_FAILED":
                raise EnrollmentError("IO_FAILED")
            raise EnrollmentError("REPAIR_REQUIRED")

        if result.status == SelectionStatus.ENROLLMENT_INCOMPLETE:
            return marker, result

        if result.status != SelectionStatus.SELECTED or result.state is None:
            raise EnrollmentError("REPAIR_REQUIRED")

        if result.state.installation_id != marker.installation_id:
            raise EnrollmentError("PROTOCOL_INVALID")

        if result.state.helper_protocol != marker.helper_protocol:
            raise EnrollmentError("REPAIR_REQUIRED")

        if not result.state.enrollment_complete:
            if result.state.phase == "ENROLLING" and result.state.revision == 1:
                _validate_bootstrap_state(result.state, marker, key_snapshot)
                return marker, result
            if (
                result.state.phase == "IDLE"
                and result.state.committed is not None
                and result.state.committed.binding.payload_sha256 == marker.bootstrap_payload_sha256
                and result.state.highwater == result.state.committed.binding
                and result.state.observed == result.state.committed.binding
                and result.state.previous is None
                and result.state.failed is None
                and result.state.transaction is None
                and result.state.cleanup is None
                and result.state.rollback is None
                and result.state.last_error is None
            ):
                return marker, result
            raise EnrollmentError("REPAIR_REQUIRED")

        if not store.slot_a_present or not store.slot_b_present:
            raise EnrollmentError("REPAIR_REQUIRED")

        return marker, result
    finally:
        if store is not None:
            store.close()
        if marker_handle is not None:
            _close_handle(marker_handle)
        if guard_handle is not None:
            _close_handle(guard_handle)
