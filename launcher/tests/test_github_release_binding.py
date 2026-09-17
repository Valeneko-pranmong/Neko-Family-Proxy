from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from neko_launcher.infrastructure.github_release import (
    GitHubRelease,
    GitHubReleaseAsset,
    GitHubReleaseDiscoveryError,
)
from neko_launcher.infrastructure.github_release_binding import (
    InstalledUpdaterVerification,
    verify_installed_updater,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_legacy_v2_release_document,
    valid_v2_release_document,
)


def _get_binding_module() -> Any:
    try:
        import neko_launcher.infrastructure.github_release_binding as mod
        return mod
    except ImportError:
        pytest.fail("neko_launcher.infrastructure.github_release_binding not implemented", pytrace=False)


class FakeReleaseGateway:
    def __init__(
        self,
        release: GitHubRelease | None = None,
        error: Exception | None = None,
    ) -> None:
        self.release = release
        self.error = error
        self.calls = 0
        self.requested_tag: str | None = None
        self.latest_requested: bool = False

    def fetch(self) -> GitHubRelease | None:
        self.calls += 1
        self.latest_requested = True
        if self.error:
            raise self.error
        return self.release

    def fetch_by_tag(self, tag: str) -> GitHubRelease | None:
        self.calls += 1
        self.requested_tag = tag
        if self.error:
            raise self.error
        return self.release


