from __future__ import annotations

import hashlib
import json
from pathlib import Path

from neko_launcher.updater.probation_runner import run_probation_self_test

_MANDATORY = (
    "NekoProxyCore.exe",
    "NekoProxyCore.dll",
    "runtime-settings.nkps",
    "bin/Redirector.bin",
    "bin/nfapi.dll",
    "bin/v2ray-sn.exe",
)


def _frozen_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "candidate"
    bundle.mkdir()
    files = {name: f"content:{name}".encode("utf-8") for name in _MANDATORY}
    for name, data in files.items():
        path = bundle / "ProxyCore" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        "source_commit": "b7d9708bc2c9a97255a9ea2f8307ef66e2d81bf8",
        "file_count": len(files),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    (bundle / "ProxyCore" / "core-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    (bundle / "NekoLauncher.exe").write_bytes(b"launcher")
    return bundle


def test_frozen_core_skips_preflight_and_passes_inventory(tmp_path: Path) -> None:
    result = run_probation_self_test(_frozen_bundle(tmp_path), skip_tk=True)

    assert result.passed is True
    assert result.error_code is None


def test_frozen_core_inventory_failure_is_rejected(tmp_path: Path) -> None:
    bundle = _frozen_bundle(tmp_path)
    (bundle / "ProxyCore" / "NekoProxyCore.exe").write_bytes(b"tampered")

    result = run_probation_self_test(bundle, skip_tk=True)

    assert result.passed is False
    assert result.error_code == "CORE_INVENTORY_INVALID"
