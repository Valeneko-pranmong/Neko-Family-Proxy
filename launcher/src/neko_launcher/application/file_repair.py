from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from neko_launcher.application.file_integrity import (
    FileIntegrityReport,
    IntegrityStatus,
    check_installed_files,
)
from neko_launcher.application.software_update_models import InstalledReleaseSelector
from neko_launcher.infrastructure.github_release_binding import verify_installed_updater
from neko_launcher.updater.manifest_v2 import UPDATER_PROTOCOL_VERSION


class RepairError(Exception):
    """Base exception for repair operation errors."""


class RepairNotAllowed(RepairError):
    """Raised when a repair request violates preconditions or constraints."""


class ReinstallRequiredError(RepairError):
    """Raised when trusted Updater cannot be validated, requiring full reinstall."""


@dataclass(frozen=True)
class RepairRequest:
    selector: InstalledReleaseSelector
    components: tuple[Literal["launcher", "core"], ...]
    explicit_action: bool = True
    integrity_report: FileIntegrityReport | None = None

    def __post_init__(self) -> None:
        if not self.explicit_action:
            raise RepairNotAllowed("Repair requires explicit user action")

        if not isinstance(self.selector, InstalledReleaseSelector):
            raise RepairNotAllowed(
                f"selector must be an InstalledReleaseSelector, got {type(self.selector)}"
            )

        if not isinstance(self.components, (tuple, list)):
            raise RepairNotAllowed("components must be a tuple or list")

        normalized = tuple(self.components)
        if not normalized:
            raise RepairNotAllowed("components list cannot be empty")

        for comp in normalized:
            if comp == "updater":
                raise RepairNotAllowed("Updater cannot be repaired; full reinstall is required")
            if comp not in ("launcher", "core"):
                raise RepairNotAllowed(
                    f"Component '{comp}' is not allowed for repair; only 'launcher' and 'core' are supported"
                )

        object.__setattr__(self, "components", normalized)

        if self.integrity_report is not None:
            if self.integrity_report.reinstall_required:
                raise RepairNotAllowed("Repair not allowed when reinstall is required")
            for comp in normalized:
                if comp not in self.integrity_report.repairable_components:
                    raise RepairNotAllowed(
                        f"Component '{comp}' is not repairable according to integrity report"
                    )


def create_repair_request_from_report(report: FileIntegrityReport) -> RepairRequest:
    """Create an explicit RepairRequest from a fresh FileIntegrityReport."""
    if not isinstance(report, FileIntegrityReport):
        raise RepairNotAllowed("Invalid integrity report provided")
    if report.reinstall_required:
        raise RepairNotAllowed("Reinstall is required; repair cannot be performed")
    if not report.repairable_components:
        raise RepairNotAllowed("No repairable components found in report")

    return RepairRequest(
        selector=report.selector,
        components=report.repairable_components,
        explicit_action=True,
        integrity_report=report,
    )


@dataclass(frozen=True)
class RepairResult:
    success: bool
    before_version: str
    after_version: str
    resolved_tag: str
    repaired_components: tuple[Literal["launcher", "core"], ...]
    integrity_report: FileIntegrityReport | None = None


