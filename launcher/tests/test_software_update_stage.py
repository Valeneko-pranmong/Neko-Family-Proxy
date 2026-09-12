from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from neko_launcher.application.software_update_models import LocalReleaseIdentity
from neko_launcher.infrastructure.github_asset_downloader import (
    DownloadedArtifact,
    GitHubAssetDownloadError,
)
from neko_launcher.infrastructure.github_release import (
    GitHubRelease,
    GitHubReleaseAsset,
)
from neko_launcher.infrastructure.github_release_binding import ResolvedGitHubRelease
from neko_launcher.infrastructure.software_update_pending_store import PendingUpdateStore
from neko_launcher.infrastructure.software_update_v2 import V2ReleaseManifestVerifierAdapter
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from tests.software_update_helpers import (
    get_test_key_registry,
    signed_envelope,
    valid_v2_release_document,
)


def lazy_import():
    try:
        from neko_launcher.infrastructure.software_update_stage import (
            SoftwareUpdateStageError,
            SoftwareUpdateStageService,
        )
        return True, (SoftwareUpdateStageError, SoftwareUpdateStageService)
    except ImportError:
        return False, None


class FakeAssetDownloader:
    def __init__(
        self,
        payloads: Mapping[str, bytes] | None = None,
        errors: Mapping[str, Exception] | None = None,
        default_error: Exception | None = None,
    ) -> None:
        self.payloads = dict(payloads or {})
        self.errors = dict(errors or {})
        self.default_error = default_error
        self.download_calls: list[dict[str, Any]] = []

    def download(
        self,
        *,
        initial_url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> DownloadedArtifact:
        self.download_calls.append({
            "initial_url": initial_url,
            "destination": Path(destination),
            "expected_size": expected_size,
            "expected_sha256": expected_sha256,
        })
        if initial_url in self.errors:
            raise self.errors[initial_url]
        if self.default_error is not None:
            raise self.default_error

        if initial_url not in self.payloads:
            raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE")

        data = self.payloads[initial_url]
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return DownloadedArtifact(size=len(data), sha256=digest)


def _make_local_identity(
    *,
    sequence: int = 1,
    release_id: str = "r1-stable",
    launcher_version: str = "5.1.0",
    launcher_sha: str = "0" * 64,
    core_version: str = "1.0.0",
    core_sha: str = "0" * 64,
) -> LocalReleaseIdentity:
    return LocalReleaseIdentity(
        release_sequence=sequence,
        release_id=release_id,
        launcher_version=launcher_version,
        launcher_installed_identity_sha256=launcher_sha,
        core_version=core_version,
        core_installed_identity_sha256=core_sha,
    )


def _make_resolved_release(
    *,
    sequence: int = 2,
    release_id: str = "r2-stable",
    channel: str = "stable",
    mandatory: bool = False,
    minimum_supported_sequence: int = 1,
    launcher_version: str = "5.1.1",
    launcher_bytes: bytes = b"MZ-staged-launcher-v2",
    core_version: str = "1.0.1",
    core_bytes: bytes = b"PK-staged-core-zip-v2",
    core_installed_sha: str | None = None,
    updater_version: str = "5.1.0",
    updater_bytes: bytes = b"MZ-updater-helper-binary",
    custom_envelope_bytes: bytes | None = None,
    key_registry: Mapping[str, bytes] | None = None,
) -> tuple[ResolvedGitHubRelease, dict[str, bytes]]:
    keys = dict(key_registry or get_test_key_registry())
    l_sha = hashlib.sha256(launcher_bytes).hexdigest()
    c_sha = hashlib.sha256(core_bytes).hexdigest()
    u_sha = hashlib.sha256(updater_bytes).hexdigest()

    doc = valid_v2_release_document(
        sequence=sequence,
        release_id=release_id,
        channel=channel,
        mandatory=mandatory,
        minimum_supported_sequence=minimum_supported_sequence,
        launcher_version=launcher_version,
        launcher_sha=l_sha,
        launcher_size=len(launcher_bytes),
        updater_version=updater_version,
        updater_sha=u_sha,
        updater_size=len(updater_bytes),
        core_version=core_version,
        core_sha=c_sha,
        core_size=len(core_bytes),
        core_installed_sha=core_installed_sha or c_sha,
    )

    env = signed_envelope(doc)
    env_bytes = custom_envelope_bytes if custom_envelope_bytes is not None else canonical_json_dumps(env)

    adapter = V2ReleaseManifestVerifierAdapter(keys, updater_protocol=1)
    authenticated_release = adapter.verify(env)
    release_v2, _ = verify_release_envelope_v2(env, keys)

    launcher_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoLauncher.exe"
    updater_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoUpdater.exe"
    core_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoProxyCore.zip"
    manifest_url = f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/release-v2.json"

    launcher_asset = GitHubReleaseAsset(id=1, name="NekoLauncher.exe", size=len(launcher_bytes), browser_download_url=launcher_url)
    updater_asset = GitHubReleaseAsset(id=2, name="NekoUpdater.exe", size=len(updater_bytes), browser_download_url=updater_url)
    core_asset = GitHubReleaseAsset(id=3, name="NekoProxyCore.zip", size=len(core_bytes), browser_download_url=core_url)
    manifest_asset = GitHubReleaseAsset(id=4, name="release-v2.json", size=len(env_bytes), browser_download_url=manifest_url)

    gh_release = GitHubRelease(
        id=10,
        tag_name=f"v{launcher_version}",
        draft=False,
        prerelease=False,
        assets=(manifest_asset, launcher_asset, updater_asset, core_asset),
    )

    resolved = ResolvedGitHubRelease(
        authenticated_release=authenticated_release,
        authenticated_release_v2=release_v2,
        envelope_bytes=env_bytes,
        envelope_document=env,
        github_release=gh_release,
        manifest_asset=manifest_asset,
        launcher_asset=launcher_asset,
        updater_asset=updater_asset,
        core_asset=core_asset,
    )
    payload_map = {
        launcher_url: launcher_bytes,
        core_url: core_bytes,
        updater_url: updater_bytes,
    }
    return resolved, payload_map


def test_stage_changed_only_launcher_downloads_only_launcher(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    old_l_sha = hashlib.sha256(b"old-launcher").hexdigest()
    same_c_bytes = b"PK-core-bytes-unchanged"
    same_c_sha = hashlib.sha256(same_c_bytes).hexdigest()

    local = _make_local_identity(sequence=1, launcher_sha=old_l_sha, core_sha=same_c_sha)

    resolved, payloads = _make_resolved_release(
        sequence=2,
        launcher_bytes=b"MZ-new-launcher-bytes",
        core_bytes=same_c_bytes,
        core_installed_sha=same_c_sha,
    )
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    pending = service.stage(resolved, local)

    assert pending is not None
    assert pending.release_sequence == 2
    assert pending.changed_components == ("launcher",)
    assert pending.launcher_artifact is not None
    assert pending.launcher_artifact.is_file()
    assert pending.launcher_artifact.read_bytes() == b"MZ-new-launcher-bytes"
    assert pending.core_artifact is None

    assert len(downloader.download_calls) == 1
    call = downloader.download_calls[0]
    assert call["initial_url"] == resolved.launcher_asset.browser_download_url
    assert call["expected_size"] == len(b"MZ-new-launcher-bytes")
    assert call["expected_sha256"] == hashlib.sha256(b"MZ-new-launcher-bytes").hexdigest()


def test_stage_changed_only_core_downloads_only_core(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    same_l_bytes = b"MZ-launcher-bytes-unchanged"
    same_l_sha = hashlib.sha256(same_l_bytes).hexdigest()
    old_c_sha = hashlib.sha256(b"old-core").hexdigest()

    local = _make_local_identity(sequence=1, launcher_sha=same_l_sha, core_sha=old_c_sha)

    resolved, payloads = _make_resolved_release(
        sequence=2,
        launcher_bytes=same_l_bytes,
        core_bytes=b"PK-new-core-bytes",
    )
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    pending = service.stage(resolved, local)

    assert pending is not None
    assert pending.release_sequence == 2
    assert pending.changed_components == ("core",)
    assert pending.launcher_artifact is None
    assert pending.core_artifact is not None
    assert pending.core_artifact.is_file()
    assert pending.core_artifact.read_bytes() == b"PK-new-core-bytes"

    assert len(downloader.download_calls) == 1
    call = downloader.download_calls[0]
    assert call["initial_url"] == resolved.core_asset.browser_download_url
    assert call["expected_size"] == len(b"PK-new-core-bytes")
    assert call["expected_sha256"] == hashlib.sha256(b"PK-new-core-bytes").hexdigest()


def test_stage_both_changed_downloads_both(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    old_l_sha = hashlib.sha256(b"old-launcher").hexdigest()
    old_c_sha = hashlib.sha256(b"old-core").hexdigest()

    local = _make_local_identity(sequence=1, launcher_sha=old_l_sha, core_sha=old_c_sha)

    resolved, payloads = _make_resolved_release(
        sequence=2,
        launcher_bytes=b"MZ-new-launcher",
        core_bytes=b"PK-new-core",
    )
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    pending = service.stage(resolved, local)

    assert pending is not None
    assert pending.release_sequence == 2
    assert pending.changed_components == ("launcher", "core")
    assert pending.launcher_artifact is not None
    assert pending.core_artifact is not None

    downloaded_urls = [c["initial_url"] for c in downloader.download_calls]
    assert resolved.launcher_asset.browser_download_url in downloaded_urls
    assert resolved.core_asset.browser_download_url in downloaded_urls
    assert resolved.updater_asset.browser_download_url not in downloaded_urls


def test_stage_noop_latest_release_returns_none_and_downloads_nothing(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    same_l_bytes = b"MZ-same-launcher"
    same_l_sha = hashlib.sha256(same_l_bytes).hexdigest()
    same_c_bytes = b"PK-same-core"
    same_c_sha = hashlib.sha256(same_c_bytes).hexdigest()

    local = _make_local_identity(
        sequence=2,
        release_id="r2-stable",
        launcher_sha=same_l_sha,
        core_sha=same_c_sha,
    )

    resolved, payloads = _make_resolved_release(
        sequence=2,
        release_id="r2-stable",
        launcher_bytes=same_l_bytes,
        core_bytes=same_c_bytes,
        core_installed_sha=same_c_sha,
    )
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    result = service.stage(resolved, local)

    assert result is None
    assert len(downloader.download_calls) == 0
    assert store.load_verified(local) is None


def test_stage_mandatory_and_non_mandatory_newer_releases(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    # Non-mandatory newer release
    resolved_optional, payloads_optional = _make_resolved_release(sequence=2, mandatory=False)
    service_opt = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_optional))
    pending_opt = service_opt.stage(resolved_optional, local)
    assert pending_opt is not None
    assert pending_opt.release_sequence == 2

    # Mandatory newer release
    resolved_mand, payloads_mand = _make_resolved_release(sequence=3, mandatory=True)
    service_mand = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_mand))
    pending_mand = service_mand.stage(resolved_mand, local)
    assert pending_mand is not None
    assert pending_mand.release_sequence == 3


def test_stage_download_failure_preserves_older_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    # 1. Stage sequence 2 successfully
    resolved_2, payloads_2 = _make_resolved_release(sequence=2, release_id="r2-stable")
    service_2 = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_2))
    pending_2 = service_2.stage(resolved_2, local)
    assert pending_2 is not None
    assert store.load_verified(local) is not None
    assert store.load_verified(local).release_sequence == 2

    # 2. Stage sequence 3 with download failure
    resolved_3, payloads_3 = _make_resolved_release(sequence=3, release_id="r3-stable")
    failing_downloader = FakeAssetDownloader(
        payloads_3,
        default_error=GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE"),
    )
    service_3 = StageService(pending_store=store, asset_downloader=failing_downloader)

    with pytest.raises(SoftwareUpdateStageError) as exc_info:
        service_3.stage(resolved_3, local)
    assert exc_info.value.code == "DOWNLOAD_UNAVAILABLE"

    # Prior valid pending must be preserved
    active_pending = store.load_verified(local)
    assert active_pending is not None
    assert active_pending.release_sequence == 2
    assert active_pending.release_id == "r2-stable"


