import pytest

from neko_launcher.updater.binary_frame import (
    MARKER_FRAME_SIZE,
    MARKER_MAGIC,
    SLOT_FRAME_SIZE,
    SLOT_MAGIC,
    FrameCorruptError,
    MarkerFrame,
    SlotFrame,
    pack_marker_frame,
    pack_slot_frame,
    unpack_marker_frame,
    unpack_slot_frame,
)


def test_slot_frame_pack_unpack_roundtrip() -> None:
    body = b'{"schema_version":1,"revision":42}'
    frame = SlotFrame(revision=42, format_version=1, body_bytes=body)
    packed = pack_slot_frame(frame)
    assert len(packed) == SLOT_FRAME_SIZE == 1_048_576
    assert packed[:8] == SLOT_MAGIC

    unpacked = unpack_slot_frame(packed)
    assert unpacked.revision == 42
    assert unpacked.format_version == 1
    assert unpacked.body_bytes == body


def test_slot_frame_rejects_corrupted_checksum() -> None:
    body = b'{"schema_version":1}'
    packed = bytearray(pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=body)))
    # Corrupt body byte
    packed[60] ^= 0xFF
    with pytest.raises(FrameCorruptError, match="Checksum mismatch"):
        unpack_slot_frame(bytes(packed))


def test_slot_frame_rejects_dirty_padding() -> None:
    body = b'{"schema_version":1}'
    packed = bytearray(pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=body)))
    # Dirty trailing padding
    packed[-1] = 0x01
    with pytest.raises(FrameCorruptError, match="Dirty trailing padding"):
        unpack_slot_frame(bytes(packed))


def test_slot_frame_rejects_wrong_size() -> None:
    with pytest.raises(FrameCorruptError, match="Invalid frame size"):
        unpack_slot_frame(b"too short")


def test_marker_frame_pack_unpack_roundtrip() -> None:
    body = b'{"installation_id":"abc"}'
    frame = MarkerFrame(format_version=1, body_bytes=body)
    packed = pack_marker_frame(frame)
    assert len(packed) == MARKER_FRAME_SIZE == 16_384
    assert packed[:8] == MARKER_MAGIC

    unpacked = unpack_marker_frame(packed)
    assert unpacked.format_version == 1
    assert unpacked.body_bytes == body


def test_marker_frame_rejects_dirty_padding() -> None:
    body = b'{"installation_id":"abc"}'
    packed = bytearray(pack_marker_frame(MarkerFrame(format_version=1, body_bytes=body)))
    packed[-1] = 0x01
    with pytest.raises(FrameCorruptError, match="Dirty trailing padding"):
        unpack_marker_frame(bytes(packed))
