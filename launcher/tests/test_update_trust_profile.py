from __future__ import annotations

import base64
import hashlib
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from neko_launcher.updater.canonical_json import canonical_json_dumps


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes_raw()
    return priv, pub_bytes


def _make_profile_envelope(
    *,
    auth_priv: Ed25519PrivateKey,
    auth_key_id: str = "test-auth-key-1",
    profile_id: str = "proof-v512",
    channel: str = "stable",
    owner: str = "Valeneko-pranmong",
    repository: str = "Neko-Family-Proxy-Updates-Proof",
    release_keys: list[dict[str, str]] | None = None,
    corrupt_sig: bool = False,
    envelope_override: dict | None = None,
    trailing: bytes = b"\n",
) -> tuple[bytes, dict, bytes]:
    if release_keys is None:
        rel_priv, rel_pub = _make_keypair()
        release_keys = [{"key_id": "test-rel-1", "public_key_hex": rel_pub.hex()}]

    payload = {
        "channel": channel,
        "owner": owner,
        "profile_id": profile_id,
        "release_keys": release_keys,
        "repository": repository,
    }
    payload_bytes = canonical_json_dumps(payload)
    sig_bytes = auth_priv.sign(payload_bytes)
    if corrupt_sig:
        sig_bytes = bytes([b ^ 0xFF for b in sig_bytes])

    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

    envelope = {
        "key_id": auth_key_id,
        "payload": payload,
        "schema_version": 1,
        "signature_b64": sig_b64,
    }
    if envelope_override is not None:
        envelope.update(envelope_override)

    raw = canonical_json_dumps(envelope) + trailing
    return raw, envelope, payload_bytes


def test_verify_update_trust_profile_happy_path():
    from neko_launcher.updater.trust_profile import (
        VerifiedUpdateTrustProfile,
        verify_update_trust_profile,
    )

    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    rel_priv, rel_pub = _make_keypair()
    release_keys = [{"key_id": "test-rel-1", "public_key_hex": rel_pub.hex()}]

    raw, envelope, payload_bytes = _make_profile_envelope(
        auth_priv=auth_priv,
        auth_key_id=auth_key_id,
        profile_id="proof-v512",
        release_keys=release_keys,
    )

    auth_keys = {auth_key_id: auth_pub}
    profile = verify_update_trust_profile(raw, profile_authority_public_keys=auth_keys)

    assert isinstance(profile, VerifiedUpdateTrustProfile)
    assert profile.profile_id == "proof-v512"
    assert profile.channel == "stable"
    assert profile.owner == "Valeneko-pranmong"
    assert profile.repository == "Neko-Family-Proxy-Updates-Proof"
    assert profile.profile_authority_key_id == auth_key_id
    assert profile.profile_authority_public_key_sha256 == hashlib.sha256(auth_pub).hexdigest()
    assert profile.profile_envelope_sha256 == hashlib.sha256(raw).hexdigest()

    expected_keyset_sha = hashlib.sha256(
        canonical_json_dumps({"release_keys": release_keys})
    ).hexdigest()
    assert profile.keyset_sha256 == expected_keyset_sha
    assert profile.release_public_keys["test-rel-1"] == rel_pub

    # Immutability
    with pytest.raises(TypeError):
        profile.release_public_keys["new_key"] = b"\x00" * 32


def test_verify_update_trust_profile_negative_newlines_and_whitespace():
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    auth_keys = {auth_key_id: auth_pub}

    # Missing terminal LF
    raw_no_lf, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, trailing=b"")
    with pytest.raises(ValueError, match="terminal LF"):
        verify_update_trust_profile(raw_no_lf, profile_authority_public_keys=auth_keys)

    # CRLF
    raw_crlf, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, trailing=b"\r\n")
    with pytest.raises(ValueError, match="terminal LF"):
        verify_update_trust_profile(raw_crlf, profile_authority_public_keys=auth_keys)

    # Double LF
    raw_dbl_lf, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, trailing=b"\n\n")
    with pytest.raises(ValueError, match="terminal LF"):
        verify_update_trust_profile(raw_dbl_lf, profile_authority_public_keys=auth_keys)

    # Leading whitespace
    raw_valid, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id)
    with pytest.raises(ValueError):
        verify_update_trust_profile(b" " + raw_valid, profile_authority_public_keys=auth_keys)

    # Trailing whitespace before LF
    with pytest.raises(ValueError):
        verify_update_trust_profile(raw_valid[:-1] + b" \n", profile_authority_public_keys=auth_keys)

    # UTF-8 BOM
    with pytest.raises(ValueError):
        verify_update_trust_profile(b"\xef\xbb\xbf" + raw_valid, profile_authority_public_keys=auth_keys)


