from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from neko_launcher.updater.canonical_json import canonical_json_dumps  # noqa: E402
from scripts.core_authority_custody import (  # noqa: E402
    CANONICAL_V512_CORE_AUTHORITY_EXPECTED,
    ArtifactIdentity,
    CoreAuthorityBinding,
    VerifiedCoreAuthority,
    bootstrap_core_authority_custody,
    compute_core_provenance_sha256,
    load_verified_core_authority,
)


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub_bytes


def _make_synthetic_core_bundle(
    *,
    source_commit: str = "6ab94bb",
    corrupt_manifest: bool = False,
    corrupt_file: bool = False,
) -> tuple[bytes, str, int, str]:
    mandatory_paths = [
        "NekoProxyCore.exe",
        "NekoProxyCore.dll",
        "runtime-settings.nkps",
        "bin/Redirector.bin",
        "bin/nfapi.dll",
        "bin/v2ray-sn.exe",
    ]
    files_list = []
    for p in mandatory_paths:
        files_list.append({
            "path": p,
            "sha256": hashlib.sha256(b"dummy-content-" + p.encode("utf-8")).hexdigest(),
            "size": len(b"dummy-content-" + p.encode("utf-8")),
        })

    manifest_obj = {
        "source_commit": source_commit,
        "rid": "win-x64",
        "executable": "NekoProxyCore.exe",
        "files": files_list,
    }
    manifest_bytes = canonical_json_dumps(manifest_obj)
    if corrupt_manifest:
        manifest_bytes = b"invalid json"

    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    import io

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("core-manifest.json", manifest_bytes)
        for entry in files_list:
            p = entry["path"]
            file_bytes = b"corrupt-bytes" if corrupt_file else (b"dummy-content-" + p.encode("utf-8"))
            zf.writestr(p, file_bytes)

    zip_bytes = bio.getvalue()
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    zip_size = len(zip_bytes)
    return zip_bytes, zip_sha, zip_size, manifest_sha


def _make_synthetic_envelope(
    *,
    priv_key: Ed25519PrivateKey,
    key_id: str,
    seq: int = 6,
    release_id: str = "stable-0006",
    version: str = "5.1.2",
    core_sha: str,
    core_size: int,
    installed_identity: str,
    corrupt_signature: bool = False,
) -> tuple[bytes, str, str]:
    payload = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": seq,
        "release_id": release_id,
        "mandatory": False,
        "minimum_supported_sequence": 1,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "artifact_id": "NekoLauncher.exe",
                "version": version,
                "artifact_sha256": "1" * 64,
                "artifact_size": 1000,
                "installed_identity_sha256": "1" * 64,
                "artifact_format": "raw-pe-v1",
            },
            "updater": {
                "artifact_id": "NekoUpdater.exe",
                "version": version,
                "artifact_sha256": "2" * 64,
                "artifact_size": 2000,
                "installed_identity_sha256": "2" * 64,
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "artifact_id": "NekoProxyCore.zip",
                "version": version,
                "artifact_sha256": core_sha,
                "artifact_size": core_size,
                "installed_identity_sha256": installed_identity,
                "artifact_format": "zip-core-v1",
            },
        },
    }
    payload_bytes = canonical_json_dumps(payload)
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()

    sig = priv_key.sign(payload_bytes)
    if corrupt_signature:
        sig = bytes([b ^ 0xFF for b in sig])

    envelope = {
        "envelope_version": 1,
        "key_id": key_id,
        "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(sig).decode("ascii"),
    }
    envelope_bytes = canonical_json_dumps(envelope)
    envelope_sha = hashlib.sha256(envelope_bytes).hexdigest()
    return envelope_bytes, envelope_sha, payload_sha


def test_canonical_v512_expected_constants():
    exp = CANONICAL_V512_CORE_AUTHORITY_EXPECTED
    assert exp.authority_version_tag == "v5.1.2"
    assert exp.authority_release_sequence == 6
    assert exp.authority_release_id == "stable-0006"
    assert exp.authority_payload_sha256 == "1ae606758302f485c8f31f324eafedeb9c182f8f0f9ab0b7bdd82bc4eab94c9f"
    assert exp.authority_envelope_sha256 == "989b0469baaa819ff619b5a83a59df5a0cd5669a80d43285f2d36bd9bb392b38"
    assert exp.authority_key_id == "neko-update-prod-1"
    assert exp.core_source_commit == "6ab94bb"
    prov = compute_core_provenance_sha256(
        authority_version_tag=exp.authority_version_tag,
        authority_release_sequence=exp.authority_release_sequence,
        authority_release_id=exp.authority_release_id,
        authority_payload_sha256=exp.authority_payload_sha256,
        authority_envelope_sha256=exp.authority_envelope_sha256,
        authority_key_id=exp.authority_key_id,
        core_source_commit=exp.core_source_commit,
    )
    assert exp.provenance_sha256 == prov


