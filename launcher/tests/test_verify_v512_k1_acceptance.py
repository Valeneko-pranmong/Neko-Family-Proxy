from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes_raw()
    return priv, pub_bytes


def _make_valid_core_zip(zip_path: Path) -> tuple[bytes, str]:
    core_files = {
        "NekoProxyCore.exe": b"test_exe_content\n",
        "NekoProxyCore.dll": b"test_dll_content\n",
        "runtime-settings.nkps": b"test_nkps_content\n",
        "bin/Redirector.bin": b"test_redir_content\n",
        "bin/nfapi.dll": b"test_nfapi_content\n",
        "bin/v2ray-sn.exe": b"test_v2ray_content\n",
    }
    manifest_files = []
    for path_str in sorted(core_files.keys()):
        content = core_files[path_str]
        manifest_files.append({
            "path": path_str,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        })
    manifest_doc = {
        "executable": "NekoProxyCore.exe",
        "files": manifest_files,
        "rid": "win-x64",
        "source_commit": "k1-proof-candidate",
    }
    manifest_bytes = canonical_json_dumps(manifest_doc)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    all_entries = dict(core_files)
    all_entries["core-manifest.json"] = manifest_bytes

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in sorted(all_entries.keys()):
            zinfo = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            zinfo.compress_type = zipfile.ZIP_STORED
            zinfo.external_attr = 0o644 << 16
            zf.writestr(zinfo, all_entries[name])

    return zip_path.read_bytes(), manifest_sha256


def test_verify_v512_k1_acceptance_schema_validation():
    from verify_v512_k1_acceptance import validate_acceptance_record_schema

    valid_record = {
        "schema_version": 1,
        "task_id": "RT1-K1",
        "rt1_code_head_sha": "a" * 40,
        "profile_authority_custody_sha256": "b" * 64,
        "proof_release_authority_custody_sha256": "c" * 64,
        "k1b_custody_path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\k1b-custody-v1.json",
        "k1b_custody_sha256": "d" * 64,
        "evidence_path": "docs/superpowers/evidence/v512-updater-trust-feasibility.md",
        "evidence_sha256": "e" * 64,
        "reviewer_model": "ag/gemini-pro-agent",
        "critical_count": 0,
        "important_count": 0,
        "reviewed_at": "2026-09-14T12:00:00Z",
    }

    raw_valid = canonical_json_dumps(valid_record) + b"\n"
    assert validate_acceptance_record_schema(raw_valid) == valid_record

    # Non-terminal LF
    with pytest.raises(ValueError, match="terminal LF"):
        validate_acceptance_record_schema(raw_valid[:-1])

    # Extra key
    bad_record = dict(valid_record)
    bad_record["extra_key"] = "forbidden"
    with pytest.raises(ValueError, match="closed fields|keys"):
        validate_acceptance_record_schema(canonical_json_dumps(bad_record) + b"\n")

    # Critical count != 0
    bad_record2 = dict(valid_record)
    bad_record2["critical_count"] = 1
    with pytest.raises(ValueError):
        validate_acceptance_record_schema(canonical_json_dumps(bad_record2) + b"\n")


