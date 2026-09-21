from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path
from typing import Any, Literal

from neko_launcher.application.software_update_models import InstalledReleaseSelector
from neko_launcher.infrastructure.github_release_binding import verify_installed_updater
from neko_launcher.updater.manifest_v2 import UPDATER_PROTOCOL_VERSION


class IntegrityStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    HASH_MISMATCH = "hash_mismatch"
    UNTRUSTED_UPDATER = "untrusted_updater"


@dataclass(frozen=True)
class FileIntegrityItem:
    component: Literal["launcher", "updater", "core"]
    path: Path
    expected_size: int
    expected_sha256: str
    actual_size: int | None
    actual_sha256: str | None
    status: IntegrityStatus


@dataclass(frozen=True)
class FileIntegrityReport:
    selector: InstalledReleaseSelector
    items: tuple[FileIntegrityItem, ...]
    repairable_components: tuple[Literal["launcher", "core"], ...]
    reinstall_required: bool
    version: str | None = None
    is_latest: bool | None = None
    latest_version: str | None = None


def _compute_sha256_stream(file_path: Path, chunk_size: int = 65536) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with file_path.open("rb") as f:
        while chunk := f.read(chunk_size):
            size += len(chunk)
            hasher.update(chunk)
    return size, hasher.hexdigest().lower()


