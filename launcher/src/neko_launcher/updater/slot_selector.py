"""Pairwise slot selector implementing the 6-predicate hierarchy from Section 8.1."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from neko_launcher.updater.state_models import State


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    ENROLLMENT_INCOMPLETE = "ENROLLMENT_INCOMPLETE"


@dataclass(frozen=True)
class SelectionResult:
    status: SelectionStatus
    state: State | None = None
    active_slot: str | None = None  # "a" or "b"
    reason: str | None = None


def select_active_slot(
    slot_a_bytes: bytes | None,
    slot_b_bytes: bytes | None,
    public_keys: Mapping[str, bytes],
) -> SelectionResult:
    """Classify and select the authoritative active slot according to Section 8.1."""
    raise NotImplementedError("select_active_slot not implemented")
