from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from neko_launcher.application.file_integrity import (
    FileIntegrityItem,
    FileIntegrityReport,
    IntegrityStatus,
    check_installed_files,
)
from neko_launcher.application.software_update_models import InstalledReleaseSelector
from neko_launcher.updater.manifest_v2 import ComponentV2, ReleaseSetV2, UpdaterProtocol


def _make_release(
    *,
    sequence: int = 9,
    release_id: str = "stable-0009",
    version: str = "5.1.3",
    tag_name: str = "v5.1.3",
    target_commit: str = "a" * 40,
    launcher_size: int = 100,
    launcher_sha: str = "1" * 64,
    updater_size: int = 200,
    updater_sha: str = "2" * 64,
    core_size: int = 300,
    core_sha: str = "3" * 64,
    proto_min: int = 1,
    proto_max: int = 1,
) -> ReleaseSetV2:
    components = {
        "launcher": ComponentV2(
            name="launcher",
            version=version,
            artifact_id="NekoLauncher.exe",
            artifact_sha256=launcher_sha,
            artifact_size=launcher_size,
            installed_identity_sha256=launcher_sha,
            artifact_format="raw-pe-v1",
        ),
        "updater": ComponentV2(
            name="updater",
            version=version,
            artifact_id="NekoUpdater.exe",
            artifact_sha256=updater_sha,
            artifact_size=updater_size,
            installed_identity_sha256=updater_sha,
            artifact_format="raw-pe-v1",
        ),
        "core": ComponentV2(
            name="core",
            version=version,
            artifact_id="NekoProxyCore.zip",
            artifact_sha256=core_sha,
            artifact_size=core_size,
            installed_identity_sha256=core_sha,
            artifact_format="zip-core-v1",
        ),
    }
    rel = ReleaseSetV2(
        schema_version=2,
        channel="stable",
        release_sequence=sequence,
        release_id=release_id,
        mandatory=False,
        minimum_supported_sequence=1,
        updater_protocol=UpdaterProtocol(minimum=proto_min, maximum=proto_max),
        components=components,
    )
    # Attach selector for exact resolution
    selector = InstalledReleaseSelector(
        sequence=sequence,
        release_id=release_id,
        version=version,
        tag_name=tag_name,
        target_commit=target_commit,
    )
    object.__setattr__(rel, "selector", selector)
    return rel


def _setup_installed_files(
    root: Path,
    *,
    launcher_content: bytes = b"launcher-bytes-ok" + b"\x00" * (100 - len(b"launcher-bytes-ok")),
    updater_content: bytes = b"updater-bytes-ok" + b"\x00" * (200 - len(b"updater-bytes-ok")),
    core_content: bytes = b"core-bytes-ok" + b"\x00" * (300 - len(b"core-bytes-ok")),
    include_launcher: bool = True,
    include_updater: bool = True,
    include_core: bool = True,
) -> tuple[Path, Path, Path]:
    launcher_path = root / "NekoLauncher.exe"
    updater_path = root / "NekoUpdater.exe"
    core_path = root / "NekoProxyCore.zip"

    if include_launcher:
        launcher_path.write_bytes(launcher_content)
    if include_updater:
        updater_path.write_bytes(updater_content)
    if include_core:
        core_path.write_bytes(core_content)

    return launcher_path, updater_path, core_path


def test_integrity_status_enum_values() -> None:
    assert IntegrityStatus.OK.value == "ok"
    assert IntegrityStatus.MISSING.value == "missing"
    assert IntegrityStatus.SIZE_MISMATCH.value == "size_mismatch"
    assert IntegrityStatus.HASH_MISMATCH.value == "hash_mismatch"
    assert IntegrityStatus.UNTRUSTED_UPDATER.value == "untrusted_updater"


