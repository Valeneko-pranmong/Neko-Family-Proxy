from enum import Enum
from typing import Any

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    ComponentRelease,
    LocalReleaseIdentity,
    ReleaseSet,
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)


class StartupUpdateDisposition(str, Enum):
    CURRENT = "current"
    MANDATORY_UPDATE = "mandatory_update"
    REINSTALL_REQUIRED = "reinstall_required"


class SoftwareUpdatePolicyError(ValueError):
    """Raised when release classification encounters an invalid or conflicting release."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(detail or code)


def _extract_remote_version(remote: Any) -> str:
    if hasattr(remote, "version") and isinstance(remote.version, str):
        return remote.version
    if hasattr(remote, "launcher_version") and isinstance(remote.launcher_version, str):
        return remote.launcher_version
    if hasattr(remote, "authenticated_release_v2") and remote.authenticated_release_v2 is not None:
        return _extract_remote_version(remote.authenticated_release_v2)
    if hasattr(remote, "authenticated_release") and remote.authenticated_release is not None:
        return _extract_remote_version(remote.authenticated_release)
    if hasattr(remote, "components"):
        comps = remote.components
        if isinstance(comps, dict) and "launcher" in comps:
            launcher = comps["launcher"]
            if hasattr(launcher, "version"):
                return launcher.version
        if isinstance(comps, (list, tuple)):
            for comp in comps:
                if getattr(comp, "name", None) == "launcher" and hasattr(comp, "version"):
                    return comp.version
    raise SoftwareUpdatePolicyError("INVALID_REMOTE", "Cannot determine component version from remote release")


def _is_updater_protocol_compatible(remote: Any, supported_protocol: int = 1) -> bool:
    if hasattr(remote, "authenticated_release_v2") and remote.authenticated_release_v2 is not None:
        return _is_updater_protocol_compatible(remote.authenticated_release_v2, supported_protocol)
    proto = getattr(remote, "updater_protocol", None)
    if proto is None:
        return True
    if isinstance(proto, int):
        return proto == supported_protocol
    if hasattr(proto, "minimum") and hasattr(proto, "maximum"):
        return proto.minimum <= supported_protocol <= proto.maximum
    if isinstance(proto, (list, tuple)) and len(proto) == 2:
        return proto[0] <= supported_protocol <= proto[1]
    return False


def classify_startup_release(
    local: LocalReleaseIdentity,
    remote: Any,
) -> StartupUpdateDisposition:
    if not isinstance(local, LocalReleaseIdentity):
        raise TypeError(
            f"Production policy requires LocalReleaseIdentity, got {type(local).__name__}"
        )
    if remote is None:
        raise SoftwareUpdatePolicyError("INVALID_REMOTE", "Remote release cannot be None")

    target = remote
    if hasattr(target, "authenticated_release_v2") and target.authenticated_release_v2 is not None:
        target = target.authenticated_release_v2
    elif hasattr(target, "authenticated_release") and target.authenticated_release is not None:
        target = target.authenticated_release

    remote_seq = getattr(target, "release_sequence", getattr(target, "sequence", None))
    if not isinstance(remote_seq, int) or isinstance(remote_seq, bool):
        raise SoftwareUpdatePolicyError("INVALID_REMOTE", "Remote release missing valid release_sequence")

    remote_id = getattr(target, "release_id", None)
    if not isinstance(remote_id, str) or not remote_id.strip():
        raise SoftwareUpdatePolicyError("INVALID_REMOTE", "Remote release missing valid release_id")

    remote_sha = getattr(target, "payload_sha256", None)

    remote_version = _extract_remote_version(remote)
    try:
        remote_major = int(remote_version.strip().lstrip("v").split(".")[0])
    except (ValueError, IndexError):
        raise SoftwareUpdatePolicyError("INVALID_VERSION", f"Invalid semantic version: {remote_version!r}")

    local_version = local.launcher_version
    try:
        local_major = int(local_version.strip().lstrip("v").split(".")[0])
    except (ValueError, IndexError):
        local_major = 5

    # Check rollback / downgrade against high_water
    if remote_seq < local.high_water.release_sequence:
        raise SoftwareUpdatePolicyError(
            UpdateDiagnosticCode.DOWNGRADE_REJECTED.value,
            f"Remote sequence {remote_seq} is lower than high water {local.high_water.release_sequence}",
        )

    # Check same sequence conflict against high_water
    if remote_seq == local.high_water.release_sequence:
        if remote_id != local.high_water.release_id:
            raise SoftwareUpdatePolicyError(
                UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT.value,
                f"Remote release_id {remote_id!r} conflicts with high water {local.high_water.release_id!r}",
            )
        if remote_sha is not None and remote_sha != local.high_water.payload_sha256:
            raise SoftwareUpdatePolicyError(
                UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT.value,
                "Remote payload_sha256 conflicts with high water",
            )

    # Check exact match against committed
    if remote_seq == local.committed.release_sequence:
        if remote_id != local.committed.release_id:
            raise SoftwareUpdatePolicyError(
                UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT.value,
                f"Remote release_id {remote_id!r} conflicts with committed {local.committed.release_id!r}",
            )
        if remote_sha is not None and remote_sha != local.committed.payload_sha256:
            raise SoftwareUpdatePolicyError(
                UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT.value,
                "Remote payload_sha256 conflicts with committed",
            )
        return StartupUpdateDisposition.CURRENT

    # Remote is newer (remote_seq > local.committed.release_sequence)
    # Check updater protocol compatibility
    if not _is_updater_protocol_compatible(remote):
        return StartupUpdateDisposition.REINSTALL_REQUIRED

    # Check major boundary
    if remote_major >= 6 or remote_major != local_major:
        return StartupUpdateDisposition.REINSTALL_REQUIRED

    return StartupUpdateDisposition.MANDATORY_UPDATE


def evaluate_release(
    local: LocalReleaseIdentity,
    remote: ReleaseSet,
    reason: UpdateInvocationReason,
) -> UpdateCheckResult:
    if not isinstance(local, LocalReleaseIdentity):
        raise TypeError(
            f"Production policy requires LocalReleaseIdentity, got {type(local).__name__}"
        )

    components: dict[str, ComponentRelease] = {
        component.name: component for component in remote.components
    }
    launcher = components["launcher"]
    core = components["core"]

    common = {
        "invocation_reason": reason,
        "release_id": remote.release_id,
        "release_sequence": remote.release_sequence,
        "launcher_version": launcher.version,
        "core_version": core.version,
    }

    launcher_changed = (
        launcher.installed_identity_sha256
        != local.launcher_installed_identity_sha256
    )
    core_changed = (
        core.installed_identity_sha256 != local.core_installed_identity_sha256
    )
    changed_components = tuple(
        name
        for name, changed in (
            ("launcher", launcher_changed),
            ("core", core_changed),
        )
        if changed
    )

    remote_binding = AuthenticatedReleaseBinding(
        release_sequence=remote.release_sequence,
        release_id=remote.release_id,
        payload_sha256=remote.payload_sha256,
    )

    mandatory = (
        remote.mandatory
        or local.committed.release_sequence < remote.minimum_supported_sequence
    )

    if remote.release_sequence < local.high_water.release_sequence:
        return UpdateCheckResult(
            state=UpdateState.VERIFY_FAILED,
            changed_components=(),
            mandatory=False,
            diagnostic_code=UpdateDiagnosticCode.DOWNGRADE_REJECTED,
            retry_staging=False,
            **common,
        )

    if remote.release_sequence == local.high_water.release_sequence:
        if remote_binding != local.high_water:
            return UpdateCheckResult(
                state=UpdateState.VERIFY_FAILED,
                changed_components=(),
                mandatory=False,
                diagnostic_code=(
                    UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT
                ),
                retry_staging=False,
                **common,
            )

        if remote_binding == local.committed:
            return UpdateCheckResult(
                state=UpdateState.LATEST,
                changed_components=(),
                mandatory=False,
                diagnostic_code=None,
                retry_staging=False,
                **common,
            )

        if local.failed is not None and remote_binding == local.failed:
            return UpdateCheckResult(
                state=UpdateState.LATEST,
                changed_components=(),
                mandatory=False,
                diagnostic_code=None,
                retry_staging=False,
                **common,
            )

        return UpdateCheckResult(
            state=UpdateState.LATEST,
            changed_components=changed_components,
            mandatory=mandatory,
            diagnostic_code=None,
            retry_staging=True,
            **common,
        )

    return UpdateCheckResult(
        state=UpdateState.MANDATORY if mandatory else UpdateState.AVAILABLE,
        changed_components=changed_components,
        mandatory=mandatory,
        diagnostic_code=None,
        retry_staging=False,
        **common,
    )


def can_apply_update(is_proxy_active: bool) -> tuple[bool, str | None]:
    """Evaluate whether an update can be applied given current proxy session activity."""
    if is_proxy_active:
        return False, "BUSY_SESSION"
    return True, None

