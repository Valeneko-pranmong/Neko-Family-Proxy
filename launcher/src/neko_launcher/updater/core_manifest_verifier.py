"""Canonical Core manifest and on-disk bundle verifier."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class CoreVerificationError(ValueError):
    """Raised when a Core bundle does not match its canonical manifest."""


@dataclass(frozen=True)
class CoreVerificationResult:
    valid: bool
    file_count: int = 0
    total_bytes: int = 0
    manifest_sha256: str = ""
    error: str | None = None


def verify_canonical_core_bundle(bundle_dir: Path) -> CoreVerificationResult:
    """Verify that bundle_dir contains a valid canonical-core-manifest.json matching all on-disk files."""
    raise NotImplementedError("verify_canonical_core_bundle not implemented")