class FakeManifestDownloader:
    def __init__(
        self,
        manifest: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.manifest = manifest
        self.error = error
        self.downloaded_assets: list[GitHubReleaseAsset] = []

    def download(self, asset: GitHubReleaseAsset) -> Any:
        self.downloaded_assets.append(asset)
        if self.error:
            raise self.error
        assert self.manifest is not None
        return self.manifest


def _setup_resolver_environment(
    tmp_path: Path,
    *,
    sequence: int = 10,
    release_id: str = "rel-10",
    launcher_version: str = "5.1.0",
    launcher_size: int = 1000,
    updater_size: int = 2000,
    core_size: int = 3000,
    helper_bytes: bytes = b"installed helper binary MZ" + b"\x00" * 1974,
    doc_overrides: dict[str, Any] | None = None,
    tag_name: str | None = None,
    include_extra_asset: bool = False,
    extra_asset_name: str = "SHA256SUMS.txt",
    corrupt_signature: bool = False,
    raw_manifest_bytes: bytes | None = None,
) -> dict[str, Any]:
    binding_mod = _get_binding_module()

    install_root = tmp_path / "install_root"
    install_root.mkdir(parents=True, exist_ok=True)
    helper_path = install_root / "NekoUpdater.exe"
    helper_path.write_bytes(helper_bytes)
    helper_sha = hashlib.sha256(helper_bytes).hexdigest()

    doc = valid_v2_release_document(
        sequence=sequence,
        release_id=release_id,
        channel="stable",
        launcher_version=launcher_version,
        launcher_sha="1" * 64,
        launcher_size=launcher_size,
        updater_version="1.0.0",
        updater_sha=helper_sha,
        updater_size=updater_size,
        core_version="2.0.0",
        core_sha="3" * 64,
        core_size=core_size,
    )
    if doc_overrides:
        for k, v in doc_overrides.items():
            if isinstance(v, dict) and k in doc and isinstance(doc[k], dict):
                doc[k].update(v)
            else:
                doc[k] = v

    env = signed_envelope(doc)
    if corrupt_signature:
        env["signature_b64"] = "A" * 86 + "=="

    if raw_manifest_bytes is not None:
        manifest_bytes = raw_manifest_bytes
    else:
        manifest_bytes = canonical_json_dumps(env)

    downloaded_manifest = binding_mod.DownloadedManifest(
        exact_bytes=manifest_bytes,
        document=env,
        actual_size=len(manifest_bytes),
    )

    base_url = "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/"
    assets = [
        GitHubReleaseAsset(1, "release-v2.json", len(manifest_bytes), base_url + "release-v2.json"),
        GitHubReleaseAsset(2, "NekoLauncher.exe", launcher_size, base_url + "NekoLauncher.exe"),
        GitHubReleaseAsset(3, "NekoUpdater.exe", updater_size, base_url + "NekoUpdater.exe"),
        GitHubReleaseAsset(4, "NekoProxyCore.zip", core_size, base_url + "NekoProxyCore.zip"),
    ]
    if include_extra_asset:
        assets.append(GitHubReleaseAsset(5, extra_asset_name, 512, base_url + extra_asset_name))

    effective_tag = tag_name if tag_name is not None else f"v{launcher_version}"
    github_release = GitHubRelease(
        id=100,
        tag_name=effective_tag,
        draft=False,
        prerelease=False,
        assets=tuple(assets),
    )

    gateway = FakeReleaseGateway(release=github_release)
    downloader = FakeManifestDownloader(manifest=downloaded_manifest)
    key_registry = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    resolver = binding_mod.GitHubReleaseResolver(
        release_gateway=gateway,
        manifest_downloader=downloader,
        key_registry=key_registry,
        install_root=install_root,
        updater_protocol=1,
    )

    return {
        "resolver": resolver,
        "gateway": gateway,
        "downloader": downloader,
        "install_root": install_root,
        "helper_path": helper_path,
        "github_release": github_release,
        "downloaded_manifest": downloaded_manifest,
        "key_registry": key_registry,
        "doc": doc,
        "envelope": env,
        "manifest_bytes": manifest_bytes,
    }


def test_resolver_successful_flow_preserves_exact_bytes(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path, include_extra_asset=True)
    resolver = env_data["resolver"]

    resolved = resolver.resolve()
    assert resolved is not None

    # Authenticated models
    assert resolved.authenticated_release.release_sequence == 10
    assert resolved.authenticated_release.release_id == "rel-10"
    assert resolved.authenticated_release.channel == "stable"
    assert resolved.authenticated_release_v2.schema_version == 2

    # Exact bytes preserved
    assert resolved.envelope_bytes == env_data["manifest_bytes"]
    assert resolved.envelope_document == env_data["envelope"]

    # Bound assets
    assert resolved.github_release == env_data["github_release"]
    assert resolved.manifest_asset.name == "release-v2.json"
    assert resolved.launcher_asset.name == "NekoLauncher.exe"
    assert resolved.updater_asset.name == "NekoUpdater.exe"
    assert resolved.core_asset.name == "NekoProxyCore.zip"


def test_resolver_returns_none_when_release_is_none(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    env_data["gateway"].release = None
    resolver = env_data["resolver"]

    assert resolver.resolve() is None


def test_resolver_raises_unavailable_on_gateway_transport_error(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    env_data["gateway"].error = GitHubReleaseDiscoveryError("GITHUB_RELEASE_UNAVAILABLE")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "GITHUB_RELEASE_UNAVAILABLE"


def test_resolver_raises_unavailable_on_manifest_download_transport_error(tmp_path: Path) -> None:
    from neko_launcher.infrastructure.github_asset_downloader import GitHubAssetDownloadError

    env_data = _setup_resolver_environment(tmp_path)
    env_data["downloader"].error = GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "GITHUB_RELEASE_UNAVAILABLE"


def test_resolver_raises_manifest_rejected_on_ineligible_release(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    env_data["gateway"].error = GitHubReleaseDiscoveryError("GITHUB_RELEASE_INELIGIBLE")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_on_corrupt_signature(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path, corrupt_signature=True)
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_on_noncanonical_manifest_bytes(tmp_path: Path) -> None:
    # Add non-canonical extra spaces
    noncanonical_bytes = b'{"envelope_version": 1,  "key_id": "neko-update-test-1"}'
    env_data = _setup_resolver_environment(tmp_path, raw_manifest_bytes=noncanonical_bytes)
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_on_legacy_two_component_envelope(tmp_path: Path) -> None:
    legacy_doc = valid_legacy_v2_release_document(sequence=10, release_id="rel-10")
    legacy_env = signed_envelope(legacy_doc)
    legacy_bytes = canonical_json_dumps(legacy_env)

    env_data = _setup_resolver_environment(
        tmp_path,
        doc_overrides=legacy_doc,
        raw_manifest_bytes=legacy_bytes,
    )
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_on_tag_mismatch(tmp_path: Path) -> None:
    # Signed launcher version is 5.1.0, but tag is v9.9.9
    env_data = _setup_resolver_environment(tmp_path, launcher_version="5.1.0", tag_name="v9.9.9")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_on_tag_missing_v_prefix(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path, launcher_version="5.1.0", tag_name="5.1.0")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_on_non_stable_channel(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path, doc_overrides={"channel": "beta"})
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_when_required_asset_missing(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    # Remove NekoProxyCore.zip asset from release
    current_assets = env_data["github_release"].assets
    filtered_assets = tuple(a for a in current_assets if a.name != "NekoProxyCore.zip")
    env_data["gateway"].release = GitHubRelease(
        id=env_data["github_release"].id,
        tag_name=env_data["github_release"].tag_name,
        draft=False,
        prerelease=False,
        assets=filtered_assets,
    )
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_raises_manifest_rejected_when_required_asset_duplicated(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    current_assets = list(env_data["github_release"].assets)
    # Duplicate NekoLauncher.exe with different ID
    dup = GitHubReleaseAsset(99, "NekoLauncher.exe", 1000, current_assets[1].browser_download_url)
    current_assets.append(dup)
    env_data["gateway"].release = GitHubRelease(
        id=env_data["github_release"].id,
        tag_name=env_data["github_release"].tag_name,
        draft=False,
        prerelease=False,
        assets=tuple(current_assets),
    )
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


@pytest.mark.parametrize("product_asset", ["NekoLauncher.exe", "NekoUpdater.exe", "NekoProxyCore.zip"])
def test_resolver_raises_manifest_rejected_on_product_api_size_mismatch(
    tmp_path: Path, product_asset: str
) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    current_assets = list(env_data["github_release"].assets)
    # Tamper with asset size reported by GitHub API
    for i, a in enumerate(current_assets):
        if a.name == product_asset:
            current_assets[i] = GitHubReleaseAsset(a.id, a.name, a.size + 123, a.browser_download_url)
    env_data["gateway"].release = GitHubRelease(
        id=env_data["github_release"].id,
        tag_name=env_data["github_release"].tag_name,
        draft=False,
        prerelease=False,
        assets=tuple(current_assets),
    )
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "RELEASE_MANIFEST_REJECTED"


def test_resolver_ignores_manifest_api_size_disagreement_when_signature_valid(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    current_assets = list(env_data["github_release"].assets)
    # Tamper with release-v2.json size in API metadata (untrusted size)
    for i, a in enumerate(current_assets):
        if a.name == "release-v2.json":
            current_assets[i] = GitHubReleaseAsset(a.id, a.name, a.size + 42, a.browser_download_url)
    env_data["gateway"].release = GitHubRelease(
        id=env_data["github_release"].id,
        tag_name=env_data["github_release"].tag_name,
        draft=False,
        prerelease=False,
        assets=tuple(current_assets),
    )
    resolver = env_data["resolver"]

    # Manifest API size is not signed authority - it must not cause rejection if signature and bytes pass
    # But wait, does downloader check it? Downloader was tested in Task 3. In resolver:
    # Resolver trusts the manifest returned by manifest downloader
    resolved = resolver.resolve()
    assert resolved is not None


def test_resolver_raises_updater_incompatible_when_helper_missing(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    env_data["helper_path"].unlink()
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "UPDATER_INCOMPATIBLE"


def test_resolver_raises_updater_incompatible_on_helper_hash_mismatch(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    # Write different contents to installed helper
    env_data["helper_path"].write_bytes(b"tampered installed helper bytes")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "UPDATER_INCOMPATIBLE"


def test_resolver_raises_updater_incompatible_on_protocol_mismatch(tmp_path: Path) -> None:
    # Helper requires protocol 2..2, but resolver has protocol 1
    doc_overrides = {"updater_protocol": {"minimum": 2, "maximum": 2}}
    env_data = _setup_resolver_environment(tmp_path, doc_overrides=doc_overrides)
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "UPDATER_INCOMPATIBLE"


def test_resolver_error_sanitization_does_not_leak_urls_or_secrets(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    # Force an error
    env_data["gateway"].error = GitHubReleaseDiscoveryError("GITHUB_RELEASE_UNAVAILABLE")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    err = exc_info.value
    assert str(err) == "GITHUB_RELEASE_UNAVAILABLE"
    assert "https://" not in str(err)
    assert "api.github.com" not in str(err)


def test_resolver_accepts_channel_profile(tmp_path: Path) -> None:
    from neko_launcher.infrastructure.update_channel_profile import UpdateChannelProfile
    from neko_launcher.updater.trust_profile import VerifiedUpdateTrustProfile

    binding_mod = _get_binding_module()
    env_data = _setup_resolver_environment(tmp_path)

    verified = VerifiedUpdateTrustProfile(
        profile_id="proof-v512",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates-Proof",
        release_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
        keyset_sha256="1" * 64,
        profile_envelope_sha256="2" * 64,
        profile_authority_key_id="auth",
        profile_authority_public_key_sha256="3" * 64,
    )
    profile = UpdateChannelProfile.from_verified(verified)

    resolver = binding_mod.GitHubReleaseResolver(
        release_gateway=env_data["gateway"],
        manifest_downloader=env_data["downloader"],
        channel_profile=profile,
        install_root=env_data["install_root"],
        updater_protocol=1,
    )

    resolved = resolver.resolve()
    assert resolved is not None
    assert resolved.authenticated_release.channel == "stable"


def test_corrupt_updater_requires_reinstall(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    resolved = env_data["resolver"].resolve()
    assert resolved is not None
    release_v2 = resolved.authenticated_release_v2
    updater_path = tmp_path / "NekoUpdater.exe"
    # Write bytes with exact expected size 2000 but corrupt content
    updater_path.write_bytes(b"tampered installed helper bytes" + b"\x01" * 1969)

    result = verify_installed_updater(
        updater_path=updater_path,
        bound_release=release_v2,
        supported_protocol=1,
    )
    assert result.reinstall_required is True
    assert result.trusted is False
    assert result.actual_sha256 != result.expected_sha256
    assert result.reason == "UPDATER_HASH_MISMATCH"


def test_missing_updater_requires_reinstall(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    resolved = env_data["resolver"].resolve()
    assert resolved is not None
    release_v2 = resolved.authenticated_release_v2
    nonexistent = tmp_path / "NonexistentUpdater.exe"

    result = verify_installed_updater(
        updater_path=nonexistent,
        bound_release=release_v2,
        supported_protocol=1,
    )
    assert result.reinstall_required is True
    assert result.trusted is False
    assert result.actual_sha256 is None
    assert result.reason == "UPDATER_MISSING"


def test_wrong_size_updater_requires_reinstall(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    resolved = env_data["resolver"].resolve()
    assert resolved is not None
    release_v2 = resolved.authenticated_release_v2
    updater_path = tmp_path / "NekoUpdater.exe"
    # Write bytes with different length than updater_size (2000)
    updater_path.write_bytes(b"short bytes")

    result = verify_installed_updater(
        updater_path=updater_path,
        bound_release=release_v2,
        supported_protocol=1,
    )
    assert result.reinstall_required is True
    assert result.trusted is False
    assert result.reason == "UPDATER_SIZE_MISMATCH"


def test_incompatible_protocol_updater_requires_reinstall(tmp_path: Path) -> None:
    doc_overrides = {"updater_protocol": {"minimum": 2, "maximum": 2}}
    env_data = _setup_resolver_environment(tmp_path, doc_overrides=doc_overrides)
    helper_path = env_data["helper_path"]
    from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
    release_v2, _ = verify_release_envelope_v2(
        env_data["downloader"].manifest.document,
        {TEST_KEY_ID: TEST_PUBLIC_KEY},
    )

    result = verify_installed_updater(
        updater_path=helper_path,
        bound_release=release_v2,
        supported_protocol=1,
    )
    assert result.reinstall_required is True
    assert result.trusted is False
    assert result.reason == "UPDATER_PROTOCOL_INCOMPATIBLE"


def test_valid_updater_verification_succeeds(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    resolved = env_data["resolver"].resolve()
    assert resolved is not None
    helper_path = env_data["helper_path"]

    result = verify_installed_updater(
        updater_path=helper_path,
        bound_release=resolved,
        supported_protocol=1,
    )
    assert isinstance(result, InstalledUpdaterVerification)
    assert result.trusted is True
    assert result.reinstall_required is False
    assert result.actual_sha256 == result.expected_sha256
    assert result.reason is None


def test_resolver_raises_updater_incompatible_on_helper_size_mismatch(tmp_path: Path) -> None:
    env_data = _setup_resolver_environment(tmp_path)
    # Tamper size: write different length to installed helper
    env_data["helper_path"].write_bytes(b"different size bytes")
    resolver = env_data["resolver"]

    with pytest.raises(Exception) as exc_info:
        resolver.resolve()

    assert exc_info.value.code == "UPDATER_INCOMPATIBLE"


def test_file_check_resolves_exact_committed_tag_not_latest() -> None:
    from neko_launcher.application.software_update_models import InstalledReleaseSelector
    from neko_launcher.infrastructure.github_release_binding import resolve_exact_release

    class FakeGitHub:
        def __init__(self) -> None:
            self.requested_tag: str | None = None
            self.latest_requested: bool = False

        def fetch_by_tag(self, tag: str) -> Any:
            self.requested_tag = tag
            return None

        def fetch(self) -> Any:
            self.latest_requested = True
            return None

    fake_github = FakeGitHub()
    selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    resolve_exact_release(client=fake_github, selector=selector)
    assert fake_github.requested_tag == "v5.1.3"
    assert fake_github.latest_requested is False


def test_resolve_exact_release_via_resolver(tmp_path: Path) -> None:
    from neko_launcher.application.software_update_models import InstalledReleaseSelector
    from neko_launcher.infrastructure.github_release_binding import resolve_exact_release

    env_data = _setup_resolver_environment(
        tmp_path,
        sequence=9,
        release_id="stable-0009",
        launcher_version="5.1.3",
        tag_name="v5.1.3",
    )
    resolver = env_data["resolver"]
    gateway = env_data["gateway"]

    selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    resolved = resolve_exact_release(resolver=resolver, selector=selector)
    assert resolved is not None
    assert resolved.authenticated_release.channel == "stable"
    assert resolved.authenticated_release_v2.release_sequence == 9
    assert gateway.requested_tag == "v5.1.3"
    assert gateway.latest_requested is False


def test_resolve_exact_mismatched_sequence_fails_closed(tmp_path: Path) -> None:
    from neko_launcher.application.software_update_models import InstalledReleaseSelector
    from neko_launcher.infrastructure.github_release_binding import (
        GitHubReleaseResolverError,
        resolve_exact_release,
    )

    env_data = _setup_resolver_environment(
        tmp_path,
        sequence=9,
        release_id="stable-0009",
        launcher_version="5.1.3",
        tag_name="v5.1.3",
    )
    resolver = env_data["resolver"]

    mismatched_selector = InstalledReleaseSelector(
        sequence=10,
        release_id="stable-0009",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    with pytest.raises(GitHubReleaseResolverError, match="RELEASE_MANIFEST_REJECTED"):
        resolve_exact_release(resolver=resolver, selector=mismatched_selector)


def test_resolve_exact_mismatched_release_id_fails_closed(tmp_path: Path) -> None:
    from neko_launcher.application.software_update_models import InstalledReleaseSelector
    from neko_launcher.infrastructure.github_release_binding import (
        GitHubReleaseResolverError,
        resolve_exact_release,
    )

    env_data = _setup_resolver_environment(
        tmp_path,
        sequence=9,
        release_id="stable-0009",
        launcher_version="5.1.3",
        tag_name="v5.1.3",
    )
    resolver = env_data["resolver"]

    mismatched_selector = InstalledReleaseSelector(
        sequence=9,
        release_id="wrong-id",
        version="5.1.3",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    with pytest.raises(GitHubReleaseResolverError, match="RELEASE_MANIFEST_REJECTED"):
        resolve_exact_release(resolver=resolver, selector=mismatched_selector)


def test_resolve_exact_mismatched_version_fails_closed(tmp_path: Path) -> None:
    from neko_launcher.application.software_update_models import InstalledReleaseSelector
    from neko_launcher.infrastructure.github_release_binding import (
        GitHubReleaseResolverError,
        resolve_exact_release,
    )

    env_data = _setup_resolver_environment(
        tmp_path,
        sequence=9,
        release_id="stable-0009",
        launcher_version="5.1.3",
        tag_name="v5.1.3",
    )
    resolver = env_data["resolver"]

    mismatched_selector = InstalledReleaseSelector(
        sequence=9,
        release_id="stable-0009",
        version="5.1.4",
        tag_name="v5.1.3",
        target_commit="a" * 40,
    )
    with pytest.raises(GitHubReleaseResolverError, match="RELEASE_MANIFEST_REJECTED"):
        resolve_exact_release(resolver=resolver, selector=mismatched_selector)
