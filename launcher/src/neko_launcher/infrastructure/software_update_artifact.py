from __future__ import annotations

import hashlib
import hmac
import stat
from dataclasses import dataclass
from pathlib import Path

from neko_launcher.application.software_update_models import ComponentRelease

_READ_SIZE = 1024 * 1024
_COMPONENT_MAX_BYTES = {
    "launcher": 128 * 1024 * 1024,
    "core": 1024 * 1024 * 1024,
}


class ArtifactVerificationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class VerifiedArtifact:
    component: str
    path: Path
    sha256: str
    size: int


def _error(code: str) -> ArtifactVerificationError:
    return ArtifactVerificationError(code)


def verify_artifact(
    path: Path,
    component: ComponentRelease,
) -> VerifiedArtifact:
    try:
        maximum_size = _COMPONENT_MAX_BYTES[component.name]
    except KeyError:
        raise _error("ARTIFACT_TOO_LARGE") from None

    if component.artifact_size > maximum_size:
        raise _error("ARTIFACT_TOO_LARGE")

    try:
        metadata = path.stat()
    except OSError:
        raise _error("ARTIFACT_MISSING") from None

    if not stat.S_ISREG(metadata.st_mode):
        raise _error("ARTIFACT_MISSING")
    if metadata.st_size > maximum_size:
        raise _error("ARTIFACT_TOO_LARGE")
    if metadata.st_size != component.artifact_size:
        raise _error("ARTIFACT_SIZE_MISMATCH")

    digest = hashlib.sha256()
    streamed_size = 0
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_READ_SIZE), b""):
                streamed_size += len(chunk)
                if streamed_size > maximum_size:
                    raise _error("ARTIFACT_TOO_LARGE")
                if streamed_size > component.artifact_size:
                    raise _error("ARTIFACT_SIZE_MISMATCH")
                digest.update(chunk)
    except ArtifactVerificationError:
        raise
    except OSError:
        raise _error("ARTIFACT_MISSING") from None

    if streamed_size != component.artifact_size:
        raise _error("ARTIFACT_SIZE_MISMATCH")

    actual_sha256 = digest.hexdigest()
    if not hmac.compare_digest(actual_sha256, component.artifact_sha256):
        raise _error("ARTIFACT_HASH_MISMATCH")

    return VerifiedArtifact(
        component=component.name,
        path=path,
        sha256=actual_sha256,
        size=streamed_size,
    )
