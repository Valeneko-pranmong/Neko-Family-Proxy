from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class UpdateLifecycleState(str, Enum):
    IDLE = "idle"
    STAGING = "staging"
    UPDATE_PENDING = "update_pending"
    APPLYING = "applying"


@dataclass(frozen=True)
class VerifiedPendingUpdate:
    release_id: str
    release_sequence: int
    changed_components: tuple[str, ...]
    envelope_bytes: bytes
    generation_dir: Path
    launcher_artifact: Path | None
    core_artifact: Path | None