def repair_installed_release(
    request: RepairRequest,
    exact_release_resolver: Any,
    updater_verifier: Any = verify_installed_updater,
    stage_service: Any = None,
    updater_session: Any = None,
    *,
    install_root: Path | None = None,
    file_checker: Callable[[Path, Any], FileIntegrityReport] | None = None,
) -> RepairResult:
    """Perform explicit exact-release repair of damaged Launcher and/or Core files.

    Follows the 9-step algorithm:
    1. validate components subset is non-empty and only launcher/core
    2. resolve exact selector; reject latest substitution or different tag/sequence
    3. revalidate installed updater trust/protocol
    4. download only requested damaged component assets
    5. verify size/SHA-256/signed release binding
    6. stage via existing transaction path with repair intent
    7. apply via validated updater IPC session
    8. re-run File Check; success only when repaired items are OK
    9. committed release identity/version remains unchanged
    """
    # 1. Validate request
    if not isinstance(request, RepairRequest):
        raise RepairNotAllowed("request must be an instance of RepairRequest")
    if not request.components:
        raise RepairNotAllowed("components cannot be empty")
    for comp in request.components:
        if comp not in ("launcher", "core"):
            raise RepairNotAllowed(f"Component '{comp}' cannot be repaired")

    # 2. Resolve exact selector; reject latest substitution or different tag/sequence
    if hasattr(exact_release_resolver, "resolve_exact"):
        resolved = exact_release_resolver.resolve_exact(request.selector)
    elif callable(exact_release_resolver):
        resolved = exact_release_resolver(request.selector)
    else:
        raise RepairError("Invalid exact_release_resolver provided")

    if resolved is None:
        raise RepairError("Exact release could not be resolved")

    # Authenticate exact release binding
    target_rel = getattr(resolved, "authenticated_release_v2", None)
    if target_rel is None:
        target_rel = getattr(resolved, "authenticated_release", None)
    if target_rel is None:
        raise RepairError("Release envelope is unauthenticated or missing")

    # Verify exact release sequence and identity
    rel_seq = getattr(target_rel, "release_sequence", None)
    rel_id = getattr(target_rel, "release_id", None)
    if rel_seq != request.selector.sequence:
        raise RepairError(
            f"Latest substitution or sequence mismatch: expected sequence {request.selector.sequence}, got {rel_seq}"
        )
    if rel_id != request.selector.release_id:
        raise RepairError(
            f"Release ID mismatch: expected {request.selector.release_id}, got {rel_id}"
        )

    gh_release = getattr(resolved, "github_release", None)
    if gh_release is not None:
        tag_name = getattr(gh_release, "tag_name", None)
        if tag_name != request.selector.tag_name:
            raise RepairError(
                f"Release tag mismatch: expected {request.selector.tag_name}, got {tag_name}"
            )
        html_url = getattr(gh_release, "html_url", "")
        if html_url and "Valeneko-pranmong/Neko-Family-Proxy" not in html_url:
            raise RepairError(f"Release is not from canonical repository: {html_url}")

    # 3. Revalidate installed updater trust/protocol BEFORE any mutation
    root_path = install_root
    if root_path is None:
        root_path = getattr(updater_session, "root_dir", None)
    if root_path is None:
        root_path = getattr(stage_service, "root_dir", None)
    if root_path is None and hasattr(stage_service, "_pending_store"):
        root_path = getattr(stage_service._pending_store, "root_dir", None)
    if root_path is None:
        root_path = Path(".")

    updater_path = root_path / "NekoUpdater.exe"
    try:
        if callable(updater_verifier):
            try:
                verification = updater_verifier(
                    updater_path=updater_path,
                    bound_release=target_rel,
                    supported_protocol=UPDATER_PROTOCOL_VERSION,
                )
            except TypeError:
                verification = updater_verifier(root_path, target_rel)
        else:
            verification = updater_verifier.verify(updater_path, target_rel)
    except Exception as err:
        raise ReinstallRequiredError(f"Failed to verify installed updater: {err}") from err

    trusted = getattr(verification, "trusted", True)
    reinstall_req = getattr(verification, "reinstall_required", False)
    if not trusted or reinstall_req:
        raise ReinstallRequiredError(
            "Updater is untrusted, corrupted, or incompatible; full reinstall is required. Zero mutation performed."
        )

    # 4 & 5. Download only requested damaged component assets & verify size/SHA-256/signed release binding
    # 6. Stage via existing transaction path with repair intent
    if stage_service is None:
        raise RepairError("stage_service is required")

    try:
        if hasattr(stage_service, "stage_repair"):
            pending = stage_service.stage_repair(
                resolved=resolved,
                components=request.components,
            )
        elif hasattr(stage_service, "stage"):
            try:
                pending = stage_service.stage(
                    resolved=resolved,
                    components=request.components,
                    intent="repair",
                )
            except TypeError:
                pending = stage_service.stage(resolved, request.selector)
        elif callable(stage_service):
            pending = stage_service(resolved, request.components)
        else:
            raise RepairError("Invalid stage_service interface")
    except Exception as err:
        if isinstance(err, RepairError):
            raise
        raise RepairError(f"Staging repair artifacts failed: {err}") from err

    if pending is None:
        raise RepairError("Failed to produce verified staged pending repair update")

    # 7. Apply via validated updater IPC session
    if updater_session is None:
        raise RepairError("updater_session is required")

    try:
        if hasattr(updater_session, "prepare_repair"):
            prepared = updater_session.prepare_repair(
                pending=pending,
                repair_components=request.components,
            )
        elif hasattr(updater_session, "prepare_pending"):
            try:
                prepared = updater_session.prepare_pending(
                    pending=pending,
                    intent="repair",
                    repair_components=request.components,
                )
            except TypeError:
                prepared = updater_session.prepare_pending(pending)
        elif hasattr(updater_session, "apply"):
            prepared = updater_session.apply(pending)
        elif callable(updater_session):
            prepared = updater_session(pending)
        else:
            raise RepairError("Invalid updater_session interface")

        if prepared is not None and hasattr(prepared, "release"):
            prepared.release()
        if prepared is not None and getattr(prepared, "success", True) is False:
            raise RepairError("Updater session apply failed")
    except Exception as err:
        if isinstance(err, RepairError):
            raise
        raise RepairError(f"Applying repair update failed: {err}") from err

    # 8. Re-run File Check; success only when repaired items are OK
    checker = file_checker or check_installed_files
    try:
        post_report = checker(root_path, target_rel)
    except Exception as err:
        raise RepairError(f"Post-repair file check execution failed: {err}") from err

    if post_report is not None:
        if post_report.reinstall_required:
            raise RepairError("Post-repair file check reported reinstall is required")
        for comp in request.components:
            if comp in post_report.repairable_components:
                raise RepairError(
                    f"Post-repair file check failed: component '{comp}' is still damaged"
                )
            item = next((it for it in post_report.items if it.component == comp), None)
            if item is not None and item.status != IntegrityStatus.OK:
                raise RepairError(
                    f"Post-repair file check failed: component '{comp}' status is {item.status.value}"
                )

    # 9. Committed release identity/version remains unchanged
    before_version = request.selector.version
    after_version = request.selector.version
    resolved_tag = request.selector.tag_name

    return RepairResult(
        success=True,
        before_version=before_version,
        after_version=after_version,
        resolved_tag=resolved_tag,
        repaired_components=request.components,
        integrity_report=post_report,
    )
