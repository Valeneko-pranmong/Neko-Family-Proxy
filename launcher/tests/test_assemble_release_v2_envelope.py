from __future__ import annotations

import hashlib
import sys
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from tests.software_update_helpers import valid_v2_release_document


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes_raw()
    return priv, pub_bytes


def test_canonicalize_release_v2_payload_happy_path():
    from assemble_release_v2_envelope import canonicalize_release_v2_payload
    from neko_launcher.updater.canonical_json import canonical_json_loads

    doc = valid_v2_release_document(sequence=1, release_id="test-rel-0001")
    payload_bytes = canonicalize_release_v2_payload(doc)

    assert not payload_bytes.endswith(b"\n")
    decoded = canonical_json_loads(payload_bytes)
    assert decoded["release_id"] == "test-rel-0001"
    assert decoded["release_sequence"] == 1


def test_canonicalize_release_v2_payload_negative():
    from assemble_release_v2_envelope import canonicalize_release_v2_payload

    with pytest.raises(ValueError):
        canonicalize_release_v2_payload({"schema_version": 999})


def test_assemble_verified_release_v2_envelope_happy_path():
    from assemble_release_v2_envelope import (
        assemble_verified_release_v2_envelope,
        canonicalize_release_v2_payload,
    )
    from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2

    priv, pub = _make_keypair()
    key_id = "test-release-key-1"
    keys = {key_id: pub}

    doc = valid_v2_release_document(sequence=1, release_id="test-rel-0001")
    payload_bytes = canonicalize_release_v2_payload(doc)
    detached_sig = priv.sign(payload_bytes)

    envelope_bytes = assemble_verified_release_v2_envelope(
        payload_bytes=payload_bytes,
        key_id=key_id,
        detached_signature=detached_sig,
        release_public_keys=keys,
    )

    assert envelope_bytes.endswith(b"\n")
    import json
    envelope_doc = json.loads(envelope_bytes.decode("utf-8"))
    release_set, returned_sha = verify_release_envelope_v2(envelope_doc, keys)
    assert release_set.release_id == "test-rel-0001"
    assert returned_sha == hashlib.sha256(payload_bytes).hexdigest()


def test_assemble_verified_release_v2_envelope_negative():
    from assemble_release_v2_envelope import (
        assemble_verified_release_v2_envelope,
        canonicalize_release_v2_payload,
    )

    priv, pub = _make_keypair()
    key_id = "test-release-key-1"
    keys = {key_id: pub}

    doc = valid_v2_release_document(sequence=1, release_id="test-rel-0001")
    payload_bytes = canonicalize_release_v2_payload(doc)

    # Wrong signature length
    with pytest.raises(ValueError, match="signature length"):
        assemble_verified_release_v2_envelope(
            payload_bytes=payload_bytes,
            key_id=key_id,
            detached_signature=b"\x00" * 32,
            release_public_keys=keys,
        )

    # Corrupted signature
    with pytest.raises(ValueError, match="Invalid signature"):
        assemble_verified_release_v2_envelope(
            payload_bytes=payload_bytes,
            key_id=key_id,
            detached_signature=b"\x00" * 64,
            release_public_keys=keys,
        )

    # Unknown key_id
    detached_sig = priv.sign(payload_bytes)
    with pytest.raises(ValueError, match="Unknown key_id"):
        assemble_verified_release_v2_envelope(
            payload_bytes=payload_bytes,
            key_id="unknown-key",
            detached_signature=detached_sig,
            release_public_keys=keys,
        )


def test_assemble_release_v2_envelope_cli_has_no_signer_inputs():
    import assemble_release_v2_envelope

    parser = getattr(assemble_release_v2_envelope, "build_parser", None)
    if parser is not None:
        p = parser()
        for a in p._actions:
            for opt in a.option_strings:
                assert "private" not in opt.lower()
                assert "secret" not in opt.lower()
                assert "sign" not in opt.lower() or opt == "--detached-signature"