def test_verify_update_trust_profile_negative_schema_and_fields():
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    auth_keys = {auth_key_id: auth_pub}

    # Field 'signature' instead of 'signature_b64'
    raw, env, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id)
    bad_env = dict(env)
    bad_env["signature"] = bad_env.pop("signature_b64")
    raw_bad = canonical_json_dumps(bad_env) + b"\n"
    with pytest.raises(ValueError):
        verify_update_trust_profile(raw_bad, profile_authority_public_keys=auth_keys)

    # Unknown envelope field
    bad_env2 = dict(env)
    bad_env2["extra"] = "forbidden"
    raw_extra = canonical_json_dumps(bad_env2) + b"\n"
    with pytest.raises(ValueError):
        verify_update_trust_profile(raw_extra, profile_authority_public_keys=auth_keys)

    # Wrong schema version
    bad_env3 = dict(env)
    bad_env3["schema_version"] = 2
    raw_v2 = canonical_json_dumps(bad_env3) + b"\n"
    with pytest.raises(ValueError):
        verify_update_trust_profile(raw_v2, profile_authority_public_keys=auth_keys)

    # Unknown authority key_id
    with pytest.raises(ValueError, match="Unknown authority key_id"):
        verify_update_trust_profile(raw, profile_authority_public_keys={"other-key": auth_pub})


def test_verify_update_trust_profile_negative_signatures():
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    auth_keys = {auth_key_id: auth_pub}

    # Corrupt signature bytes
    raw_corrupt, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, corrupt_sig=True)
    with pytest.raises(ValueError, match="Invalid signature"):
        verify_update_trust_profile(raw_corrupt, profile_authority_public_keys=auth_keys)

    # Invalid base64
    raw, env, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id)
    bad_b64_env = dict(env)
    bad_b64_env["signature_b64"] = env["signature_b64"][:-2] + "!!"
    with pytest.raises(ValueError):
        verify_update_trust_profile(canonical_json_dumps(bad_b64_env) + b"\n", profile_authority_public_keys=auth_keys)

    # Wrong signature length (32 bytes instead of 64)
    short_b64_env = dict(env)
    short_b64_env["signature_b64"] = base64.b64encode(b"\x00" * 32).decode("ascii")
    with pytest.raises(ValueError, match="signature length"):
        verify_update_trust_profile(canonical_json_dumps(short_b64_env) + b"\n", profile_authority_public_keys=auth_keys)


def test_verify_update_trust_profile_negative_release_keys():
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    auth_priv, auth_pub = _make_keypair()
    auth_key_id = "test-auth-key-1"
    auth_keys = {auth_key_id: auth_pub}

    _, pub1 = _make_keypair()
    _, pub2 = _make_keypair()

    # Empty release_keys
    raw_empty, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, release_keys=[])
    with pytest.raises(ValueError, match="release_keys"):
        verify_update_trust_profile(raw_empty, profile_authority_public_keys=auth_keys)

    # Unsorted release_keys
    keys_unsorted = [
        {"key_id": "z-key", "public_key_hex": pub1.hex()},
        {"key_id": "a-key", "public_key_hex": pub2.hex()},
    ]
    raw_unsorted, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, release_keys=keys_unsorted)
    with pytest.raises(ValueError, match="sorted"):
        verify_update_trust_profile(raw_unsorted, profile_authority_public_keys=auth_keys)

    # Duplicate key_id
    keys_dup = [
        {"key_id": "a-key", "public_key_hex": pub1.hex()},
        {"key_id": "a-key", "public_key_hex": pub2.hex()},
    ]
    raw_dup, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, release_keys=keys_dup)
    with pytest.raises(ValueError):
        verify_update_trust_profile(raw_dup, profile_authority_public_keys=auth_keys)

    # Uppercase hex
    keys_upper = [{"key_id": "a-key", "public_key_hex": pub1.hex().upper()}]
    raw_upper, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, release_keys=keys_upper)
    with pytest.raises(ValueError, match="hex"):
        verify_update_trust_profile(raw_upper, profile_authority_public_keys=auth_keys)

    # Non-hex / wrong length
    keys_bad_len = [{"key_id": "a-key", "public_key_hex": "abcd"}]
    raw_bad_len, _, _ = _make_profile_envelope(auth_priv=auth_priv, auth_key_id=auth_key_id, release_keys=keys_bad_len)
    with pytest.raises(ValueError, match="hex"):
        verify_update_trust_profile(raw_bad_len, profile_authority_public_keys=auth_keys)

    # Production profile containing proof key
    keys_proof = [{"key_id": "neko-update-proof-v512-1", "public_key_hex": pub1.hex()}]
    raw_prod_with_proof, _, _ = _make_profile_envelope(
        auth_priv=auth_priv,
        auth_key_id=auth_key_id,
        profile_id="production",
        release_keys=keys_proof,
    )
    with pytest.raises(ValueError, match="proof"):
        verify_update_trust_profile(raw_prod_with_proof, profile_authority_public_keys=auth_keys)


def test_load_installed_update_trust_profile(tmp_path):
    from neko_launcher.updater.trust_profile import load_installed_update_trust_profile

    # Missing profile file
    with pytest.raises((FileNotFoundError, ValueError)):
        load_installed_update_trust_profile(tmp_path)

    # Non-trust folder
    trust_dir = tmp_path / "trust"
    trust_dir.mkdir(parents=True)
    profile_file = trust_dir / "update-profile-v1.json"

    # Write bad data
    profile_file.write_bytes(b"not json\n")
    with pytest.raises(ValueError):
        load_installed_update_trust_profile(tmp_path)