def test_stage_hash_failure_preserves_older_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    resolved_2, payloads_2 = _make_resolved_release(sequence=2, release_id="r2-stable")
    service_2 = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_2))
    assert service_2.stage(resolved_2, local) is not None

    resolved_3, payloads_3 = _make_resolved_release(sequence=3, release_id="r3-stable")
    failing_downloader = FakeAssetDownloader(
        payloads_3,
        default_error=GitHubAssetDownloadError("DOWNLOAD_HASH_MISMATCH"),
    )
    service_3 = StageService(pending_store=store, asset_downloader=failing_downloader)

    with pytest.raises(SoftwareUpdateStageError) as exc_info:
        service_3.stage(resolved_3, local)
    assert exc_info.value.code == "DOWNLOAD_HASH_MISMATCH"

    active = store.load_verified(local)
    assert active is not None
    assert active.release_sequence == 2


def test_stage_size_failure_preserves_older_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    resolved_2, payloads_2 = _make_resolved_release(sequence=2, release_id="r2-stable")
    service_2 = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_2))
    assert service_2.stage(resolved_2, local) is not None

    resolved_3, payloads_3 = _make_resolved_release(sequence=3, release_id="r3-stable")
    failing_downloader = FakeAssetDownloader(
        payloads_3,
        default_error=GitHubAssetDownloadError("DOWNLOAD_SIZE_MISMATCH"),
    )
    service_3 = StageService(pending_store=store, asset_downloader=failing_downloader)

    with pytest.raises(SoftwareUpdateStageError) as exc_info:
        service_3.stage(resolved_3, local)
    assert exc_info.value.code == "DOWNLOAD_SIZE_MISMATCH"

    active = store.load_verified(local)
    assert active is not None
    assert active.release_sequence == 2


