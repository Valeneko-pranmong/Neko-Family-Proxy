"""Binary frame encoder and decoder for dual slot files and enrollment marker."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct

SLOT_FRAME_SIZE = 1_048_576
MARKER_FRAME_SIZE = 16_384

SLOT_MAGIC = b"NEKOUPD1"
MARKER_MAGIC = b"NEKOENR1"

HEADER_PREFIX_FORMAT = "<8sIIQ"
HEADER_PREFIX_SIZE = struct.calcsize(HEADER_PREFIX_FORMAT)  # 24 bytes
CHECKSUM_SIZE = 32
TOTAL_HEADER_SIZE = HEADER_PREFIX_SIZE + CHECKSUM_SIZE      # 56 bytes

MAX_SLOT_BODY_SIZE = SLOT_FRAME_SIZE - TOTAL_HEADER_SIZE     # 1,048,520 bytes
MAX_MARKER_BODY_SIZE = MARKER_FRAME_SIZE - TOTAL_HEADER_SIZE # 16,328 bytes


class FrameCorruptError(ValueError):
    """Raised when a binary frame has an invalid magic, checksum, or dirty padding."""


@dataclass(frozen=True)
class SlotFrame:
    revision: int
    format_version: int
    body_bytes: bytes


@dataclass(frozen=True)
class MarkerFrame:
    format_version: int
    body_bytes: bytes


def pack_slot_frame(frame: SlotFrame) -> bytes:
    """Pack a SlotFrame into exactly 1,048,576 bytes."""
    body_len = len(frame.body_bytes)
    if body_len == 0 or body_len > MAX_SLOT_BODY_SIZE:
        raise ValueError(f"Invalid body length for slot frame: {body_len}")
    if frame.format_version != 1:
        raise ValueError(f"Unsupported format version: {frame.format_version}")
    if frame.revision < 1:
        raise ValueError(f"Invalid revision: {frame.revision}")

    prefix = struct.pack(
        HEADER_PREFIX_FORMAT,
        SLOT_MAGIC,
        body_len,
        frame.format_version,
        frame.revision,
    )
    checksum = hashlib.sha256(prefix + frame.body_bytes).digest()
    padding_len = SLOT_FRAME_SIZE - TOTAL_HEADER_SIZE - body_len
    padding = b"\x00" * padding_len
    return prefix + checksum + frame.body_bytes + padding


def unpack_slot_frame(raw: bytes) -> SlotFrame:
    """Unpack exactly 1,048,576 bytes into a SlotFrame."""
    if len(raw) != SLOT_FRAME_SIZE:
        raise FrameCorruptError(f"Invalid frame size: expected {SLOT_FRAME_SIZE}, got {len(raw)}")

    prefix = raw[:HEADER_PREFIX_SIZE]
    magic, body_len, format_version, revision = struct.unpack(HEADER_PREFIX_FORMAT, prefix)
    if magic != SLOT_MAGIC:
        raise FrameCorruptError(f"Invalid slot magic: {magic!r}")
    if body_len == 0 or body_len > MAX_SLOT_BODY_SIZE:
        raise FrameCorruptError(f"Invalid body length: {body_len}")
    if format_version != 1:
        raise FrameCorruptError(f"Unsupported format version: {format_version}")

    stored_checksum = raw[HEADER_PREFIX_SIZE:TOTAL_HEADER_SIZE]
    body_bytes = raw[TOTAL_HEADER_SIZE : TOTAL_HEADER_SIZE + body_len]
    expected_checksum = hashlib.sha256(prefix + body_bytes).digest()
    if stored_checksum != expected_checksum:
        raise FrameCorruptError("Checksum mismatch in slot frame")

    padding = raw[TOTAL_HEADER_SIZE + body_len :]
    # Check if padding has any non-zero byte
    if any(b != 0 for b in padding):
        raise FrameCorruptError("Dirty trailing padding in slot frame")

    return SlotFrame(revision=revision, format_version=format_version, body_bytes=body_bytes)


def pack_marker_frame(frame: MarkerFrame) -> bytes:
    """Pack a MarkerFrame into exactly 16,384 bytes."""
    body_len = len(frame.body_bytes)
    if body_len == 0 or body_len > MAX_MARKER_BODY_SIZE:
        raise ValueError(f"Invalid body length for marker frame: {body_len}")
    if frame.format_version != 1:
        raise ValueError(f"Unsupported format version: {frame.format_version}")

    prefix = struct.pack(
        HEADER_PREFIX_FORMAT,
        MARKER_MAGIC,
        body_len,
        frame.format_version,
        1,  # Marker revision is always 1
    )
    checksum = hashlib.sha256(prefix + frame.body_bytes).digest()
    padding_len = MARKER_FRAME_SIZE - TOTAL_HEADER_SIZE - body_len
    padding = b"\x00" * padding_len
    return prefix + checksum + frame.body_bytes + padding


def unpack_marker_frame(raw: bytes) -> MarkerFrame:
    """Unpack exactly 16,384 bytes into a MarkerFrame."""
    if len(raw) != MARKER_FRAME_SIZE:
        raise FrameCorruptError(f"Invalid frame size: expected {MARKER_FRAME_SIZE}, got {len(raw)}")

    prefix = raw[:HEADER_PREFIX_SIZE]
    magic, body_len, format_version, revision = struct.unpack(HEADER_PREFIX_FORMAT, prefix)
    if magic != MARKER_MAGIC:
        raise FrameCorruptError(f"Invalid marker magic: {magic!r}")
    if body_len == 0 or body_len > MAX_MARKER_BODY_SIZE:
        raise FrameCorruptError(f"Invalid body length: {body_len}")
    if format_version != 1:
        raise FrameCorruptError(f"Unsupported format version: {format_version}")
    if revision != 1:
        raise FrameCorruptError(f"Unsupported marker revision: {revision}")

    stored_checksum = raw[HEADER_PREFIX_SIZE:TOTAL_HEADER_SIZE]
    body_bytes = raw[TOTAL_HEADER_SIZE : TOTAL_HEADER_SIZE + body_len]
    expected_checksum = hashlib.sha256(prefix + body_bytes).digest()
    if stored_checksum != expected_checksum:
        raise FrameCorruptError("Checksum mismatch in marker frame")

    padding = raw[TOTAL_HEADER_SIZE + body_len :]
    if any(b != 0 for b in padding):
        raise FrameCorruptError("Dirty trailing padding in marker frame")

    return MarkerFrame(format_version=format_version, body_bytes=body_bytes)
