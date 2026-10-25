from __future__ import annotations

import pytest

from scripts.publish_atomic_release import (
    StageDraftReleaseError,
    validate_stable_release_channel,
)


def test_5_2_stable_publication_is_blocked() -> None:
    for version in ("5.2.0", "v5.2.1"):
        with pytest.raises(StageDraftReleaseError, match="preview-only"):
            validate_stable_release_channel(version, as_prerelease=False)


def test_5_2_preview_and_other_lines_are_allowed() -> None:
    validate_stable_release_channel("v5.2.0", as_prerelease=True)
    validate_stable_release_channel("v5.1.6", as_prerelease=False)
    validate_stable_release_channel("v5.3.0", as_prerelease=False)
