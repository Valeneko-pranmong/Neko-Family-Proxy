"""Deterministic crash-recovery engine and recovery dispatcher."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from neko_launcher.updater.state_models import Generation, State


@dataclass(frozen=True)
class RecoveryResult:
    converged: bool
    status: str
    selected_generation: Generation | None
    mutations_performed: int
    final_state: State | None
    error: str | None = None


class RecoveryEngine:
    """Manages crash recovery, fault resolution, and scratch cleanup."""

    def __init__(
        self,
        root_dir: Path,
        public_keys: Mapping[str, bytes],
    ) -> None:
        self.root_dir = root_dir
        self.public_keys = public_keys

    def run_recovery(self) -> RecoveryResult:
        """Execute crash recovery to converge installation to OLD_FULLY_RESTORED or NEW_FULLY_COMMITTED."""
        raise NotImplementedError("run_recovery not implemented")
