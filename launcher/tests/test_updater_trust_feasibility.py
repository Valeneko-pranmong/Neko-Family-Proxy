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

    all_entries = dict(files)
    all_entries["core-manifest.json"] = manifest_bytes

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in sorted(all_entries.keys()):
            zinfo = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            zinfo.compress_type = zipfile.ZIP_STORED
            zinfo.external_attr = 0o644 << 16
            zf.writestr(zinfo, all_entries[name])

    zip_bytes = zip_path.read_bytes()
    return zip_bytes, hashlib.sha256(zip_bytes).hexdigest(), len(zip_bytes)


def test_deterministic_candidate_fixture(tmp_path):
    core_dir = tmp_path / "core"
    zip_path = tmp_path / "NekoProxyCore.zip"
    zip_bytes, sha, size = build_deterministic_candidate_core(core_dir, zip_path)

    assert size == len(zip_bytes)
    assert sha == hashlib.sha256(zip_bytes).hexdigest()
    assert verify_canonical_core_bundle(core_dir).valid is True


def test_deterministic_candidate_fixture_strict_reproducibility(tmp_path):
    core1 = tmp_path / "c1" / "core"
    zip1 = tmp_path / "c1" / "NekoProxyCore.zip"
    core2 = tmp_path / "c2" / "core"
    zip2 = tmp_path / "c2" / "NekoProxyCore.zip"

    bytes1, sha1, size1 = build_deterministic_candidate_core(core1, zip1)
    bytes2, sha2, size2 = build_deterministic_candidate_core(core2, zip2)

    assert bytes1 == bytes2
    assert sha1 == sha2
    assert size1 == size2

    expected_entries = sorted([
        "NekoProxyCore.exe",
        "NekoProxyCore.dll",
        "runtime-settings.nkps",
        "bin/Redirector.bin",
        "bin/nfapi.dll",
        "bin/v2ray-sn.exe",
        "core-manifest.json",
    ])

    with zipfile.ZipFile(zip1, "r") as zf:
        infolist = zf.infolist()
        entry_names = [info.filename for info in infolist]
        assert entry_names == expected_entries
        for info in infolist:
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert (info.external_attr >> 16) & 0o120000 != 0o120000
            assert (info.external_attr >> 16) & 0o100000 == 0o100000 or (info.external_attr >> 16) == 0o644


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
