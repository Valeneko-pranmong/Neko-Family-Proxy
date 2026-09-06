import json
from pathlib import Path

from neko_launcher.updater.core_manifest_verifier import (
    verify_canonical_core_bundle,
)

CANONICAL_A43_ROOT = Path("E:/Github/worktrees/NekoProxyCore-live-update/TestResults/task12/a43-core")


def test_verifies_canonical_a43_fixture() -> None:
    res = verify_canonical_core_bundle(CANONICAL_A43_ROOT)
    assert res.valid
    assert res.file_count == 1022
    assert res.total_bytes == 371717577
    assert res.manifest_sha256 == "d39f43c75ac84fa3189f93f935dd30b6538ee76b3c817652d711451c3f15b59a"


def test_rejects_tampered_core_bundle(tmp_path: Path) -> None:
    # Create a minimal bundle with manifest and 1 file
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "NekoProxyCore.exe").write_bytes(b"dummy exe")
    manifest = {
        "source_commit": "1234567",
        "candidate": "5.1.0a3",
        "authority": "test",
        "file_count": 1,
        "total_bytes": len(b"dummy exe"),
        "neko_proxy_core_exe_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # wrong hash
        "neko_proxy_core_dll_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "protected_settings_payload_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "redirector_bin_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "nfapi_dll_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "v2ray_sn_exe_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "security": {
            "runtime_settings_key_files": 0,
            "plaintext_settings_files": 0,
            "plaintext_secret_marker_hits": 0,
            "external_dotnet_dependency": False,
        },
        "files": {
            "NekoProxyCore.exe": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
    }
    (bundle / "canonical-core-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    res = verify_canonical_core_bundle(bundle)
    assert not res.valid
    assert "hash mismatch" in res.error.lower()