def test_check_installed_files_all_ok(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        updater_content=u_bytes,
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert isinstance(report, FileIntegrityReport)
    assert report.selector == rel.selector
    assert len(report.items) == 3
    assert report.reinstall_required is False
    assert report.repairable_components == ()

    item_map = {item.component: item for item in report.items}
    for comp_name in ("launcher", "updater", "core"):
        item = item_map[comp_name]
        assert isinstance(item, FileIntegrityItem)
        assert item.status == IntegrityStatus.OK
        assert item.actual_size == item.expected_size
        assert item.actual_sha256 == item.expected_sha256


def test_check_installed_files_launcher_missing(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        include_launcher=False,
        updater_content=u_bytes,
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is False
    assert report.repairable_components == ("launcher",)

    item_map = {item.component: item for item in report.items}
    assert item_map["launcher"].status == IntegrityStatus.MISSING
    assert item_map["launcher"].actual_size is None
    assert item_map["launcher"].actual_sha256 is None
    assert item_map["updater"].status == IntegrityStatus.OK
    assert item_map["core"].status == IntegrityStatus.OK


def test_check_installed_files_launcher_size_mismatch(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=b"too short",
        updater_content=u_bytes,
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is False
    assert report.repairable_components == ("launcher",)

    item_map = {item.component: item for item in report.items}
    assert item_map["launcher"].status == IntegrityStatus.SIZE_MISMATCH
    assert item_map["launcher"].actual_size == len(b"too short")
    assert item_map["updater"].status == IntegrityStatus.OK
    assert item_map["core"].status == IntegrityStatus.OK


def test_check_installed_files_launcher_hash_mismatch(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=b"X" * 100,  # Same size, different content
        updater_content=u_bytes,
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is False
    assert report.repairable_components == ("launcher",)

    item_map = {item.component: item for item in report.items}
    assert item_map["launcher"].status == IntegrityStatus.HASH_MISMATCH
    assert item_map["launcher"].actual_size == 100
    assert item_map["launcher"].actual_sha256 == hashlib.sha256(b"X" * 100).hexdigest()
    assert item_map["updater"].status == IntegrityStatus.OK
    assert item_map["core"].status == IntegrityStatus.OK


def test_check_installed_files_core_missing(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        updater_content=u_bytes,
        include_core=False,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is False
    assert report.repairable_components == ("core",)

    item_map = {item.component: item for item in report.items}
    assert item_map["core"].status == IntegrityStatus.MISSING
    assert item_map["launcher"].status == IntegrityStatus.OK
    assert item_map["updater"].status == IntegrityStatus.OK


def test_check_installed_files_core_size_mismatch(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        updater_content=u_bytes,
        core_content=b"short core",
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is False
    assert report.repairable_components == ("core",)

    item_map = {item.component: item for item in report.items}
    assert item_map["core"].status == IntegrityStatus.SIZE_MISMATCH
    assert item_map["core"].actual_size == len(b"short core")


def test_check_installed_files_core_hash_mismatch(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        updater_content=u_bytes,
        core_content=b"Z" * 300,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is False
    assert report.repairable_components == ("core",)

    item_map = {item.component: item for item in report.items}
    assert item_map["core"].status == IntegrityStatus.HASH_MISMATCH
    assert item_map["core"].actual_size == 300
    assert item_map["core"].actual_sha256 == hashlib.sha256(b"Z" * 300).hexdigest()


def test_check_installed_files_both_launcher_and_core_damaged(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=b"bad launcher bytes",
        updater_content=u_bytes,
        include_core=False,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is False
    assert report.repairable_components == ("launcher", "core")


def test_check_installed_files_updater_missing_requires_reinstall(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        include_updater=False,
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is True
    assert report.repairable_components == ()
    item_map = {item.component: item for item in report.items}
    assert item_map["updater"].status == IntegrityStatus.MISSING


def test_check_installed_files_updater_size_mismatch_requires_reinstall(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        updater_content=b"short updater",
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is True
    assert report.repairable_components == ()
    item_map = {item.component: item for item in report.items}
    assert item_map["updater"].status == IntegrityStatus.SIZE_MISMATCH


def test_check_installed_files_updater_hash_mismatch_requires_reinstall(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        updater_content=b"Y" * 200,
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is True
    assert report.repairable_components == ()
    item_map = {item.component: item for item in report.items}
    assert item_map["updater"].status == IntegrityStatus.HASH_MISMATCH


def test_check_installed_files_updater_protocol_incompatible_requires_reinstall(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
        proto_min=2,
        proto_max=2,  # Incompatible with Launcher supported protocol (1)
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=l_bytes,
        updater_content=u_bytes,
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is True
    assert report.repairable_components == ()
    item_map = {item.component: item for item in report.items}
    assert item_map["updater"].status == IntegrityStatus.UNTRUSTED_UPDATER


def test_check_installed_files_updater_mismatch_with_launcher_mismatch_requires_reinstall(tmp_path: Path) -> None:
    l_bytes = b"L" * 100
    u_bytes = b"U" * 200
    c_bytes = b"C" * 300

    rel = _make_release(
        launcher_size=100,
        launcher_sha=hashlib.sha256(l_bytes).hexdigest(),
        updater_size=200,
        updater_sha=hashlib.sha256(u_bytes).hexdigest(),
        core_size=300,
        core_sha=hashlib.sha256(c_bytes).hexdigest(),
    )
    _setup_installed_files(
        tmp_path,
        launcher_content=b"bad launcher",
        updater_content=b"bad updater",
        core_content=c_bytes,
    )

    report = check_installed_files(install_root=tmp_path, release=rel)

    assert report.reinstall_required is True
    assert report.repairable_components == ()


def test_file_check_has_no_mutation_dependency(tmp_path: Path) -> None:
    rel = _make_release()
    report = check_installed_files(install_root=tmp_path, release=rel)
    assert len(report.items) == 3
    assert not hasattr(report, "apply")

    # Verify check_installed_files signature has no mutation/downloader/stager/updater-session parameters
    params = inspect.signature(check_installed_files).parameters
    allowed_params = {"install_root", "release"}
    assert set(params.keys()) == allowed_params
    for param in params.values():
        assert param.default is inspect.Parameter.empty or param.default is None

    # Verify no files were created or modified in install_root
    assert list(tmp_path.iterdir()) == []