def check_installed_files(
    install_root: Path,
    release: Any,
) -> FileIntegrityReport:
    root = Path(install_root)
    target_release = release
    if (
        hasattr(target_release, "authenticated_release_v2")
        and target_release.authenticated_release_v2 is not None
    ):
        target_release = target_release.authenticated_release_v2

    selector = getattr(release, "selector", None)
    if selector is None:
        selector = getattr(release, "installed_selector", None)
    if selector is None:
        selector = getattr(target_release, "selector", None)
    if selector is None and hasattr(target_release, "release_sequence"):
        comps = getattr(target_release, "components", {})
        l_comp = comps.get("launcher") if isinstance(comps, dict) else None
        l_ver = getattr(l_comp, "version", "0.0.0") if l_comp else "0.0.0"
        gh_rel = getattr(release, "github_release", None)
        tag_name = getattr(gh_rel, "tag_name", f"v{l_ver}")
        target_commit = getattr(gh_rel, "target_commitish", "0" * 40)
        selector = InstalledReleaseSelector(
            sequence=target_release.release_sequence,
            release_id=target_release.release_id,
            version=l_ver,
            tag_name=tag_name,
            target_commit=target_commit,
        )
    if not isinstance(selector, InstalledReleaseSelector):
        raise ValueError(
            f"release must provide a valid InstalledReleaseSelector, got {type(selector)}"
        )

    components_dict = getattr(target_release, "components", {})
    if not isinstance(components_dict, dict):
        raise ValueError("release must provide components mapping")

    items: list[FileIntegrityItem] = []
    items_by_component: dict[str, FileIntegrityItem] = {}

    for comp_name in ("launcher", "updater", "core"):
        comp = components_dict.get(comp_name)
        if comp is None:
            raise ValueError(f"Release missing component {comp_name}")

        if comp_name == "launcher":
            artifact_id = getattr(comp, "artifact_id", "NekoLauncher.exe")
            candidate_paths = [root / "NekoLauncher.exe", root / artifact_id]
            path = next((p for p in candidate_paths if p.is_file()), root / "NekoLauncher.exe")
            expected_size = getattr(comp, "artifact_size", getattr(comp, "size", 0))
            expected_sha256 = getattr(
                comp,
                "installed_identity_sha256",
                getattr(comp, "artifact_sha256", getattr(comp, "sha256", "")),
            ).lower()
        elif comp_name == "updater":
            artifact_id = getattr(comp, "artifact_id", "NekoUpdater.exe")
            candidate_paths = [root / "NekoUpdater.exe", root / artifact_id]
            path = next((p for p in candidate_paths if p.is_file()), root / "NekoUpdater.exe")
            expected_size = getattr(comp, "artifact_size", getattr(comp, "size", 0))
            expected_sha256 = getattr(
                comp,
                "installed_identity_sha256",
                getattr(comp, "artifact_sha256", getattr(comp, "sha256", "")),
            ).lower()
        else:  # core
            artifact_id = getattr(comp, "artifact_id", "NekoProxyCore.zip")
            candidate_paths = [
                root / artifact_id,
                root / "ProxyCore" / "core-manifest.json",
                root / "core-manifest.json",
                root / "ProxyCore" / "canonical-core-manifest.json",
                root / "CoreBundle" / "core-manifest.json",
                root / "ProxyCore" / "NekoProxyCore.exe",
                root / "NekoProxyCore.exe",
            ]
            path = next((p for p in candidate_paths if p.is_file()), None)
            if path is None:
                if (root / "ProxyCore").is_dir():
                    path = root / "ProxyCore" / "core-manifest.json"
                elif artifact_id and not artifact_id.endswith(".zip"):
                    path = root / artifact_id
                else:
                    path = root / artifact_id

            if path.name in ("core-manifest.json", "canonical-core-manifest.json"):
                expected_sha256 = getattr(
                    comp,
                    "installed_identity_sha256",
                    getattr(comp, "artifact_sha256", ""),
                ).lower()
                expected_size = getattr(
                    comp,
                    "installed_identity_size",
                    getattr(comp, "installed_size", None),
                )
            else:
                expected_sha256 = getattr(
                    comp,
                    "installed_identity_sha256",
                    getattr(comp, "artifact_sha256", getattr(comp, "sha256", "")),
                ).lower()
                expected_size = getattr(comp, "artifact_size", getattr(comp, "size", 0))

        if not path.is_file():
            status = IntegrityStatus.MISSING
            actual_size = None
            actual_sha256 = None
        else:
            try:
                actual_size = path.stat().st_size
            except OSError:
                actual_size = None
                actual_sha256 = None
                status = IntegrityStatus.MISSING

            if actual_size is not None:
                if expected_size is not None and actual_size != expected_size:
                    status = IntegrityStatus.SIZE_MISMATCH
                    actual_sha256 = None
                else:
                    try:
                        _, actual_sha256 = _compute_sha256_stream(path)
                    except OSError:
                        status = IntegrityStatus.MISSING
                        actual_sha256 = None
                    else:
                        if actual_sha256 != expected_sha256:
                            status = IntegrityStatus.HASH_MISMATCH
                        else:
                            status = IntegrityStatus.OK

        # Extra verification for Updater component
        if comp_name == "updater":
            verification = verify_installed_updater(
                updater_path=path,
                bound_release=target_release,
                supported_protocol=UPDATER_PROTOCOL_VERSION,
            )
            if not verification.trusted:
                if verification.reason == "UPDATER_PROTOCOL_INCOMPATIBLE":
                    status = IntegrityStatus.UNTRUSTED_UPDATER
                elif status == IntegrityStatus.OK:
                    status = IntegrityStatus.UNTRUSTED_UPDATER

        item = FileIntegrityItem(
            component=comp_name,
            path=path,
            expected_size=expected_size if expected_size is not None else (actual_size or 0),
            expected_sha256=expected_sha256,
            actual_size=actual_size,
            actual_sha256=actual_sha256,
            status=status,
        )
        items.append(item)
        items_by_component[comp_name] = item

    updater_status = items_by_component["updater"].status
    if updater_status != IntegrityStatus.OK:
        reinstall_required = True
        repairable_components: tuple[Literal["launcher", "core"], ...] = ()
    else:
        reinstall_required = False
        rep_list: list[Literal["launcher", "core"]] = []
        if items_by_component["launcher"].status != IntegrityStatus.OK:
            rep_list.append("launcher")
        if items_by_component["core"].status != IntegrityStatus.OK:
            rep_list.append("core")
        repairable_components = tuple(rep_list)

    return FileIntegrityReport(
        selector=selector,
        items=tuple(items),
        repairable_components=repairable_components,
        reinstall_required=reinstall_required,
        version=getattr(selector, "version", None),
    )
