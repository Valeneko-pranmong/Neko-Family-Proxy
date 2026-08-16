from __future__ import annotations

import json
from pathlib import Path

import pytest

from neko_launcher.e2e.final_windows_harness import (
    FINAL_CORE_ARTIFACT_PATH,
    FINAL_CORE_EXE_SHA256,
    FINAL_CORE_SOURCE_SHA,
    FINAL_MANIFEST_SHA256,
    FINAL_PROTECTED_PAYLOAD_SHA256,
    FINAL_PSO2_MODE_SHA256,
    admit_final_core_artifact,
)


def _setup_mock_artifact(
    base: Path,
    *,
    exe_content: bytes = b"MZ_MOCK_CORE_EXECUTABLE",
    payload_content: bytes = b"MOCK_PROTECTED_PAYLOAD",
    pso2_content: bytes = b'{"mode": "pso2"}',
) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / "NekoProxyCore.exe").write_bytes(exe_content)
    (base / "runtime-settings.nkps").write_bytes(payload_content)
    pso2_dir = base / "mode" / "Custom"
    pso2_dir.mkdir(parents=True, exist_ok=True)
    (pso2_dir / "PSO2.json").write_bytes(pso2_content)
    return base


def test_scenario_a_manifest_matches_artifact_passes(tmp_path: Path) -> None:
    import hashlib

    art = _setup_mock_artifact(tmp_path / "art")
    exe_hash = hashlib.sha256((art / "NekoProxyCore.exe").read_bytes()).hexdigest()
    payload_hash = hashlib.sha256((art / "runtime-settings.nkps").read_bytes()).hexdigest()
    pso2_hash = hashlib.sha256((art / "mode" / "Custom" / "PSO2.json").read_bytes()).hexdigest()

    manifest_data = {
        "source_commit": "549e3f5b1f339ee6dd2a11920d6e5816a752671f",
        "branch_head_context": "d909a2a0f1a06562b060535ae57bb4d0cddcb251",
        "neko_proxy_core_exe_hash": exe_hash,
        "protected_settings_payload_hash": payload_hash,
        "files": {
            "NekoProxyCore.exe": exe_hash,
            "runtime-settings.nkps": payload_hash,
            "mode/Custom/PSO2.json": pso2_hash,
        },
    }
    manifest_path = tmp_path / "canonical-core-manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    admission = admit_final_core_artifact(art, manifest_path=manifest_path)
    assert admission.core_exe_sha256 == exe_hash
    assert admission.protected_payload_sha256 == payload_hash
    assert admission.pso2_mode_sha256 == pso2_hash
    assert admission.source_sha == "549e3f5b1f339ee6dd2a11920d6e5816a752671f"


def test_scenario_b_artifact_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    art = _setup_mock_artifact(tmp_path / "art")
    manifest_data = {
        "source_commit": "549e3f5b1f339ee6dd2a11920d6e5816a752671f",
        "neko_proxy_core_exe_hash": "0000000000000000000000000000000000000000000000000000000000000000",
        "files": {
            "NekoProxyCore.exe": "0000000000000000000000000000000000000000000000000000000000000000",
        },
    }
    manifest_path = tmp_path / "canonical-core-manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="Core executable hash mismatch"):
        admit_final_core_artifact(art, manifest_path=manifest_path)


def test_scenario_c_missing_authority_fails_closed(tmp_path: Path) -> None:
    art = _setup_mock_artifact(tmp_path / "art_no_authority")
    # No manifest and no explicit hash provided for custom artifact path
    with pytest.raises(ValueError, match="artifact authority is unavailable"):
        admit_final_core_artifact(art)


def test_scenario_d_historical_s0_mode_preserves_expected_values() -> None:
    assert FINAL_CORE_SOURCE_SHA == "b3c9d0851cff74691500c431c0da1ec30c21927a"
    assert FINAL_CORE_EXE_SHA256 == "1b9b0ba313ac1f8c879f07f678a2f01e5b334c29fc17323533017aed2cbffcfe"
    assert (
        FINAL_PROTECTED_PAYLOAD_SHA256
        == "3046c165a8d0c2516915a341c9816877c919b0a05353d72953eb3cd3282bc982"
    )
    assert FINAL_PSO2_MODE_SHA256 == "23b3ea655e5ec96d84e37ac649e6da7f0f9d6090b28c82d48425152110ebc213"
    assert FINAL_MANIFEST_SHA256 == "2826a78a34f4b536c38c9a038c72ed6a4802d3da044f94cd18b895e7193f9841"
    assert FINAL_CORE_ARTIFACT_PATH == Path(r"E:\Temp\neko-phase25-core-final-b3c9d085-FROZEN")


def test_scenario_e_canonical_lite_artifact_auto_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    # Create an artifact directory and adjacent canonical-core-manifest.json
    art_dir = tmp_path / "core-canonical-publish"
    _setup_mock_artifact(art_dir)
    exe_hash = hashlib.sha256((art_dir / "NekoProxyCore.exe").read_bytes()).hexdigest()
    payload_hash = hashlib.sha256((art_dir / "runtime-settings.nkps").read_bytes()).hexdigest()

    manifest_data = {
        "source_commit": "549e3f5b1f339ee6dd2a11920d6e5816a752671f",
        "neko_proxy_core_exe_hash": exe_hash,
        "protected_settings_payload_hash": payload_hash,
        "files": {
            "NekoProxyCore.exe": exe_hash,
            "runtime-settings.nkps": payload_hash,
        },
    }
    # Place adjacent to art_dir as canonical-core-manifest.json
    (tmp_path / "canonical-core-manifest.json").write_text(
        json.dumps(manifest_data), encoding="utf-8"
    )

    monkeypatch.setenv("NEKO_FINAL_CORE_ARTIFACT_PATH", str(art_dir))
    admission = admit_final_core_artifact()
    assert admission.core_exe_sha256 == exe_hash
    assert admission.artifact_path == art_dir.resolve()
