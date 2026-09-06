"""Staging area creation and atomic generation publication."""
from __future__ import annotations

from pathlib import Path

from neko_launcher.updater.state_models import DirectoryIdentity


class GenerationPublisher:
    """Manages transaction staging creation and atomic publication into releases/."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def create_staging_area(self, transaction_id: str) -> tuple[int, DirectoryIdentity, Path]:
        """Exclusively create staging/<transaction-id> and return (handle, identity, path)."""
        raise NotImplementedError("create_staging_area not implemented")

    def publish_generation(self, staging_generation_dir: Path, generation_id: str) -> Path:
        """Atomically rename staging_generation_dir into releases/<generation-id>."""
        raise NotImplementedError("publish_generation not implemented")
