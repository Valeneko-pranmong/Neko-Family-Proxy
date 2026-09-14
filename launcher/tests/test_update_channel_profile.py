from __future__ import annotations

import pytest

from neko_launcher.updater.trust_profile import VerifiedUpdateTrustProfile


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


def test_update_channel_profile_production():
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

    channel_profile = UpdateChannelProfile.from_verified(verified)
    assert channel_profile.profile_id == "production"
    assert channel_profile.latest_release_api == (
        "https://api.github.com/repos/Valeneko-pranmong/Neko-Family-Proxy-Updates/releases/latest"
    )
    assert channel_profile.browser_download_prefix == (
        "/Valeneko-pranmong/Neko-Family-Proxy-Updates/releases/download/"
    )
