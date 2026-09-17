from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from neko_launcher.application.software_update_models import (
    InstalledReleaseSelector,
    ReleaseSet,
)
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
    from neko_launcher.infrastructure.update_channel_profile import UpdateChannelProfile

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
    "InstalledUpdaterVerification",
    "verify_installed_updater",
    "resolve_exact_release",
]


@dataclass(frozen=True)
class InstalledUpdaterVerification:
    trusted: bool
    reinstall_required: bool
    expected_sha256: str
    actual_sha256: str | None
    reason: str | None


def verify_installed_updater(
    updater_path: Path,
    bound_release: object,
    supported_protocol: int = UPDATER_PROTOCOL_VERSION,
) -> InstalledUpdaterVerification:
    target_release: object = bound_release
    if (
        hasattr(target_release, "authenticated_release_v2")
        and target_release.authenticated_release_v2 is not None
    ):
        target_release = target_release.authenticated_release_v2

    updater_comp: object = None
    if hasattr(target_release, "components"):
        comps = target_release.components
        if isinstance(comps, Mapping) or isinstance(comps, dict):
            updater_comp = comps.get("updater")
        elif isinstance(comps, (list, tuple)):
            updater_comp = next(
                (c for c in comps if getattr(c, "name", None) == "updater"),
                None,
            )
    elif hasattr(target_release, "updater_component"):
        updater_comp = target_release.updater_component
    elif hasattr(target_release, "updater"):
        updater_comp = target_release.updater

    if updater_comp is not None:
        expected_sha256 = getattr(
            updater_comp,
            "artifact_sha256",
            getattr(
                updater_comp,
                "sha256",
                getattr(updater_comp, "installed_identity_sha256", ""),
            ),
        )
        expected_size = getattr(
            updater_comp,
            "artifact_size",
            getattr(updater_comp, "size", None),
        )
    else:
        expected_sha256 = getattr(
            bound_release,
            "updater_sha256",
            getattr(
                bound_release,
                "updater_sha",
                getattr(target_release, "updater_sha256", ""),
            ),
        )
        expected_size = getattr(
            bound_release,
            "updater_size",
            getattr(target_release, "updater_size", None),
        )

    if isinstance(expected_sha256, str):
        expected_sha256 = expected_sha256.lower()
    else:
        expected_sha256 = ""

    proto = getattr(
        target_release,
        "updater_protocol",
        getattr(bound_release, "updater_protocol", None),
    )

    u_path = Path(updater_path)
    if not u_path.is_file():
        return InstalledUpdaterVerification(
            trusted=False,
            reinstall_required=True,
            expected_sha256=expected_sha256,
            actual_sha256=None,
            reason="UPDATER_MISSING",
        )

    if expected_size is not None:
        try:
            actual_size = u_path.stat().st_size
        except OSError:
            return InstalledUpdaterVerification(
                trusted=False,
                reinstall_required=True,
                expected_sha256=expected_sha256,
                actual_sha256=None,
                reason="UPDATER_IO_ERROR",
            )
        if actual_size != expected_size:
            return InstalledUpdaterVerification(
                trusted=False,
                reinstall_required=True,
                expected_sha256=expected_sha256,
                actual_sha256=None,
                reason="UPDATER_SIZE_MISMATCH",
            )

    try:
        hasher = hashlib.sha256()
        with u_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        actual_sha256 = hasher.hexdigest().lower()
    except OSError:
        return InstalledUpdaterVerification(
            trusted=False,
            reinstall_required=True,
            expected_sha256=expected_sha256,
            actual_sha256=None,
            reason="UPDATER_IO_ERROR",
        )

    if not expected_sha256 or actual_sha256 != expected_sha256:
        return InstalledUpdaterVerification(
            trusted=False,
            reinstall_required=True,
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
            reason="UPDATER_HASH_MISMATCH",
        )

    if proto is not None:
        if isinstance(proto, int):
            proto_ok = proto == supported_protocol
        elif hasattr(proto, "minimum") and hasattr(proto, "maximum"):
            proto_ok = proto.minimum <= supported_protocol <= proto.maximum
        elif isinstance(proto, (list, tuple)) and len(proto) == 2:
            proto_ok = proto[0] <= supported_protocol <= proto[1]
        else:
            proto_ok = False
        if not proto_ok:
            return InstalledUpdaterVerification(
                trusted=False,
                reinstall_required=True,
                expected_sha256=expected_sha256,
                actual_sha256=actual_sha256,
                reason="UPDATER_PROTOCOL_INCOMPATIBLE",
            )

    return InstalledUpdaterVerification(
        trusted=True,
        reinstall_required=False,
        expected_sha256=expected_sha256,
        actual_sha256=actual_sha256,
        reason=None,
    )


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
    def resolve_exact(self, selector: InstalledReleaseSelector) -> ResolvedGitHubRelease | None: ...


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
        key_registry: Mapping[str, bytes] | None = None,
        channel_profile: UpdateChannelProfile | None = None,
        install_root: Path,
        updater_protocol: int = UPDATER_PROTOCOL_VERSION,
    ) -> None:
        self._release_gateway = release_gateway
        self._manifest_downloader = manifest_downloader
        if channel_profile is not None and key_registry is None:
            self._key_registry = dict(channel_profile.release_public_keys)
        elif key_registry is not None:
            self._key_registry = dict(key_registry)
        else:
            raise ValueError("Either channel_profile or key_registry must be provided")
        self._channel_profile = channel_profile
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

        return self._process_release(release)

    def resolve_exact(
        self,
        selector: InstalledReleaseSelector,
    ) -> ResolvedGitHubRelease | None:
        if not isinstance(selector, InstalledReleaseSelector):
            raise ValueError("selector must be an InstalledReleaseSelector")
        try:
            release = self._release_gateway.fetch_by_tag(selector.tag_name)
        except GitHubReleaseDiscoveryError as err:
            if err.code == "GITHUB_RELEASE_UNAVAILABLE":
                raise GitHubReleaseResolverError("GITHUB_RELEASE_UNAVAILABLE") from None
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED") from None
        except Exception:
            raise GitHubReleaseResolverError("GITHUB_RELEASE_UNAVAILABLE") from None

        if release is None:
            return None

        return self._process_release(release, expected_selector=selector)

    def _process_release(
        self,
        release: GitHubRelease,
        expected_selector: InstalledReleaseSelector | None = None,
    ) -> ResolvedGitHubRelease:
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

        if expected_selector is not None:
            if release_set_v2.release_sequence != expected_selector.sequence:
                raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
            if release_set_v2.release_id != expected_selector.release_id:
                raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")
            if release.tag_name != expected_selector.tag_name:
                raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        expected_tag = f"v{launcher_comp.version}"
        if release.tag_name != expected_tag:
            raise GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED")

        if expected_selector is not None:
            if launcher_comp.version != expected_selector.version:
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
        verification = verify_installed_updater(
            updater_path=helper_path,
            bound_release=release_set_v2,
            supported_protocol=self._updater_protocol,
        )
        if not verification.trusted or verification.reinstall_required:
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


def resolve_exact_release(
    selector_or_client: Any = None,
    maybe_selector: InstalledReleaseSelector | None = None,
    *,
    client: Any = None,
    resolver: GitHubReleaseResolver | None = None,
    selector: InstalledReleaseSelector | None = None,
) -> Any:
    target_selector = selector or maybe_selector
    target = client or resolver
    if isinstance(selector_or_client, InstalledReleaseSelector):
        target_selector = selector_or_client
    elif selector_or_client is not None and target is None:
        target = selector_or_client

    if target_selector is None:
        raise ValueError("selector is required")
    if target is None:
        raise ValueError("client or resolver is required")

    if hasattr(target, "resolve_exact"):
        return target.resolve_exact(target_selector)
    if hasattr(target, "fetch_by_tag"):
        return target.fetch_by_tag(target_selector.tag_name)
    raise ValueError(f"Unsupported client or resolver: {type(target)!r}")
