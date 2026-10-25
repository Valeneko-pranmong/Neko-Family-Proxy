from __future__ import annotations

from pathlib import Path

import pytest

from neko_launcher.updater.trust import PROFILE_AUTHORITY_PUBLIC_KEYS
from neko_launcher.updater.trust_profile import (
    VerifiedUpdateTrustProfile,
    verify_update_trust_profile,
)


def test_committed_preview_profile_is_signed_and_preview_only() -> None:
    profile_path = (
        Path(__file__).parents[2] / "trust" / "update-profile-preview-v1.json"
    )
    verified = verify_update_trust_profile(
        profile_path.read_bytes(),
        profile_authority_public_keys=PROFILE_AUTHORITY_PUBLIC_KEYS,
    )

    assert verified.profile_id == "preview"
    assert verified.channel == "preview"
    assert verified.owner == "Valeneko-pranmong"
    assert verified.repository == "Neko-Family-Proxy"
    assert set(verified.release_public_keys) == {"neko-update-prod-2"}


def test_update_channel_profile_from_verified_happy_path():
    from neko_launcher.infrastructure.update_channel_profile import UpdateChannelProfile

    verified = VerifiedUpdateTrustProfile(
        profile_id="proof-v512",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates-Proof",
        release_public_keys={"key-1": b"\x01" * 32},
        keyset_sha256="1" * 64,
        profile_envelope_sha256="2" * 64,
        profile_authority_key_id="auth-1",
        profile_authority_public_key_sha256="3" * 64,
    )

    channel_profile = UpdateChannelProfile.from_verified(verified)

    assert channel_profile.profile_id == "proof-v512"
    assert channel_profile.channel == "stable"
    assert channel_profile.owner == "Valeneko-pranmong"
    assert channel_profile.repository == "Neko-Family-Proxy-Updates-Proof"
    assert channel_profile.release_public_keys["key-1"] == b"\x01" * 32

    assert channel_profile.latest_release_api == (
        "https://api.github.com/repos/Valeneko-pranmong/Neko-Family-Proxy-Updates-Proof/releases/latest"
    )
    assert channel_profile.browser_download_prefix == (
        "/Valeneko-pranmong/Neko-Family-Proxy-Updates-Proof/releases/download/"
    )

    # Immutability of release_public_keys
    with pytest.raises((TypeError, AttributeError)):
        channel_profile.release_public_keys["key-2"] = b"\x02" * 32


def test_update_channel_profile_preview_uses_release_list():
    from neko_launcher.infrastructure.update_channel_profile import UpdateChannelProfile

    verified = VerifiedUpdateTrustProfile(
        profile_id="preview",
        channel="preview",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy",
        release_public_keys={"key-1": b"\x01" * 32},
        keyset_sha256="1" * 64,
        profile_envelope_sha256="2" * 64,
        profile_authority_key_id="auth-1",
        profile_authority_public_key_sha256="3" * 64,
    )

    channel_profile = UpdateChannelProfile.from_verified(verified)

    assert channel_profile.is_preview is True
    assert channel_profile.releases_api == (
        "https://api.github.com/repos/Valeneko-pranmong/"
        "Neko-Family-Proxy/releases?per_page=100"
    )
    assert channel_profile.latest_release_api.endswith("/releases/latest")


def test_update_channel_profile_production():
    from neko_launcher.infrastructure.update_channel_profile import UpdateChannelProfile

    verified = VerifiedUpdateTrustProfile(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy",
        release_public_keys={"neko-update-prod-1": b"\x09" * 32},
        keyset_sha256="1" * 64,
        profile_envelope_sha256="2" * 64,
        profile_authority_key_id="auth-1",
        profile_authority_public_key_sha256="3" * 64,
    )

    channel_profile = UpdateChannelProfile.from_verified(verified)
    assert channel_profile.profile_id == "production"
    assert channel_profile.owner == "Valeneko-pranmong"
    assert channel_profile.repository == "Neko-Family-Proxy"
    assert channel_profile.release_public_keys["neko-update-prod-1"] == b"\x09" * 32
    assert channel_profile.latest_release_api == (
        "https://api.github.com/repos/Valeneko-pranmong/Neko-Family-Proxy/releases/latest"
    )
    assert channel_profile.browser_download_prefix == (
        "/Valeneko-pranmong/Neko-Family-Proxy/releases/download/"
    )


def test_update_channel_profile_production_rejects_superseded_updates_repository():
    from neko_launcher.infrastructure.update_channel_profile import UpdateChannelProfile

    verified = VerifiedUpdateTrustProfile(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates",
        release_public_keys={"neko-update-prod-1": b"\x09" * 32},
        keyset_sha256="1" * 64,
        profile_envelope_sha256="2" * 64,
        profile_authority_key_id="auth-1",
        profile_authority_public_key_sha256="3" * 64,
    )

    with pytest.raises(ValueError, match="superseded|Neko-Family-Proxy-Updates"):
        UpdateChannelProfile.from_verified(verified)