def test_k1b_custody_manifest_schema_validation():
    from verify_v512_k1_acceptance import validate_k1b_custody_manifest_schema

    valid_manifest = {
        "schema_version": 1,
        "rt1_code_head_sha": "0" * 40,
        "authorities": {
            "profile_authority": {
                "key_id": "neko-update-profile-v512-1",
                "public_key_sha256": "1" * 64,
                "custody_file_sha256": "2" * 64,
            },
            "proof_release_authority": {
                "key_id": "neko-update-proof-v512-1",
                "public_key_sha256": "3" * 64,
                "custody_file_sha256": "4" * 64,
            },
            "production": {
                "key_id": "neko-update-prod-1",
                "public_key_sha256": "5" * 64,
                "keyset_sha256": "6" * 64,
            },
        },
        "profiles": {
            "production": {
                "path": "E:\\Github\\artifacts\\v512-update-trust-profiles\\production\\update-profile-v1.json",
                "payload_sha256": "7" * 64,
                "envelope_sha256": "8" * 64,
                "keyset_sha256": "6" * 64,
            },
            "proof": {
                "path": "E:\\Github\\artifacts\\v512-update-trust-profiles\\proof\\update-profile-v1.json",
                "payload_sha256": "9" * 64,
                "envelope_sha256": "a" * 64,
                "keyset_sha256": "b" * 64,
            },
        },
        "artifacts": {
            "baseline": {
                "launcher": {
                    "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\baseline\\NekoLauncher.exe",
                    "version": "5.1.2",
                    "artifact_id": "NekoLauncher.exe",
                    "artifact_sha256": "c" * 64,
                    "artifact_size": 100,
                    "installed_identity_sha256": "c" * 64,
                    "artifact_format": "raw-pe-v1",
                },
                "updater": {
                    "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\baseline\\NekoUpdater.exe",
                    "version": "5.1.2",
                    "artifact_id": "NekoUpdater.exe",
                    "artifact_sha256": "d" * 64,
                    "artifact_size": 100,
                    "installed_identity_sha256": "d" * 64,
                    "artifact_format": "raw-pe-v1",
                },
                "core": {
                    "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\baseline\\NekoProxyCore.zip",
                    "version": "5.1.2",
                    "artifact_id": "NekoProxyCore.zip",
                    "artifact_sha256": "e" * 64,
                    "artifact_size": 100,
                    "installed_identity_sha256": "f" * 64,
                    "artifact_format": "zip-core-v1",
                },
            },
            "candidate": {
                "launcher": {
                    "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\candidate\\NekoLauncher.exe",
                    "version": "5.1.3-proof",
                    "artifact_id": "NekoLauncher.exe",
                    "artifact_sha256": "1" * 64,
                    "artifact_size": 100,
                    "installed_identity_sha256": "1" * 64,
                    "artifact_format": "raw-pe-v1",
                },
                "updater": {
                    "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\candidate\\NekoUpdater.exe",
                    "version": "5.1.2",
                    "artifact_id": "NekoUpdater.exe",
                    "artifact_sha256": "d" * 64,
                    "artifact_size": 100,
                    "installed_identity_sha256": "d" * 64,
                    "artifact_format": "raw-pe-v1",
                },
                "core": {
                    "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\candidate\\NekoProxyCore.zip",
                    "version": "5.1.3-proof",
                    "artifact_id": "NekoProxyCore.zip",
                    "artifact_sha256": "2" * 64,
                    "artifact_size": 100,
                    "installed_identity_sha256": "3" * 64,
                    "artifact_format": "zip-core-v1",
                },
            },
        },
        "package_evidence": {
            "production_updater_sha256": "d" * 64,
            "proof_updater_sha256": "d" * 64,
            "updater_byte_identical": True,
            "baseline_components_sha256": "4" * 64,
            "candidate_components_sha256": "5" * 64,
        },
        "proof_releases": {
            "baseline": {
                "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\baseline\\release-v2.json",
                "release_sequence": 1,
                "release_id": "proof-k1-0001",
                "payload_sha256": "6" * 64,
                "envelope_sha256": "7" * 64,
                "key_id": "neko-update-proof-v512-1",
            },
            "candidate": {
                "path": "E:\\Github\\artifacts\\v512-k1-proof-fixtures\\candidate\\release-v2.json",
                "release_sequence": 2,
                "release_id": "proof-k1-0002",
                "payload_sha256": "8" * 64,
                "envelope_sha256": "9" * 64,
                "key_id": "neko-update-proof-v512-1",
            },
        },
    }

    raw = canonical_json_dumps(valid_manifest) + b"\n"
    assert validate_k1b_custody_manifest_schema(raw) == valid_manifest

    # Rejection of missing terminal LF
    with pytest.raises(ValueError, match="terminal LF"):
        validate_k1b_custody_manifest_schema(raw[:-1])

    # Rejection of CRLF
    with pytest.raises(ValueError):
        validate_k1b_custody_manifest_schema(raw.replace(b"\n", b"\r\n"))

    # Rejection of extra top-level key
    bad = dict(valid_manifest)
    bad["extra_top_level"] = "x"
    with pytest.raises(ValueError, match="closed fields|keys"):
        validate_k1b_custody_manifest_schema(canonical_json_dumps(bad) + b"\n")

    # Rejection of invented public_key_hex in manifest authority
    bad_auth = json.loads(json.dumps(valid_manifest))
    bad_auth["authorities"]["profile_authority"]["public_key_hex"] = "a" * 64
    with pytest.raises(ValueError, match="closed fields|keys|public_key_hex"):
        validate_k1b_custody_manifest_schema(canonical_json_dumps(bad_auth) + b"\n")


def test_verify_v512_k1_acceptance_verifier_cli_has_no_signer_inputs():
    import verify_v512_k1_acceptance

    parser = getattr(verify_v512_k1_acceptance, "build_parser", None)
    if parser is not None:
        p = parser()
        for a in p._actions:
            for opt in a.option_strings:
                assert "private" not in opt.lower()
                assert "secret" not in opt.lower()
                assert "sign" not in opt.lower()


