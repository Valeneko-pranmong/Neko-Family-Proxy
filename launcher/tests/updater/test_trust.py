from pathlib import Path

from neko_launcher.updater.trust import (
    CURRENT_PROFILE_AUTHORITY_KEY_ID,
    CURRENT_PRODUCTION_RELEASE_KEY_ID,
    PRODUCTION_RELEASE_PUBLIC_KEYS,
    PROFILE_AUTHORITY_PUBLIC_KEYS,
)
from neko_launcher.updater.trust_profile import verify_update_trust_profile


def test_production_release_public_keys_include_current_and_historical_trust_anchors() -> None:
    assert CURRENT_PRODUCTION_RELEASE_KEY_ID in PRODUCTION_RELEASE_PUBLIC_KEYS
    assert "neko-update-prod-1" in PRODUCTION_RELEASE_PUBLIC_KEYS

    for public_key in PRODUCTION_RELEASE_PUBLIC_KEYS.values():
        assert isinstance(public_key, bytes)
        assert len(public_key) == 32

    assert all(
        "test" not in key_id.lower() and "placeholder" not in key_id.lower()
        for key_id in PRODUCTION_RELEASE_PUBLIC_KEYS
    )


def test_committed_production_profile_authorizes_only_the_current_release_key() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    raw = (repository_root / "trust" / "update-profile-v1.json").read_bytes()
    profile = verify_update_trust_profile(
        raw,
        profile_authority_public_keys=PROFILE_AUTHORITY_PUBLIC_KEYS,
    )

    assert profile.profile_id == "production"
    assert profile.channel == "stable"
    assert profile.repository == "Neko-Family-Proxy"
    assert profile.profile_authority_key_id == CURRENT_PROFILE_AUTHORITY_KEY_ID
    assert set(profile.release_public_keys) == {CURRENT_PRODUCTION_RELEASE_KEY_ID}
    assert "neko-update-prod-1" not in profile.release_public_keys
