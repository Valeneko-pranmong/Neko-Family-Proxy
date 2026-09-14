from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle
from neko_launcher.updater.manifest_v2 import (
    verify_release_envelope_v2,
)


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes_raw()
    return priv, pub_bytes


def build_deterministic_candidate_core(core_dir: Path, zip_path: Path) -> tuple[bytes, str, int]:
    core_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "NekoProxyCore.exe": b"proof-candidate-core-exe\n",
        "NekoProxyCore.dll": b"proof-candidate-core-dll\n",
        "runtime-settings.nkps": b"proof-candidate-runtime-settings\n",
        "bin/Redirector.bin": b"proof-candidate-redirector\n",
        "bin/nfapi.dll": b"proof-candidate-nfapi\n",
        "bin/v2ray-sn.exe": b"proof-candidate-v2ray-sn\n",
    }

    manifest_entries = []
    for rel_path, data in sorted(files.items()):
        fpath = core_dir / rel_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_bytes(data)
        manifest_entries.append({
            "path": rel_path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })

    manifest_obj = {
        "executable": "NekoProxyCore.exe",
        "files": manifest_entries,
        "rid": "win-x64",
        "source_commit": "k1-proof-candidate",
    }
    manifest_bytes = canonical_json_dumps(manifest_obj)
    (core_dir / "core-manifest.json").write_bytes(manifest_bytes)

    res = verify_canonical_core_bundle(core_dir)
    assert res.valid is True, f"Core bundle verification failed: {res.error}"

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("core-manifest.json", manifest_bytes)
        for rel_path in sorted(files.keys()):
            zf.writestr(rel_path, files[rel_path])

    zip_bytes = zip_path.read_bytes()
    return zip_bytes, hashlib.sha256(zip_bytes).hexdigest(), len(zip_bytes)


def test_deterministic_candidate_fixture(tmp_path):
    core_dir = tmp_path / "core"
    zip_path = tmp_path / "NekoProxyCore.zip"
    zip_bytes, sha, size = build_deterministic_candidate_core(core_dir, zip_path)

    assert size == len(zip_bytes)
    assert sha == hashlib.sha256(zip_bytes).hexdigest()
    assert verify_canonical_core_bundle(core_dir).valid is True


def test_cross_trust_rejection():
    # Production profile release key
    prod_priv, prod_pub = _make_keypair()
    prod_keys = {"neko-update-prod-1": prod_pub}

    # Proof profile release key
    proof_priv, proof_pub = _make_keypair()
    proof_keys = {"neko-update-proof-v512-1": proof_pub}

    payload = {
        "channel": "stable",
        "components": {
            "core": {
                "artifact_id": "NekoProxyCore.zip",
                "format": "zip-core-v1",
                "sha256": "0" * 64,
                "size": 100,
                "version": "5.1.3-proof",
            },
            "launcher": {
                "artifact_id": "NekoLauncher.exe",
                "format": "raw-pe-v1",
                "sha256": "1" * 64,
                "size": 100,
                "version": "5.1.3-proof",
            },
            "updater": {
                "artifact_id": "NekoUpdater.exe",
                "format": "raw-pe-v1",
                "sha256": "2" * 64,
                "size": 100,
                "version": "5.1.2",
            },
        },
        "mandatory": True,
        "minimum_supported_sequence": 2,
        "release_id": "proof-k1-0002",
        "release_sequence": 2,
        "schema_version": 2,
        "updater_protocol": {"maximum": 1, "minimum": 1},
    }
    payload_bytes = canonical_json_dumps(payload)

    # Sign with proof key
    proof_sig = proof_priv.sign(payload_bytes)
    proof_envelope = {
        "envelope_version": 1,
        "key_id": "neko-update-proof-v512-1",
        "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(proof_sig).decode("ascii"),
    }

    # Verify proof envelope under production keys -> must fail (Unknown key_id)
    with pytest.raises(ValueError, match="Unknown key_id"):
        verify_release_envelope_v2(proof_envelope, prod_keys)

    # Sign with prod key
    prod_sig = prod_priv.sign(payload_bytes)
    prod_envelope = {
        "envelope_version": 1,
        "key_id": "neko-update-prod-1",
        "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(prod_sig).decode("ascii"),
    }

    # Verify prod envelope under proof keys -> must fail (Unknown key_id)
    with pytest.raises(ValueError, match="Unknown key_id"):
        verify_release_envelope_v2(prod_envelope, proof_keys)
