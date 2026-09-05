from neko_launcher.application.software_update_models import (
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

    if remote.release_sequence < local.release_sequence:
        return UpdateCheckResult(
            state=UpdateState.VERIFY_FAILED,
            changed_components=(),
            mandatory=False,
            diagnostic_code=UpdateDiagnosticCode.DOWNGRADE_REJECTED,
            **common,
        )

    launcher_changed = (
        launcher.installed_identity_sha256
        != local.launcher_installed_identity_sha256
    )
    core_changed = (
        core.installed_identity_sha256 != local.core_installed_identity_sha256
    )

    if remote.release_sequence == local.release_sequence:
        if launcher_changed or core_changed:
            return UpdateCheckResult(
                state=UpdateState.VERIFY_FAILED,
                changed_components=(),
                mandatory=False,
                diagnostic_code=(
                    UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT
                ),
                **common,
            )
        return UpdateCheckResult(
            state=UpdateState.LATEST,
            changed_components=(),
            mandatory=False,
            diagnostic_code=None,
            **common,
        )

    changed_components = tuple(
        name
        for name, changed in (
            ("launcher", launcher_changed),
            ("core", core_changed),
        )
        if changed
    )
    mandatory = (
        remote.mandatory
        or local.release_sequence < remote.minimum_supported_sequence
    )

    return UpdateCheckResult(
        state=UpdateState.MANDATORY if mandatory else UpdateState.AVAILABLE,
        changed_components=changed_components,
        mandatory=mandatory,
        diagnostic_code=None,
        **common,
    )