def test_bootstrap_and_load_synthetic_happy_path(tmp_path: Path):
    priv, pub = _make_keypair()
    key_id = "test-prod-key-1"
    keys = {key_id: pub}

    zip_bytes, zip_sha, zip_size, inst_id = _make_synthetic_core_bundle(source_commit="6ab94bb")
    env_bytes, env_sha, pay_sha = _make_synthetic_envelope(
        priv_key=priv,
        key_id=key_id,
        seq=6,
        release_id="stable-0006",
        version="5.1.2",
        core_sha=zip_sha,
        core_size=zip_size,
        installed_identity=inst_id,
    )

    src_env = tmp_path / "src_env.json"
    src_env.write_bytes(env_bytes)
    src_core = tmp_path / "src_core.zip"
    src_core.write_bytes(zip_bytes)

    prov = compute_core_provenance_sha256(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
    )
    expected_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
        provenance_sha256=prov,
    )

    custody_dir = tmp_path / "custody"
    verified = bootstrap_core_authority_custody(
        source_envelope=src_env,
        source_core_zip=src_core,
        custody_root=custody_dir,
        trusted_public_keys=keys,
        expected=expected_binding,
    )

    assert isinstance(verified, VerifiedCoreAuthority)
    assert isinstance(verified.core, ArtifactIdentity)
    assert verified.binding == expected_binding
    assert verified.core_zip_path == custody_dir / "NekoProxyCore.zip"
    assert verified.core.artifact_id == "NekoProxyCore.zip"
    assert verified.core.version == "5.1.2"
    assert verified.core.sha256 == zip_sha
    assert verified.core.size == zip_size
    assert verified.core.installed_identity_sha256 == inst_id
    assert verified.core.artifact_format == "zip-core-v1"

    # Idempotent re-bootstrap
    verified2 = bootstrap_core_authority_custody(
        source_envelope=src_env,
        source_core_zip=src_core,
        custody_root=custody_dir,
        trusted_public_keys=keys,
        expected=expected_binding,
    )
    assert verified2.binding == verified.binding
    assert verified2.core == verified.core

    # Fresh load
    loaded = load_verified_core_authority(custody_dir, trusted_public_keys=keys)
    assert loaded == verified


def test_bootstrap_rejects_preexisting_mismatch(tmp_path: Path):
    priv, pub = _make_keypair()
    key_id = "test-prod-key-1"
    keys = {key_id: pub}

    zip_bytes, zip_sha, zip_size, inst_id = _make_synthetic_core_bundle(source_commit="6ab94bb")
    env_bytes, env_sha, pay_sha = _make_synthetic_envelope(
        priv_key=priv,
        key_id=key_id,
        seq=6,
        release_id="stable-0006",
        version="5.1.2",
        core_sha=zip_sha,
        core_size=zip_size,
        installed_identity=inst_id,
    )

    src_env = tmp_path / "src_env.json"
    src_env.write_bytes(env_bytes)
    src_core = tmp_path / "src_core.zip"
    src_core.write_bytes(zip_bytes)

    prov = compute_core_provenance_sha256(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
    )
    expected_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
        provenance_sha256=prov,
    )

    custody_dir = tmp_path / "custody"
    bootstrap_core_authority_custody(
        source_envelope=src_env,
        source_core_zip=src_core,
        custody_root=custody_dir,
        trusted_public_keys=keys,
        expected=expected_binding,
    )

    # Mutated expected binding
    mutated_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=7,
        authority_release_id="stable-0007",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
        provenance_sha256=prov,
    )
    with pytest.raises(ValueError, match="(?i)mismatch"):
        bootstrap_core_authority_custody(
            source_envelope=src_env,
            source_core_zip=src_core,
            custody_root=custody_dir,
            trusted_public_keys=keys,
            expected=mutated_binding,
        )


