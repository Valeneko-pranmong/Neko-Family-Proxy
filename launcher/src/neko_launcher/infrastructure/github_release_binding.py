from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from neko_launcher.application.software_update_models import ReleaseSet
from neko_launcher.infrastructure.github_asset_downloader import (
    DownloadedManifest,
    GitHubAssetDownloadError,
)
from neko_launcher.infrastructure.github_release import (
    GitHubRelease,
    GitHubReleaseAsset,
    GitHubReleaseDiscoveryError,
)
from neko_launcher.infrastructure.software_update_v2 import (
    V2ReleaseManifestVerifierAdapter,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.manifest_v2 import (
    UPDATER_PROTOCOL_VERSION,
    ReleaseSetV2,
    verify_release_envelope_v2,
)

if TYPE_CHECKING:
    from neko_launcher.infrastructure.github_asset_downloader import GitHubManifestDownloader
    from neko_launcher.infrastructure.github_release import GitHubLatestReleaseGateway

RELEASE_MANIFEST_ASSET_NAME = "release-v2.json"
LAUNCHER_ASSET_NAME = "NekoLauncher.exe"
UPDATER_ASSET_NAME = "NekoUpdater.exe"
CORE_ASSET_NAME = "NekoProxyCore.zip"

__all__ = [
    "RELEASE_MANIFEST_ASSET_NAME",
    "LAUNCHER_ASSET_NAME",
    "UPDATER_ASSET_NAME",
    "CORE_ASSET_NAME",
    "DownloadedManifest",
    "ResolvedGitHubRelease",
    "AuthenticatedReleaseGateway",
    "GitHubReleaseResolverError",
    "GitHubReleaseResolver",
]


@dataclass(frozen=True)
class ResolvedGitHubRelease:
    authenticated_release: ReleaseSet
    authenticated_release_v2: ReleaseSetV2
    envelope_bytes: bytes
    envelope_document: object
    github_release: GitHubRelease
    manifest_asset: GitHubReleaseAsset
    launcher_asset: GitHubReleaseAsset
    updater_asset: GitHubReleaseAsset
    core_asset: GitHubReleaseAsset


class AuthenticatedReleaseGateway(Protocol):
    def resolve(self) -> ResolvedGitHubRelease | None: ...


class GitHubReleaseResolverError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class GitHubReleaseResolver:
    def __init__(
        self,
        *,
        release_gateway: GitHubLatestReleaseGateway,
        manifest_downloader: GitHubManifestDownloader,
        key_registry: Mapping[str, bytes],
        install_root: Path,
        updater_protocol: int = UPDATER_PROTOCOL_VERSION,
    ) -> None:
        self._release_gateway = release_gateway
        self._manifest_downloader = manifest_downloader
        self._key_registry = dict(key_registry)
        self._install_root = Path(install_root)
        self._updater_protocol = updater_protocol

    def resolve(self) -> ResolvedGitHubRelease | None:
        try:
            release = self._release_gateway.fetch()
        except GitHubReleaseDiscoveryError as err:
            if err.code == "GITHUB_RELEASE_UNAVAILABLE":
                raise GitHubReleaseResolverError("GITHUB_RELEASE_UNAVAILABLE") from None
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED") from None
        except Exception:
            raise GitHubReleaseResolverError("GITHUB_RELEASE_UNAVAILABLE") from None

        if release is None:
            return None

        if release.draft or release.prerelease:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        required_names = {
            RELEASE_MANIFEST_ASSET_NAME,
            LAUNCHER_ASSET_NAME,
            UPDATER_ASSET_NAME,
            CORE_ASSET_NAME,
        }
        found_assets: dict[str, list[GitHubReleaseAsset]] = {name: [] for name in required_names}
        for asset in release.assets:
            if asset.name in found_assets:
                found_assets[asset.name].append(asset)

        for name, asset_list in found_assets.items():
            if len(asset_list) != 1:
                raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        manifest_asset = found_assets[RELEASE_MANIFEST_ASSET_NAME][0]
        launcher_asset = found_assets[LAUNCHER_ASSET_NAME][0]
        updater_asset = found_assets[UPDATER_ASSET_NAME][0]
        core_asset = found_assets[CORE_ASSET_NAME][0]

        try:
            manifest = self._manifest_downloader.download(manifest_asset)
        except GitHubAssetDownloadError as err:
            if err.code == "DOWNLOAD_UNAVAILABLE":
                raise GitHubReleaseResolverError("GITHUB_RELEASE_UNAVAILABLE") from None
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED") from None
        except Exception:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED") from None

        if not isinstance(manifest.document, dict):
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        try:
            re_dumped = canonical_json_dumps(manifest.document)
            if re_dumped != manifest.exact_bytes:
                raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
        except Exception:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED") from None

        try:
            release_set_v2, _payload_sha256 = verify_release_envelope_v2(
                manifest.document,
                self._key_registry,
            )
        except Exception:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED") from None

        if release_set_v2.channel != "stable":
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        launcher_comp = release_set_v2.components.get("launcher")
        updater_comp = release_set_v2.components.get("updater")
        core_comp = release_set_v2.components.get("core")
        if launcher_comp is None or updater_comp is None or core_comp is None:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        expected_tag = f"v{launcher_comp.version}"
        if release.tag_name != expected_tag:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        if launcher_comp.artifact_id != LAUNCHER_ASSET_NAME:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
        if launcher_comp.artifact_format != "raw-pe-v1":
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        if updater_comp.artifact_id != UPDATER_ASSET_NAME:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
        if updater_comp.artifact_format != "raw-pe-v1":
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        if core_comp.artifact_id != CORE_ASSET_NAME:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
        if core_comp.artifact_format != "zip-core-v1":
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        if launcher_asset.size != launcher_comp.artifact_size:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
        if updater_asset.size != updater_comp.artifact_size:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
        if core_asset.size != core_comp.artifact_size:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        adapter = V2ReleaseManifestVerifierAdapter(
            self._key_registry,
            updater_protocol=self._updater_protocol,
        )
        try:
            authenticated_release = adapter.verify(manifest.document)
        except Exception:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED") from None

        helper_path = self._install_root / UPDATER_ASSET_NAME
        if not helper_path.is_file():
            raise GitHubReleaseResolverError("UPDATER_INCOMPATIBLE")

        try:
            hasher = hashlib.sha256()
            with helper_path.open("rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            installed_helper_sha256 = hasher.hexdigest().lower()
        except OSError:
            raise GitHubReleaseResolverError("UPDATER_INCOMPATIBLE") from None

        if installed_helper_sha256 != updater_comp.artifact_sha256.lower():
            raise GitHubReleaseResolverError("UPDATER_INCOMPATIBLE")

        proto = release_set_v2.updater_protocol
        if not (proto.minimum <= self._updater_protocol <= proto.maximum):
            raise GitHubReleaseResolverError("UPDATER_INCOMPATIBLE")

        return ResolvedGitHubRelease(
            authenticated_release=authenticated_release,
            authenticated_release_v2=release_set_v2,
            envelope_bytes=manifest.exact_bytes,
            envelope_document=manifest.document,
            github_release=release,
            manifest_asset=manifest_asset,
            launcher_asset=launcher_asset,
            updater_asset=updater_asset,
            core_asset=core_asset,
        )
