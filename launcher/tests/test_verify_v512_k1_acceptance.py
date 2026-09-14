from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from neko_launcher.updater.canonical_json import canonical_json_dumps


def _make_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes_raw()
    return priv, pub_bytes


def _make_valid_core_zip(zip_path: Path) -> bytes:
    core_files = {
        "NekoProxyCore.exe": b"test_exe_content",
        "NekoProxyCore.dll": b"test_dll_content",
        "runtime-settings.nkps": b"test_nkps_content",
        "bin/Redirector.bin": b"test_redir_content",
        "bin/nfapi.dll": b"test_nfapi_content",
        "bin/v2ray-sn.exe": b"test_v2ray_content",
    }
    manifest_files = []
    for path_str, content in sorted(core_files.items()):
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

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("core-manifest.json", manifest_bytes)
        for path_str, content in core_files.items():
            zf.writestr(path_str, content)

    return zip_path.read_bytes()


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