def test_stage_higher_release_supersedes_older_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    # 1. Stage sequence 2
    resolved_2, payloads_2 = _make_resolved_release(sequence=2, release_id="r2-stable")
    service_2 = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_2))
    pending_2 = service_2.stage(resolved_2, local)
    assert pending_2 is not None
    assert store.load_verified(local).release_sequence == 2
    gen_dir_2 = pending_2.generation_dir

    # 2. Stage sequence 3 (superseding)
    resolved_3, payloads_3 = _make_resolved_release(sequence=3, release_id="r3-stable")
    service_3 = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_3))
    pending_3 = service_3.stage(resolved_3, local)
    assert pending_3 is not None
    assert pending_3.release_sequence == 3

    # Active is now sequence 3
    active = store.load_verified(local)
    assert active is not None
    assert active.release_sequence == 3
    assert active.release_id == "r3-stable"
    # Old generation dir cleaned up
    assert not gen_dir_2.exists()


def test_stage_lower_sequence_rejection_against_local(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=3)

    resolved, payloads = _make_resolved_release(sequence=2)
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    with pytest.raises(SoftwareUpdateStageError) as exc_info:
        service.stage(resolved, local)
    assert exc_info.value.code == "DOWNGRADE_REJECTED"
    assert len(downloader.download_calls) == 0