def _setup_mock_k1_fixture(
    tmp_path: Path,
    *,
    prod_owner: str = "Valeneko-pranmong",
    prod_repository: str = "Neko-Family-Proxy",
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)

    # Init git repo and make a base commit
    subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestRunner"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=repo_root, check=True)

    security_paths = [
        "scripts/build_update_trust_profile.py",
        "scripts/assemble_release_v2_envelope.py",
        "scripts/verify_v512_k1_acceptance.py",
        "launcher/src/neko_launcher/updater/trust.py",
        "launcher/src/neko_launcher/updater/trust_profile.py",
    ]
    for sp in security_paths:
        p = repo_root / sp
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"# security file content\n")

    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_root, check=True)
    rt1_code_head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()

    # Create K1A public authorities
    prof_priv, prof_pub = _make_keypair()
    prof_key_id = "neko-update-profile-v512-1"
    prof_custody_doc = {
        "key_id": prof_key_id,
        "public_key_hex": prof_pub.hex(),
        "public_key_sha256": hashlib.sha256(prof_pub).hexdigest(),
        "schema_version": 1,
    }
    prof_custody_raw = canonical_json_dumps(prof_custody_doc) + b"\n"
    prof_custody_file = tmp_path / "authority" / "v512-update-profile-authority" / "public-v1.json"
    prof_custody_file.parent.mkdir(parents=True, exist_ok=True)
    prof_custody_file.write_bytes(prof_custody_raw)
    prof_custody_sha256 = hashlib.sha256(prof_custody_raw).hexdigest()

    proof_priv, proof_pub = _make_keypair()
    proof_key_id = "neko-update-proof-v512-1"
    proof_custody_doc = {
        "key_id": proof_key_id,
        "public_key_hex": proof_pub.hex(),
        "public_key_sha256": hashlib.sha256(proof_pub).hexdigest(),
        "schema_version": 1,
    }
    proof_custody_raw = canonical_json_dumps(proof_custody_doc) + b"\n"
    proof_custody_file = tmp_path / "authority" / "v512-proof-release-authority" / "public-v1.json"
    proof_custody_file.parent.mkdir(parents=True, exist_ok=True)
    proof_custody_file.write_bytes(proof_custody_raw)
    proof_custody_sha256 = hashlib.sha256(proof_custody_raw).hexdigest()

    # Production authority
    prod_key_id = "neko-update-prod-1"
    prod_pub = PRODUCTION_RELEASE_PUBLIC_KEYS[prod_key_id]
    prod_pub_sha256 = hashlib.sha256(prod_pub).hexdigest()
    prod_keyset = {
        "release_keys": [{"key_id": prod_key_id, "public_key_hex": prod_pub.hex()}]
    }
    prod_keyset_sha256 = hashlib.sha256(canonical_json_dumps(prod_keyset)).hexdigest()

    # Create profiles
    prod_payload = {
        "channel": "stable",
        "owner": prod_owner,
        "profile_id": "production",
        "release_keys": [{"key_id": prod_key_id, "public_key_hex": prod_pub.hex()}],
        "repository": prod_repository,
    }
    prod_payload_bytes = canonical_json_dumps(prod_payload)
    prod_payload_sha256 = hashlib.sha256(prod_payload_bytes).hexdigest()
    prod_sig = prof_priv.sign(prod_payload_bytes)
    prod_envelope = {
        "key_id": prof_key_id,
        "payload": prod_payload,
        "schema_version": 1,
        "signature_b64": base64.b64encode(prod_sig).decode("ascii"),
    }
    prod_envelope_raw = canonical_json_dumps(prod_envelope) + b"\n"
    prod_envelope_sha256 = hashlib.sha256(prod_envelope_raw).hexdigest()
    prod_profile_file = tmp_path / "artifacts" / "v512-update-trust-profiles" / "production" / "update-profile-v1.json"
    prod_profile_file.parent.mkdir(parents=True, exist_ok=True)
    prod_profile_file.write_bytes(prod_envelope_raw)

    proof_keyset = {
        "release_keys": [{"key_id": proof_key_id, "public_key_hex": proof_pub.hex()}]
    }
    proof_keyset_sha256 = hashlib.sha256(canonical_json_dumps(proof_keyset)).hexdigest()
    proof_payload = {
        "channel": "stable",
        "owner": "Valeneko-pranmong",
        "profile_id": "proof-v512",
        "release_keys": [{"key_id": proof_key_id, "public_key_hex": proof_pub.hex()}],
        "repository": "Neko-Family-Proxy-Updates-Proof",
    }
    proof_payload_bytes = canonical_json_dumps(proof_payload)
    proof_payload_sha256 = hashlib.sha256(proof_payload_bytes).hexdigest()
    proof_sig = prof_priv.sign(proof_payload_bytes)
    proof_envelope = {
        "key_id": prof_key_id,
        "payload": proof_payload,
        "schema_version": 1,
        "signature_b64": base64.b64encode(proof_sig).decode("ascii"),
    }
    proof_envelope_raw = canonical_json_dumps(proof_envelope) + b"\n"
    proof_envelope_sha256 = hashlib.sha256(proof_envelope_raw).hexdigest()
    proof_profile_file = tmp_path / "artifacts" / "v512-update-trust-profiles" / "proof" / "update-profile-v1.json"
    proof_profile_file.parent.mkdir(parents=True, exist_ok=True)
    proof_profile_file.write_bytes(proof_envelope_raw)

    # Artifacts
    baseline_dir = tmp_path / "artifacts" / "v512-k1-proof-fixtures" / "baseline"
    candidate_dir = tmp_path / "artifacts" / "v512-k1-proof-fixtures" / "candidate"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # Launcher
    base_launcher_bytes = b"baseline-launcher-content\n"
    base_launcher_path = baseline_dir / "NekoLauncher.exe"
    base_launcher_path.write_bytes(base_launcher_bytes)
    base_launcher_sha = hashlib.sha256(base_launcher_bytes).hexdigest()

    cand_launcher_bytes = b"k1-proof-launcher-v2\n"
    cand_launcher_path = candidate_dir / "NekoLauncher.exe"
    cand_launcher_path.write_bytes(cand_launcher_bytes)
    cand_launcher_sha = hashlib.sha256(cand_launcher_bytes).hexdigest()

    # Updater (byte identical!)
    common_updater_bytes = b"common-updater-binary-content\n"
    base_updater_path = baseline_dir / "NekoUpdater.exe"
    base_updater_path.write_bytes(common_updater_bytes)
    cand_updater_path = candidate_dir / "NekoUpdater.exe"
    cand_updater_path.write_bytes(common_updater_bytes)
    updater_sha = hashlib.sha256(common_updater_bytes).hexdigest()

    # Core ZIPs
    base_core_path = baseline_dir / "NekoProxyCore.zip"
    base_core_bytes, base_core_manifest_sha = _make_valid_core_zip(base_core_path)
    base_core_sha = hashlib.sha256(base_core_bytes).hexdigest()

    cand_core_path = candidate_dir / "NekoProxyCore.zip"
    cand_core_bytes, cand_core_manifest_sha = _make_valid_core_zip(cand_core_path)
    cand_core_sha = hashlib.sha256(cand_core_bytes).hexdigest()

    # Proof release envelopes
    base_rel_components = {
        "core": {
            "artifact_format": "zip-core-v1",
            "artifact_id": "NekoProxyCore.zip",
            "artifact_sha256": base_core_sha,
            "artifact_size": len(base_core_bytes),
            "installed_identity_sha256": base_core_manifest_sha,
            "version": "5.1.2",
        },
        "launcher": {
            "artifact_format": "raw-pe-v1",
            "artifact_id": "NekoLauncher.exe",
            "artifact_sha256": base_launcher_sha,
            "artifact_size": len(base_launcher_bytes),
            "installed_identity_sha256": base_launcher_sha,
            "version": "5.1.2",
        },
        "updater": {
            "artifact_format": "raw-pe-v1",
            "artifact_id": "NekoUpdater.exe",
            "artifact_sha256": updater_sha,
            "artifact_size": len(common_updater_bytes),
            "installed_identity_sha256": updater_sha,
            "version": "5.1.2",
        },
    }
    base_components_sha256 = hashlib.sha256(
        canonical_json_dumps({"components": base_rel_components})
    ).hexdigest()
    base_payload = {
        "channel": "stable",
        "components": base_rel_components,
        "mandatory": False,
        "minimum_supported_sequence": 1,
        "release_id": "proof-k1-0001",
        "release_sequence": 1,
        "schema_version": 2,
        "updater_protocol": {"maximum": 1, "minimum": 1},
    }
    base_payload_bytes = canonical_json_dumps(base_payload)
    base_payload_sha256 = hashlib.sha256(base_payload_bytes).hexdigest()
    base_sig = proof_priv.sign(base_payload_bytes)
    base_rel_envelope = {
        "envelope_version": 1,
        "key_id": proof_key_id,
        "payload_b64": base64.b64encode(base_payload_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(base_sig).decode("ascii"),
    }
    base_rel_raw = canonical_json_dumps(base_rel_envelope) + b"\n"
    base_rel_envelope_sha256 = hashlib.sha256(base_rel_raw).hexdigest()
    base_rel_file = baseline_dir / "release-v2.json"
    base_rel_file.write_bytes(base_rel_raw)

    cand_rel_components = {
        "core": {
            "artifact_format": "zip-core-v1",
            "artifact_id": "NekoProxyCore.zip",
            "artifact_sha256": cand_core_sha,
            "artifact_size": len(cand_core_bytes),
            "installed_identity_sha256": cand_core_manifest_sha,
            "version": "5.1.3-proof",
        },
        "launcher": {
            "artifact_format": "raw-pe-v1",
            "artifact_id": "NekoLauncher.exe",
            "artifact_sha256": cand_launcher_sha,
            "artifact_size": len(cand_launcher_bytes),
            "installed_identity_sha256": cand_launcher_sha,
            "version": "5.1.3-proof",
        },
        "updater": {
            "artifact_format": "raw-pe-v1",
            "artifact_id": "NekoUpdater.exe",
            "artifact_sha256": updater_sha,
            "artifact_size": len(common_updater_bytes),
            "installed_identity_sha256": updater_sha,
            "version": "5.1.2",
        },
    }
    cand_components_sha256 = hashlib.sha256(
        canonical_json_dumps({"components": cand_rel_components})
    ).hexdigest()
    cand_payload = {
        "channel": "stable",
        "components": cand_rel_components,
        "mandatory": True,
        "minimum_supported_sequence": 2,
        "release_id": "proof-k1-0002",
        "release_sequence": 2,
        "schema_version": 2,
        "updater_protocol": {"maximum": 1, "minimum": 1},
    }
    cand_payload_bytes = canonical_json_dumps(cand_payload)
    cand_payload_sha256 = hashlib.sha256(cand_payload_bytes).hexdigest()
    cand_sig = proof_priv.sign(cand_payload_bytes)
    cand_rel_envelope = {
        "envelope_version": 1,
        "key_id": proof_key_id,
        "payload_b64": base64.b64encode(cand_payload_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(cand_sig).decode("ascii"),
    }
    cand_rel_raw = canonical_json_dumps(cand_rel_envelope) + b"\n"
    cand_rel_envelope_sha256 = hashlib.sha256(cand_rel_raw).hexdigest()
    cand_rel_file = candidate_dir / "release-v2.json"
    cand_rel_file.write_bytes(cand_rel_raw)

    # Artifacts dictionary in manifest
    artifacts_dict = {
        "baseline": {
            "core": {
                "artifact_format": "zip-core-v1",
                "artifact_id": "NekoProxyCore.zip",
                "artifact_sha256": base_core_sha,
                "artifact_size": len(base_core_bytes),
                "installed_identity_sha256": base_core_manifest_sha,
                "path": str(base_core_path),
                "version": "5.1.2",
            },
            "launcher": {
                "artifact_format": "raw-pe-v1",
                "artifact_id": "NekoLauncher.exe",
                "artifact_sha256": base_launcher_sha,
                "artifact_size": len(base_launcher_bytes),
                "installed_identity_sha256": base_launcher_sha,
                "path": str(base_launcher_path),
                "version": "5.1.2",
            },
            "updater": {
                "artifact_format": "raw-pe-v1",
                "artifact_id": "NekoUpdater.exe",
                "artifact_sha256": updater_sha,
                "artifact_size": len(common_updater_bytes),
                "installed_identity_sha256": updater_sha,
                "path": str(base_updater_path),
                "version": "5.1.2",
            },
        },
        "candidate": {
            "core": {
                "artifact_format": "zip-core-v1",
                "artifact_id": "NekoProxyCore.zip",
                "artifact_sha256": cand_core_sha,
                "artifact_size": len(cand_core_bytes),
                "installed_identity_sha256": cand_core_manifest_sha,
                "path": str(cand_core_path),
                "version": "5.1.3-proof",
            },
            "launcher": {
                "artifact_format": "raw-pe-v1",
                "artifact_id": "NekoLauncher.exe",
                "artifact_sha256": cand_launcher_sha,
                "artifact_size": len(cand_launcher_bytes),
                "installed_identity_sha256": cand_launcher_sha,
                "path": str(cand_launcher_path),
                "version": "5.1.3-proof",
            },
            "updater": {
                "artifact_format": "raw-pe-v1",
                "artifact_id": "NekoUpdater.exe",
                "artifact_sha256": updater_sha,
                "artifact_size": len(common_updater_bytes),
                "installed_identity_sha256": updater_sha,
                "path": str(cand_updater_path),
                "version": "5.1.2",
            },
        },
    }

    # Custody manifest
    k1b_manifest_doc = {
        "schema_version": 1,
        "rt1_code_head_sha": rt1_code_head_sha,
        "authorities": {
            "profile_authority": {
                "custody_file_sha256": prof_custody_sha256,
                "key_id": prof_key_id,
                "public_key_sha256": hashlib.sha256(prof_pub).hexdigest(),
            },
            "proof_release_authority": {
                "custody_file_sha256": proof_custody_sha256,
                "key_id": proof_key_id,
                "public_key_sha256": hashlib.sha256(proof_pub).hexdigest(),
            },
            "production": {
                "key_id": prod_key_id,
                "keyset_sha256": prod_keyset_sha256,
                "public_key_sha256": prod_pub_sha256,
            },
        },
        "profiles": {
            "production": {
                "envelope_sha256": prod_envelope_sha256,
                "keyset_sha256": prod_keyset_sha256,
                "path": str(prod_profile_file),
                "payload_sha256": prod_payload_sha256,
            },
            "proof": {
                "envelope_sha256": proof_envelope_sha256,
                "keyset_sha256": proof_keyset_sha256,
                "path": str(proof_profile_file),
                "payload_sha256": proof_payload_sha256,
            },
        },
        "artifacts": artifacts_dict,
        "package_evidence": {
            "production_updater_sha256": updater_sha,
            "proof_updater_sha256": updater_sha,
            "updater_byte_identical": True,
            "baseline_components_sha256": base_components_sha256,
            "candidate_components_sha256": cand_components_sha256,
        },
        "proof_releases": {
            "baseline": {
                "envelope_sha256": base_rel_envelope_sha256,
                "key_id": proof_key_id,
                "path": str(base_rel_file),
                "payload_sha256": base_payload_sha256,
                "release_id": "proof-k1-0001",
                "release_sequence": 1,
            },
            "candidate": {
                "envelope_sha256": cand_rel_envelope_sha256,
                "key_id": proof_key_id,
                "path": str(cand_rel_file),
                "payload_sha256": cand_payload_sha256,
                "release_id": "proof-k1-0002",
                "release_sequence": 2,
            },
        },
    }
    k1b_manifest_raw = canonical_json_dumps(k1b_manifest_doc) + b"\n"
    k1b_manifest_file = tmp_path / "artifacts" / "v512-k1-proof-fixtures" / "k1b-custody-v1.json"
    k1b_manifest_file.write_bytes(k1b_manifest_raw)
    k1b_manifest_sha256 = hashlib.sha256(k1b_manifest_raw).hexdigest()

    # Evidence doc
    evidence_path = repo_root / "docs" / "superpowers" / "evidence" / "v512-updater-trust-feasibility.md"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_content = b"# Evidence document\nValid evidence content.\n"
    evidence_path.write_bytes(evidence_content)
    evidence_sha256 = hashlib.sha256(evidence_content).hexdigest()

    # Acceptance record
    acceptance_doc = {
        "critical_count": 0,
        "evidence_path": "docs/superpowers/evidence/v512-updater-trust-feasibility.md",
        "evidence_sha256": evidence_sha256,
        "important_count": 0,
        "k1b_custody_path": str(k1b_manifest_file),
        "k1b_custody_sha256": k1b_manifest_sha256,
        "profile_authority_custody_sha256": prof_custody_sha256,
        "proof_release_authority_custody_sha256": proof_custody_sha256,
        "reviewed_at": "2026-09-14T12:00:00Z",
        "reviewer_model": "ag/gemini-pro-agent",
        "rt1_code_head_sha": rt1_code_head_sha,
        "schema_version": 1,
        "task_id": "RT1-K1",
    }
    acceptance_raw = canonical_json_dumps(acceptance_doc) + b"\n"
    acceptance_path = repo_root / "docs" / "superpowers" / "evidence" / "v512-k1-acceptance.json"
    acceptance_path.write_bytes(acceptance_raw)

    return {
        "repo_root": repo_root,
        "acceptance_path": acceptance_path,
        "evidence_path": evidence_path,
        "k1b_custody_path": k1b_manifest_file,
        "prof_custody_file": prof_custody_file,
        "proof_custody_file": proof_custody_file,
        "acceptance_doc": acceptance_doc,
        "k1b_manifest_doc": k1b_manifest_doc,
        "rt1_code_head_sha": rt1_code_head_sha,
        "base_launcher_path": base_launcher_path,
        "cand_updater_path": cand_updater_path,
        "base_core_path": base_core_path,
    }


def test_verify_k1_acceptance_happy_path(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    verify_v512_k1_acceptance.verify_k1_acceptance(
        repo_root=fix["repo_root"],
        acceptance_record_path=fix["acceptance_path"],
        evidence_path=fix["evidence_path"],
        k1b_custody_path=fix["k1b_custody_path"],
        require_git_immutability=False,
    )


def test_verify_k1_acceptance_rejects_cli_path_mismatch(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    other_evidence = tmp_path / "other-evidence.md"
    other_evidence.write_bytes(fix["evidence_path"].read_bytes())

    with pytest.raises(ValueError, match="path binding|mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=other_evidence,
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_manifest_authority_invented_keys(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    # Mutate k1b manifest to include public_key_hex in profile_authority
    doc = json.loads(json.dumps(fix["k1b_manifest_doc"]))
    doc["authorities"]["profile_authority"]["public_key_hex"] = "0" * 64
    raw = canonical_json_dumps(doc) + b"\n"
    fix["k1b_custody_path"].write_bytes(raw)

    # Update acceptance record sha to match mutated file
    acc = json.loads(json.dumps(fix["acceptance_doc"]))
    acc["k1b_custody_sha256"] = hashlib.sha256(raw).hexdigest()
    fix["acceptance_path"].write_bytes(canonical_json_dumps(acc) + b"\n")

    with pytest.raises(ValueError, match="closed fields|keys|public_key_hex"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_core_bundle_invalid(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    # Corrupt core zip (invalid zip data)
    fix["base_core_path"].write_bytes(b"corrupted zip content\n")

    with pytest.raises(ValueError, match="[Cc]ore"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_nonexistent_rt1_sha(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    # Set rt1_code_head_sha to a commit that doesn't exist in the git repo
    acc = json.loads(json.dumps(fix["acceptance_doc"]))
    acc["rt1_code_head_sha"] = "f" * 40
    fix["acceptance_path"].write_bytes(canonical_json_dumps(acc) + b"\n")

    doc = json.loads(json.dumps(fix["k1b_manifest_doc"]))
    doc["rt1_code_head_sha"] = "f" * 40
    raw_k1b = canonical_json_dumps(doc) + b"\n"
    fix["k1b_custody_path"].write_bytes(raw_k1b)
    acc["k1b_custody_sha256"] = hashlib.sha256(raw_k1b).hexdigest()
    fix["acceptance_path"].write_bytes(canonical_json_dumps(acc) + b"\n")

    with pytest.raises(ValueError, match="rt1_code_head_sha|commit"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_evidence_sha_mismatch(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    fix["evidence_path"].write_bytes(b"tampered evidence content\n")

    with pytest.raises(ValueError, match="Evidence SHA256 mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_k1b_custody_sha_mismatch(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    fix["k1b_custody_path"].write_bytes(b"{\"tampered\": true}\n")

    with pytest.raises(ValueError, match="K1B custody manifest SHA256 mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_profile_authority_custody_sha_mismatch(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    # Mutate acceptance profile authority custody sha
    acc = json.loads(json.dumps(fix["acceptance_doc"]))
    acc["profile_authority_custody_sha256"] = "9" * 64
    fix["acceptance_path"].write_bytes(canonical_json_dumps(acc) + b"\n")

    with pytest.raises(ValueError, match="Profile authority custody file SHA256 mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_profile_routing_mismatch(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    # Point production profile to proof profile
    doc = json.loads(json.dumps(fix["k1b_manifest_doc"]))
    doc["profiles"]["production"]["path"] = doc["profiles"]["proof"]["path"]
    doc["profiles"]["production"]["envelope_sha256"] = doc["profiles"]["proof"]["envelope_sha256"]
    doc["profiles"]["production"]["payload_sha256"] = doc["profiles"]["proof"]["payload_sha256"]
    raw_k1b = canonical_json_dumps(doc) + b"\n"
    fix["k1b_custody_path"].write_bytes(raw_k1b)

    acc = json.loads(json.dumps(fix["acceptance_doc"]))
    acc["k1b_custody_sha256"] = hashlib.sha256(raw_k1b).hexdigest()
    fix["acceptance_path"].write_bytes(canonical_json_dumps(acc) + b"\n")

    with pytest.raises(ValueError, match="Production profile routing mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_superseded_updates_repository(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path, prod_repository="Neko-Family-Proxy-Updates")
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    with pytest.raises(ValueError, match="superseded|repository mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_arbitrary_production_repository(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path, prod_repository="ArbitraryRepo")
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    with pytest.raises(ValueError, match="repository mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_arbitrary_production_owner(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path, prod_owner="ArbitraryOwner")
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    with pytest.raises(ValueError, match="repository mismatch|owner"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )



def test_verify_k1_acceptance_rejects_updater_not_byte_identical(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    # Make candidate updater different bytes with updated manifest matching candidate updater
    different_bytes = b"different-updater-binary-conte\n"  # 31 bytes
    fix["cand_updater_path"].write_bytes(different_bytes)
    diff_sha = hashlib.sha256(different_bytes).hexdigest()

    doc = json.loads(json.dumps(fix["k1b_manifest_doc"]))
    doc["artifacts"]["candidate"]["updater"]["artifact_size"] = len(different_bytes)
    doc["artifacts"]["candidate"]["updater"]["artifact_sha256"] = diff_sha
    doc["artifacts"]["candidate"]["updater"]["installed_identity_sha256"] = diff_sha
    # Also update signed release component so that check passes
    raw_k1b = canonical_json_dumps(doc) + b"\n"
    fix["k1b_custody_path"].write_bytes(raw_k1b)

    acc = json.loads(json.dumps(fix["acceptance_doc"]))
    acc["k1b_custody_sha256"] = hashlib.sha256(raw_k1b).hexdigest()
    fix["acceptance_path"].write_bytes(canonical_json_dumps(acc) + b"\n")

    with pytest.raises(ValueError, match="Candidate updater is not byte-identical|Signed component updater does not match"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_k1_acceptance_rejects_package_evidence_components_sha_mismatch(tmp_path, monkeypatch):
    import verify_v512_k1_acceptance

    fix = _setup_mock_k1_fixture(tmp_path)
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROFILE_AUTHORITY_CUSTODY_PATH", fix["prof_custody_file"])
    monkeypatch.setattr(verify_v512_k1_acceptance, "_PROOF_RELEASE_AUTHORITY_CUSTODY_PATH", fix["proof_custody_file"])

    doc = json.loads(json.dumps(fix["k1b_manifest_doc"]))
    doc["package_evidence"]["baseline_components_sha256"] = "0" * 64
    raw_k1b = canonical_json_dumps(doc) + b"\n"
    fix["k1b_custody_path"].write_bytes(raw_k1b)

    acc = json.loads(json.dumps(fix["acceptance_doc"]))
    acc["k1b_custody_sha256"] = hashlib.sha256(raw_k1b).hexdigest()
    fix["acceptance_path"].write_bytes(canonical_json_dumps(acc) + b"\n")

    with pytest.raises(ValueError, match="Package evidence baseline_components_sha256 mismatch"):
        verify_v512_k1_acceptance.verify_k1_acceptance(
            repo_root=fix["repo_root"],
            acceptance_record_path=fix["acceptance_path"],
            evidence_path=fix["evidence_path"],
            k1b_custody_path=fix["k1b_custody_path"],
        )


def test_verify_git_immutability_enforcement(tmp_path):
    from verify_v512_k1_acceptance import verify_git_immutability

    repo = tmp_path / "repo_git"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestRunner"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=repo, check=True)

    security_paths = [
        "scripts/build_update_trust_profile.py",
        "scripts/assemble_release_v2_envelope.py",
        "scripts/verify_v512_k1_acceptance.py",
        "launcher/src/neko_launcher/updater/trust.py",
        "launcher/src/neko_launcher/updater/trust_profile.py",
    ]
    for sp in security_paths:
        p = repo / sp
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"# security file\n")

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "rt1 commit"], cwd=repo, check=True)
    rt1_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    acc_path = repo / "acceptance.json"
    acc_doc = {"rt1_code_head_sha": rt1_sha}
    acc_path.write_bytes(canonical_json_dumps(acc_doc) + b"\n")
    subprocess.run(["git", "add", "acceptance.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add acceptance"], cwd=repo, check=True)

    # 1. Single introduction passes
    msg = verify_git_immutability(repo, "acceptance.json")
    assert "RT1_SECURITY_TOOL_GUARD_OK" in msg

    # 2. Modify after introduction fails
    acc_path.write_bytes(canonical_json_dumps(acc_doc) + b" \n")
    with pytest.raises(subprocess.CalledProcessError):
        verify_git_immutability(repo, "acceptance.json")

    # Reset
    subprocess.run(["git", "checkout", "acceptance.json"], cwd=repo, check=True)

    # 3. Modify security path after rt1_sha fails
    sec_file = repo / security_paths[0]
    sec_file.write_bytes(b"# modified security file\n")
    subprocess.run(["git", "add", security_paths[0]], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "modify security file"], cwd=repo, check=True)
    with pytest.raises(ValueError, match="RT1 security paths changed"):
        verify_git_immutability(repo, "acceptance.json")
