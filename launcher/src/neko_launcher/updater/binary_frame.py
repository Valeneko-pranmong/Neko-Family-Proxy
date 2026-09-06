"""Binary frame encoder and decoder for dual slot files and enrollment marker."""
from __future__ import annotations

from dataclasses import dataclass

SLOT_FRAME_SIZE = 1_048_576
MARKER_FRAME_SIZE = 16_384

SLOT_MAGIC = b"NEKOUPD1"
MARKER_MAGIC = b"NEKOENR1"


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
    raise NotImplementedError("pack_slot_frame not implemented")


def unpack_slot_frame(raw: bytes) -> SlotFrame:
    """Unpack exactly 1,048,576 bytes into a SlotFrame."""
    raise NotImplementedError("unpack_slot_frame not implemented")


def pack_marker_frame(frame: MarkerFrame) -> bytes:
    """Pack a MarkerFrame into exactly 16,384 bytes."""
    raise NotImplementedError("pack_marker_frame not implemented")


def unpack_marker_frame(raw: bytes) -> MarkerFrame:
    """Unpack exactly 16,384 bytes into a MarkerFrame."""
    raise NotImplementedError("unpack_marker_frame not implemented")
