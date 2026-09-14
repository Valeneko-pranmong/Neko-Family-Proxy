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

