from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from neko_launcher.application.software_update_models import (
    LocalReleaseIdentity,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.application.software_update_pending import VerifiedPendingUpdate
from neko_launcher.application.software_update_policy import evaluate_release
from neko_launcher.infrastructure.github_asset_downloader import (
    GitHubAssetDownloadError,
    GitHubAssetDownloader,
)

if TYPE_CHECKING:
    from neko_launcher.infrastructure.github_release_binding import ResolvedGitHubRelease
    from neko_launcher.infrastructure.software_update_pending_store import (
        PendingUpdateStore,
    )

__all__ = [
    "SoftwareUpdateStageError",
    "SoftwareUpdateStageService",
]


class SoftwareUpdateStageError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class SoftwareUpdateStageService:
    def __init__(
        self,
        *,
        pending_store: PendingUpdateStore,
        asset_downloader: GitHubAssetDownloader,
    ) -> None:
        self._pending_store = pending_store
        self._asset_downloader = asset_downloader

    def stage(
        self,
        resolved: ResolvedGitHubRelease,
        local: LocalReleaseIdentity,
    ) -> VerifiedPendingUpdate | None:
        check_result = evaluate_release(
            local,
            resolved.authenticated_release,
            UpdateInvocationReason.STARTUP,
        )

        if check_result.diagnostic_code == UpdateDiagnosticCode.DOWNGRADE_REJECTED:
            raise SoftwareUpdateStageError("DOWNGRADE_REJECTED")
        if (
            check_result.diagnostic_code
            == UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT
        ):
            raise SoftwareUpdateStageError("SAME_SEQUENCE_IDENTITY_CONFLICT")
        if check_result.diagnostic_code is not None:
            raise SoftwareUpdateStageError(check_result.diagnostic_code.value)

        if (
            check_result.state == UpdateState.LATEST
            or not check_result.changed_components
        ):
            return None

        # Check supersession against existing valid pending update
        existing_pending = self._pending_store.load_verified(local)
        if existing_pending is not None:
            if (
                resolved.authenticated_release.release_sequence
                < existing_pending.release_sequence
            ):
                raise SoftwareUpdateStageError("DOWNGRADE_REJECTED")
            if (
                resolved.authenticated_release.release_sequence
                == existing_pending.release_sequence
            ):
                if (
                    resolved.authenticated_release.release_id
                    != existing_pending.release_id
                ):
                    raise SoftwareUpdateStageError("SAME_SEQUENCE_IDENTITY_CONFLICT")
                return existing_pending

        # Stage changed Launcher and Core only; never stage or replace Updater
        changed_components = tuple(
            c for c in check_result.changed_components if c in ("launcher", "core")
        )
        if not changed_components:
            return None

        staging_dir = self._pending_store.base_dir / f"tmp_stage_{uuid.uuid4().hex}"
        self._pending_store.base_dir.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=False)

        staged_files: dict[str, Path] = {}
        try:
            for comp_name in changed_components:
                if comp_name == "launcher":
                    asset = resolved.launcher_asset
                    comp_v2 = resolved.authenticated_release_v2.components.get("launcher")
                    dest_path = staging_dir / "launcher.artifact"
                elif comp_name == "core":
                    asset = resolved.core_asset
                    comp_v2 = resolved.authenticated_release_v2.components.get("core")
                    dest_path = staging_dir / "core.artifact.zip"
                else:
                    continue

                if comp_v2 is None:
                    raise SoftwareUpdateStageError(
                        "RELEASE_MANIFEST_REJECTED",
                        f"Component {comp_name} missing from release manifest",
                    )

                try:
                    self._asset_downloader.download(
                        initial_url=asset.browser_download_url,
                        destination=dest_path,
                        expected_size=comp_v2.artifact_size,
                        expected_sha256=comp_v2.artifact_sha256,
                    )
                except GitHubAssetDownloadError as err:
                    raise SoftwareUpdateStageError(err.code) from err
                except Exception as err:
                    raise SoftwareUpdateStageError("DOWNLOAD_FAILED") from err

                staged_files[comp_name] = dest_path

            try:
                promoted = self._pending_store.promote(
                    envelope_bytes=resolved.envelope_bytes,
                    release=resolved.authenticated_release_v2,
                    changed_components=changed_components,
                    staged_files=staged_files,
                )
            except ValueError as err:
                msg = str(err)
                if "Downgrade rejected" in msg:
                    raise SoftwareUpdateStageError("DOWNGRADE_REJECTED") from err
                if "Same-sequence identity conflict" in msg:
                    raise SoftwareUpdateStageError(
                        "SAME_SEQUENCE_IDENTITY_CONFLICT"
                    ) from err
                raise SoftwareUpdateStageError("STAGE_PROMOTION_FAILED") from err
            except Exception as err:
                raise SoftwareUpdateStageError("STAGE_PROMOTION_FAILED") from err

            return promoted
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