def test_load_rejects_corrupted_signature(tmp_path: Path):
    priv, pub = _make_keypair()
    key_id = "test-prod-key-1"
    keys = {key_id: pub}

    zip_bytes, zip_sha, zip_size, inst_id = _make_synthetic_core_bundle(source_commit="6ab94bb")
    env_bytes, env_sha, pay_sha = _make_synthetic_envelope(
        priv_key=priv,
        key_id=key_id,
        seq=6,
        release_id="stable-0006",
        version="5.1.2",
        core_sha=zip_sha,
        core_size=zip_size,
        installed_identity=inst_id,
    )

    src_env = tmp_path / "src_env.json"
    src_env.write_bytes(env_bytes)
    src_core = tmp_path / "src_core.zip"
    src_core.write_bytes(zip_bytes)

    prov = compute_core_provenance_sha256(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
    )
    expected_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
        provenance_sha256=prov,
    )

    custody_dir = tmp_path / "custody"
    bootstrap_core_authority_custody(
        source_envelope=src_env,
        source_core_zip=src_core,
        custody_root=custody_dir,
        trusted_public_keys=keys,
        expected=expected_binding,
    )

    # Corrupt the envelope's signature
    env_path = custody_dir / "release-v2.json"
    env_data = json.loads(env_path.read_text(encoding="utf-8"))
    sig_raw = base64.b64decode(env_data["signature_b64"])
    corrupted_sig = bytes([b ^ 0xFF for b in sig_raw])
    env_data["signature_b64"] = base64.b64encode(corrupted_sig).decode("ascii")
    env_path.write_bytes(canonical_json_dumps(env_data))

    with pytest.raises((ValueError, RuntimeError)):
        load_verified_core_authority(custody_dir, trusted_public_keys=keys)


def test_load_rejects_source_commit_mismatch(tmp_path: Path):
    priv, pub = _make_keypair()
    key_id = "test-prod-key-1"
    keys = {key_id: pub}

    zip_bytes, zip_sha, zip_size, inst_id = _make_synthetic_core_bundle(source_commit="different-commit")
    env_bytes, env_sha, pay_sha = _make_synthetic_envelope(
        priv_key=priv,
        key_id=key_id,
        seq=6,
        release_id="stable-0006",
        version="5.1.2",
        core_sha=zip_sha,
        core_size=zip_size,
        installed_identity=inst_id,
    )

    src_env = tmp_path / "src_env.json"
    src_env.write_bytes(env_bytes)
    src_core = tmp_path / "src_core.zip"
    src_core.write_bytes(zip_bytes)

    prov = compute_core_provenance_sha256(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
    )
    expected_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
        provenance_sha256=prov,
    )

    custody_dir = tmp_path / "custody"
    # Bootstrap should fail because source commit in zip does not match expected_binding
    with pytest.raises(ValueError, match="(?i)source_commit"):
        bootstrap_core_authority_custody(
            source_envelope=src_env,
            source_core_zip=src_core,
            custody_root=custody_dir,
            trusted_public_keys=keys,
            expected=expected_binding,
        )


def test_load_rejects_non_canonical_metadata(tmp_path: Path):
    priv, pub = _make_keypair()
    key_id = "test-prod-key-1"
    keys = {key_id: pub}

    zip_bytes, zip_sha, zip_size, inst_id = _make_synthetic_core_bundle(source_commit="6ab94bb")
    env_bytes, env_sha, pay_sha = _make_synthetic_envelope(
        priv_key=priv,
        key_id=key_id,
        seq=6,
        release_id="stable-0006",
        version="5.1.2",
        core_sha=zip_sha,
        core_size=zip_size,
        installed_identity=inst_id,
    )

    src_env = tmp_path / "src_env.json"
    src_env.write_bytes(env_bytes)
    src_core = tmp_path / "src_core.zip"
    src_core.write_bytes(zip_bytes)

    prov = compute_core_provenance_sha256(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
    )
    expected_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit="6ab94bb",
        provenance_sha256=prov,
    )

    custody_dir = tmp_path / "custody"
    bootstrap_core_authority_custody(
        source_envelope=src_env,
        source_core_zip=src_core,
        custody_root=custody_dir,
        trusted_public_keys=keys,
        expected=expected_binding,
    )

    # Tamper with core-authority-v1.json to make it non-canonical
    meta_path = custody_dir / "core-authority-v1.json"
    meta_bytes = meta_path.read_bytes()
    meta_path.write_bytes(b"   " + meta_bytes)

    with pytest.raises(ValueError, match="(?i)canonical"):
        load_verified_core_authority(custody_dir, trusted_public_keys=keys)
