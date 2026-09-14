from __future__ import annotations

import hashlib
from pathlib import Path

from neko_launcher.application.software_update_models import (
    DevelopmentReleaseIdentity,
)

_READ_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_READ_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_development_release_identity(
    *,
    launcher_version: str,
    launcher_executable: Path,
    core_version: str,
    core_manifest: Path,
) -> DevelopmentReleaseIdentity:
    return DevelopmentReleaseIdentity(
        release_sequence=0,
        release_id="dev-unpublished",
        launcher_version=launcher_version,
        launcher_installed_identity_sha256=sha256_file(launcher_executable),
        core_version=core_version,
        core_installed_identity_sha256=sha256_file(core_manifest),
    )
