from __future__ import annotations

import hashlib
from pathlib import Path

from neko_launcher.application.software_update_models import LocalReleaseIdentity

_READ_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_READ_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_local_release_identity(
    *,
    release_sequence: int,
    release_id: str,
    launcher_version: str,
    launcher_executable: Path,
    core_version: str,
    core_manifest: Path,
) -> LocalReleaseIdentity:
    return LocalReleaseIdentity(
        release_sequence=release_sequence,
        release_id=release_id,
        launcher_version=launcher_version,
        launcher_installed_identity_sha256=sha256_file(launcher_executable),
        core_version=core_version,
        core_installed_identity_sha256=sha256_file(core_manifest),
    )
