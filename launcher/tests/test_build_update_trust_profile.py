from __future__ import annotations

import sys
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Add scripts directory to path for import
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes_raw()
    return priv, pub_bytes


def test_canonicalize_profile_payload_happy_path():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        canonicalize_profile_payload,
    )
    from neko_launcher.updater.canonical_json import canonical_json_loads

    _, pub1 = _make_keypair()
    _, pub2 = _make_keypair()
    keys = sorted(
        [
            {"key_id": "key-1", "public_key_hex": pub1.hex()},
            {"key_id": "key-2", "public_key_hex": pub2.hex()},
        ],
        key=lambda k: k["key_id"],
    )

    spec = UpdateTrustProfileSpec(
        profile_id="proof-v512",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates-Proof",
        release_keys=keys,
    )

    payload_bytes = canonicalize_profile_payload(spec)
    assert not payload_bytes.endswith(b"\n")

    decoded = canonical_json_loads(payload_bytes)
    assert decoded["profile_id"] == "proof-v512"
    assert decoded["channel"] == "stable"
    assert decoded["owner"] == "Valeneko-pranmong"
    assert decoded["repository"] == "Neko-Family-Proxy-Updates-Proof"
    assert decoded["release_keys"] == keys


def test_canonicalize_profile_payload_negative():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        canonicalize_profile_payload,
    )

    _, pub = _make_keypair()

    # Empty keys
    with pytest.raises(ValueError):
        canonicalize_profile_payload(
            UpdateTrustProfileSpec(
                profile_id="proof-v512",
                channel="stable",
                owner="Valeneko-pranmong",
                repository="Neko-Family-Proxy-Updates-Proof",
                release_keys=[],
            )
        )

    # Production with proof key
    with pytest.raises(ValueError, match="proof"):
        canonicalize_profile_payload(
            UpdateTrustProfileSpec(
                profile_id="production",
                channel="stable",
                owner="Valeneko-pranmong",
                repository="Neko-Family-Proxy",
                release_keys=[{"key_id": "neko-update-proof-1", "public_key_hex": pub.hex()}],
            )
        )


def test_canonicalize_profile_payload_production_accepts_canonical_repository():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        canonicalize_profile_payload,
    )
    from neko_launcher.updater.canonical_json import canonical_json_loads

    _, pub = _make_keypair()
    spec = UpdateTrustProfileSpec(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy",
        release_keys=[{"key_id": "neko-update-prod-1", "public_key_hex": pub.hex()}],
    )
    payload_bytes = canonicalize_profile_payload(spec)
    decoded = canonical_json_loads(payload_bytes)
    assert decoded["profile_id"] == "production"
    assert decoded["owner"] == "Valeneko-pranmong"
    assert decoded["repository"] == "Neko-Family-Proxy"


def test_canonicalize_profile_payload_production_rejects_superseded_updates_repository():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        canonicalize_profile_payload,
    )

    _, pub = _make_keypair()
    spec = UpdateTrustProfileSpec(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates",
        release_keys=[{"key_id": "neko-update-prod-1", "public_key_hex": pub.hex()}],
    )
    with pytest.raises(ValueError, match="superseded|Neko-Family-Proxy-Updates"):
        canonicalize_profile_payload(spec)


def test_canonicalize_profile_payload_production_rejects_arbitrary_repository():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        canonicalize_profile_payload,
    )

    _, pub = _make_keypair()
    spec = UpdateTrustProfileSpec(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="ArbitraryRepo",
        release_keys=[{"key_id": "neko-update-prod-1", "public_key_hex": pub.hex()}],
    )
    with pytest.raises(ValueError, match="repository mismatch|expected"):
        canonicalize_profile_payload(spec)


def test_canonicalize_profile_payload_production_rejects_arbitrary_owner():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        canonicalize_profile_payload,
    )

    _, pub = _make_keypair()
    spec = UpdateTrustProfileSpec(
        profile_id="production",
        channel="stable",
        owner="ArbitraryOwner",
        repository="Neko-Family-Proxy",
        release_keys=[{"key_id": "neko-update-prod-1", "public_key_hex": pub.hex()}],
    )
    with pytest.raises(ValueError, match="repository mismatch|owner|expected"):
        canonicalize_profile_payload(spec)



def test_assemble_verified_profile_envelope_happy_path():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        assemble_verified_profile_envelope,
        canonicalize_profile_payload,
    )
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    auth_keys = {auth_key_id: auth_pub}

    _, rel_pub = _make_keypair()
    spec = UpdateTrustProfileSpec(
        profile_id="proof-v512",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates-Proof",
        release_keys=[{"key_id": "rel-1", "public_key_hex": rel_pub.hex()}],
    )
    payload_bytes = canonicalize_profile_payload(spec)
    detached_sig = auth_priv.sign(payload_bytes)

    envelope_bytes = assemble_verified_profile_envelope(
        payload_bytes=payload_bytes,
        profile_authority_key_id=auth_key_id,
        detached_signature=detached_sig,
        profile_authority_public_keys=auth_keys,
    )

    assert envelope_bytes.endswith(b"\n")
    profile = verify_update_trust_profile(envelope_bytes, profile_authority_public_keys=auth_keys)
    assert profile.profile_id == "proof-v512"
    assert profile.profile_authority_key_id == auth_key_id


def test_assemble_verified_profile_envelope_negative():
    from build_update_trust_profile import (
        UpdateTrustProfileSpec,
        assemble_verified_profile_envelope,
        canonicalize_profile_payload,
    )

    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    auth_keys = {auth_key_id: auth_pub}

    _, rel_pub = _make_keypair()
    spec = UpdateTrustProfileSpec(
        profile_id="proof-v512",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates-Proof",
        release_keys=[{"key_id": "rel-1", "public_key_hex": rel_pub.hex()}],
    )
    payload_bytes = canonicalize_profile_payload(spec)

    # Wrong signature length
    with pytest.raises(ValueError, match="signature length"):
        assemble_verified_profile_envelope(
            payload_bytes=payload_bytes,
            profile_authority_key_id=auth_key_id,
            detached_signature=b"\x00" * 32,
            profile_authority_public_keys=auth_keys,
        )

    # Invalid signature bytes
    with pytest.raises(ValueError, match="Invalid signature"):
        assemble_verified_profile_envelope(
            payload_bytes=payload_bytes,
            profile_authority_key_id=auth_key_id,
            detached_signature=b"\x00" * 64,
            profile_authority_public_keys=auth_keys,
        )


def test_build_update_trust_profile_cli_has_no_private_key_or_signer_inputs():
    import build_update_trust_profile

    # Inspect module source or argument parser
    parser = getattr(build_update_trust_profile, "build_parser", None)
    if parser is not None:
        p = parser()
        actions = p._actions
        for a in actions:
            for opt in a.option_strings:
                assert "private" not in opt.lower()
                assert "secret" not in opt.lower()
                assert "sign" not in opt.lower() or opt == "--detached-signature"