def test_stage_lower_sequence_rejection_against_existing_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    # Pending has sequence 3
    resolved_3, payloads_3 = _make_resolved_release(sequence=3, release_id="r3-stable")
    service_3 = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_3))
    assert service_3.stage(resolved_3, local) is not None

    # Incoming has sequence 2 (< 3)
    resolved_2, payloads_2 = _make_resolved_release(sequence=2, release_id="r2-stable")
    downloader_2 = FakeAssetDownloader(payloads_2)
    service_2 = StageService(pending_store=store, asset_downloader=downloader_2)

    with pytest.raises(SoftwareUpdateStageError) as exc_info:
        service_2.stage(resolved_2, local)
    assert exc_info.value.code == "DOWNGRADE_REJECTED"
    assert len(downloader_2.download_calls) == 0

    # Sequence 3 pending is preserved
    active = store.load_verified(local)
    assert active is not None
    assert active.release_sequence == 3


def test_stage_same_sequence_conflict_against_local(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    # Local sequence 2 with sha_a
    local_l_bytes = b"local-launcher-bytes"
    local_l_sha = hashlib.sha256(local_l_bytes).hexdigest()
    local = _make_local_identity(sequence=2, release_id="r2-stable", launcher_sha=local_l_sha)

    # Remote sequence 2 with different launcher bytes (identity conflict)
    resolved, payloads = _make_resolved_release(
        sequence=2,
        release_id="r2-stable",
        launcher_bytes=b"remote-conflicting-launcher-bytes",
    )
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    with pytest.raises(SoftwareUpdateStageError) as exc_info:
        service.stage(resolved, local)
    assert exc_info.value.code == "SAME_SEQUENCE_IDENTITY_CONFLICT"
    assert len(downloader.download_calls) == 0


def test_stage_same_sequence_conflict_against_pending(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    # Pending has sequence 2 with id "r2-alpha"
    resolved_alpha, payloads_alpha = _make_resolved_release(sequence=2, release_id="r2-alpha")
    service_alpha = StageService(pending_store=store, asset_downloader=FakeAssetDownloader(payloads_alpha))
    assert service_alpha.stage(resolved_alpha, local) is not None

    # Incoming has sequence 2 with id "r2-beta"
    resolved_beta, payloads_beta = _make_resolved_release(sequence=2, release_id="r2-beta")
    downloader_beta = FakeAssetDownloader(payloads_beta)
    service_beta = StageService(pending_store=store, asset_downloader=downloader_beta)

    with pytest.raises(SoftwareUpdateStageError) as exc_info:
        service_beta.stage(resolved_beta, local)
    assert exc_info.value.code == "SAME_SEQUENCE_IDENTITY_CONFLICT"
    assert len(downloader_beta.download_calls) == 0

    active = store.load_verified(local)
    assert active is not None
    assert active.release_id == "r2-alpha"


def test_stage_exact_envelope_bytes_preserved(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    doc = valid_v2_release_document(sequence=2, release_id="r2-stable")
    env = signed_envelope(doc)
    # Specific formatted json with trailing newline
    distinct_envelope_bytes = (canonical_json_dumps(env).decode("utf-8") + "\n").encode("utf-8")

    resolved, payloads = _make_resolved_release(
        sequence=2,
        release_id="r2-stable",
        custom_envelope_bytes=distinct_envelope_bytes,
    )
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    pending = service.stage(resolved, local)
    assert pending is not None
    assert pending.envelope_bytes == distinct_envelope_bytes

    envelope_file = pending.generation_dir / "release-v2.json"
    assert envelope_file.read_bytes() == distinct_envelope_bytes


def test_stage_never_stages_or_replaces_updater_and_never_invokes_helper(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    resolved, payloads = _make_resolved_release(
        sequence=2,
        launcher_bytes=b"MZ-launcher",
        core_bytes=b"PK-core",
        updater_bytes=b"MZ-updater-should-never-be-downloaded",
    )
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    pending = service.stage(resolved, local)
    assert pending is not None

    downloaded_urls = [c["initial_url"] for c in downloader.download_calls]
    assert resolved.updater_asset.browser_download_url not in downloaded_urls

    generation_files = [p.name for p in pending.generation_dir.iterdir()]
    assert "NekoUpdater.exe" not in generation_files
    assert "updater.artifact" not in generation_files


def test_stage_already_pending_same_release_returns_existing_without_redownload(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    _Error, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    resolved, payloads = _make_resolved_release(sequence=2, release_id="r2-stable")
    downloader = FakeAssetDownloader(payloads)
    service = StageService(pending_store=store, asset_downloader=downloader)

    pending_1 = service.stage(resolved, local)
    assert pending_1 is not None
    calls_count = len(downloader.download_calls)
    assert calls_count > 0

    # Call stage again with the exact same release
    pending_2 = service.stage(resolved, local)
    assert pending_2 is not None
    assert pending_2.release_id == pending_1.release_id
    assert pending_2.release_sequence == pending_1.release_sequence
    # No additional downloads
    assert len(downloader.download_calls) == calls_count


def test_stage_cleans_up_temporary_staging_directory_on_failure(tmp_path: Path):
    ok, symbols = lazy_import()
    assert ok and symbols is not None, "SoftwareUpdateStageService must be implemented"
    SoftwareUpdateStageError, StageService = symbols

    store = PendingUpdateStore(tmp_path, get_test_key_registry(), updater_protocol=1)
    local = _make_local_identity(sequence=1)

    resolved, payloads = _make_resolved_release(sequence=2)
    failing_downloader = FakeAssetDownloader(payloads, default_error=GitHubAssetDownloadError("DOWNLOAD_WRITE_FAILED"))
    service = StageService(pending_store=store, asset_downloader=failing_downloader)

    with pytest.raises(SoftwareUpdateStageError):
        service.stage(resolved, local)

    # Check that any tmp_ directories under store.base_dir are gone
    if store.base_dir.exists():
        tmp_dirs = [p for p in store.base_dir.iterdir() if p.name.startswith("tmp_")]
        assert len(tmp_dirs) == 0
