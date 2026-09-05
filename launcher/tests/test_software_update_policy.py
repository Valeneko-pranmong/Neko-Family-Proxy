from __future__ import annotations

from dataclasses import replace

import pytest

from neko_launcher.application.software_update_models import (
    ComponentRelease,
    LocalReleaseIdentity,
    ReleaseSet,
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)

H_A = "a" * 64
H_B = "b" * 64
H_C = "c" * 64
H_D = "d" * 64
H_E = "e" * 64
H_F = "f" * 64
H_0 = "0" * 64
H_1 = "1" * 64
H_2 = "2" * 64
H_3 = "3" * 64
H_4 = "4" * 64
H_5 = "5" * 64

LAUNCHER_SIZE = 10_000_000
CORE_SIZE = 100_000_000


def component(
    name: str,
    *,
    version: str,
    artifact_id: str,
    artifact_sha256: str,
    artifact_size: int,
    installed_identity_sha256: str,
) -> ComponentRelease:
    return ComponentRelease(
        name=name,
        version=version,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha256,
        artifact_size=artifact_size,
        installed_identity_sha256=installed_identity_sha256,
    )


def release_set(
    sequence: int,
    *,
    release_id: str | None = None,
    mandatory: bool = False,
    minimum_supported_sequence: int = 1,
    launcher_identity: str = H_A,
    core_identity: str = H_B,
    launcher_version: str = "5.1.0",
    core_version: str = "1.2.0",
    launcher_artifact_id: str = "launcher-5.1.0",
    core_artifact_id: str = "core-1.2.0",
    launcher_artifact_sha256: str = H_C,
    core_artifact_sha256: str = H_D,
    launcher_artifact_size: int = LAUNCHER_SIZE,
    core_artifact_size: int = CORE_SIZE,
    core_first: bool = False,
) -> ReleaseSet:
    launcher = component(
        "launcher",
        version=launcher_version,
        artifact_id=launcher_artifact_id,
        artifact_sha256=launcher_artifact_sha256,
        artifact_size=launcher_artifact_size,
        installed_identity_sha256=launcher_identity,
    )
    core = component(
        "core",
        version=core_version,
        artifact_id=core_artifact_id,
        artifact_sha256=core_artifact_sha256,
        artifact_size=core_artifact_size,
        installed_identity_sha256=core_identity,
    )
    components = (core, launcher) if core_first else (launcher, core)
    return ReleaseSet(
        schema_version=1,
        channel="beta",
        release_sequence=sequence,
        release_id=release_id or f"beta-{sequence}",
        mandatory=mandatory,
        minimum_supported_sequence=minimum_supported_sequence,
        components=components,
    )


def local_identity(
    sequence: int = 10,
    *,
    release_id: str | None = None,
    launcher_identity: str = H_A,
    core_identity: str = H_B,
    launcher_version: str = "5.0.0",
    core_version: str = "1.1.0",
) -> LocalReleaseIdentity:
    if sequence == 0:
        effective_release_id = "dev-unpublished"
    else:
        effective_release_id = release_id or f"beta-{sequence}"

    return LocalReleaseIdentity(
        release_sequence=sequence,
        release_id=effective_release_id,
        launcher_version=launcher_version,
        launcher_installed_identity_sha256=launcher_identity,
        core_version=core_version,
        core_installed_identity_sha256=core_identity,
    )


def execute(
    local: LocalReleaseIdentity,
    remote: ReleaseSet,
    reason: UpdateInvocationReason = UpdateInvocationReason.STARTUP,
) -> UpdateCheckResult:
    from neko_launcher.application.software_update_policy import evaluate_release

    return evaluate_release(local, remote, reason)


@pytest.mark.parametrize(
    (
        "local_sequence",
        "remote_sequence",
        "remote_mandatory",
        "minimum_supported_sequence",
        "expected_state",
        "expected_diagnostic",
    ),
    [
        (
            10,
            9,
            True,
            9,
            UpdateState.VERIFY_FAILED,
            UpdateDiagnosticCode.DOWNGRADE_REJECTED,
        ),
        (10, 10, False, 1, UpdateState.LATEST, None),
        (10, 11, False, 1, UpdateState.AVAILABLE, None),
        (10, 11, True, 1, UpdateState.MANDATORY, None),
        (10, 11, False, 11, UpdateState.MANDATORY, None),
    ],
)
def test_decision_table(
    local_sequence: int,
    remote_sequence: int,
    remote_mandatory: bool,
    minimum_supported_sequence: int,
    expected_state: UpdateState,
    expected_diagnostic: UpdateDiagnosticCode | None,
) -> None:
    local = local_identity(local_sequence)
    remote = release_set(
        remote_sequence,
        mandatory=remote_mandatory,
        minimum_supported_sequence=minimum_supported_sequence,
    )

    result = execute(local, remote)

    assert result.state is expected_state
    assert result.diagnostic_code is expected_diagnostic
    assert result.mandatory is (expected_state is UpdateState.MANDATORY)


@pytest.mark.parametrize(
    "reason",
    [UpdateInvocationReason.STARTUP, UpdateInvocationReason.MANUAL],
)
def test_preserves_invocation_reason(reason: UpdateInvocationReason) -> None:
    result = execute(local_identity(), release_set(11), reason)

    assert result.invocation_reason is reason


def test_downgrade_rejects_remote_even_when_metadata_differs() -> None:
    remote = release_set(
        9,
        release_id="beta-9-repacked",
        mandatory=True,
        minimum_supported_sequence=9,
        launcher_identity=H_C,
        core_identity=H_D,
        launcher_version="4.9.9",
        core_version="1.0.9",
        launcher_artifact_id="launcher-4.9.9-repacked",
        core_artifact_id="core-1.0.9-repacked",
        launcher_artifact_sha256=H_E,
        core_artifact_sha256=H_F,
        launcher_artifact_size=LAUNCHER_SIZE + 1,
        core_artifact_size=CORE_SIZE + 1,
    )

    result = execute(local_identity(), remote)

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.DOWNGRADE_REJECTED
    assert result.changed_components == ()
    assert result.mandatory is False


def test_same_sequence_ignores_artifact_metadata_when_identities_match_by_name() -> None:
    remote = release_set(
        10,
        release_id="beta-10-repacked",
        mandatory=True,
        minimum_supported_sequence=10,
        launcher_version="5.0.0-metadata2",
        core_version="1.1.0-metadata2",
        launcher_artifact_id="launcher-5.0.0-metadata2",
        core_artifact_id="core-1.1.0-metadata2",
        launcher_artifact_sha256=H_E,
        core_artifact_sha256=H_F,
        launcher_artifact_size=LAUNCHER_SIZE + 7,
        core_artifact_size=CORE_SIZE + 11,
        core_first=True,
    )

    result = execute(local_identity(), remote)

    assert result.state is UpdateState.LATEST
    assert result.changed_components == ()
    assert result.mandatory is False
    assert result.diagnostic_code is None


@pytest.mark.parametrize(
    ("launcher_identity", "core_identity"),
    [(H_C, H_B), (H_A, H_D), (H_C, H_D)],
    ids=["launcher", "core", "both"],
)
def test_same_sequence_identity_conflict_matrix(
    launcher_identity: str,
    core_identity: str,
) -> None:
    remote = release_set(
        10,
        launcher_identity=launcher_identity,
        core_identity=core_identity,
    )

    result = execute(local_identity(), remote)

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT
    assert result.changed_components == ()
    assert result.mandatory is False


@pytest.mark.parametrize(
    ("launcher_identity", "core_identity", "expected_changed"),
    [
        (H_A, H_B, ()),
        (H_C, H_B, ("launcher",)),
        (H_A, H_D, ("core",)),
        (H_C, H_D, ("launcher", "core")),
    ],
    ids=["none", "launcher", "core", "both"],
)
def test_forward_changed_components_depend_only_on_installed_identity(
    launcher_identity: str,
    core_identity: str,
    expected_changed: tuple[str, ...],
) -> None:
    remote = release_set(
        11,
        launcher_identity=launcher_identity,
        core_identity=core_identity,
        launcher_version="5.1.7",
        core_version="1.2.7",
        launcher_artifact_id="launcher-5.1.7",
        core_artifact_id="core-1.2.7",
        launcher_artifact_sha256=H_E,
        core_artifact_sha256=H_F,
        launcher_artifact_size=LAUNCHER_SIZE + 17,
        core_artifact_size=CORE_SIZE + 19,
    )

    result = execute(local_identity(), remote)

    assert result.changed_components == expected_changed


@pytest.mark.parametrize(
    (
        "remote_mandatory",
        "local_sequence",
        "minimum_supported_sequence",
        "expected_state",
    ),
    [
        (False, 10, 1, UpdateState.AVAILABLE),
        (True, 10, 1, UpdateState.MANDATORY),
        (False, 10, 11, UpdateState.MANDATORY),
        (True, 10, 11, UpdateState.MANDATORY),
    ],
)
def test_forward_mandatory_precedence(
    remote_mandatory: bool,
    local_sequence: int,
    minimum_supported_sequence: int,
    expected_state: UpdateState,
) -> None:
    result = execute(
        local_identity(local_sequence),
        release_set(
            11,
            mandatory=remote_mandatory,
            minimum_supported_sequence=minimum_supported_sequence,
        ),
    )

    assert result.state is expected_state
    assert result.mandatory is (expected_state is UpdateState.MANDATORY)
    assert result.diagnostic_code is None


@pytest.mark.parametrize(
    ("remote", "expected_state", "expected_diagnostic"),
    [
        (
            release_set(9, mandatory=True, minimum_supported_sequence=9),
            UpdateState.VERIFY_FAILED,
            UpdateDiagnosticCode.DOWNGRADE_REJECTED,
        ),
        (
            release_set(10, launcher_identity=H_C),
            UpdateState.VERIFY_FAILED,
            UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT,
        ),
        (release_set(10), UpdateState.LATEST, None),
        (release_set(11), UpdateState.AVAILABLE, None),
        (
            release_set(11, mandatory=True),
            UpdateState.MANDATORY,
            None,
        ),
    ],
)
def test_effective_mandatory_and_diagnostic_are_consistent(
    remote: ReleaseSet,
    expected_state: UpdateState,
    expected_diagnostic: UpdateDiagnosticCode | None,
) -> None:
    result = execute(local_identity(), remote)

    assert result.state is expected_state
    assert result.mandatory is (expected_state is UpdateState.MANDATORY)
    assert result.diagnostic_code is expected_diagnostic


@pytest.mark.parametrize(
    "remote",
    [
        release_set(9, release_id="beta-9-info", minimum_supported_sequence=9),
        release_set(10, release_id="beta-10-info", launcher_identity=H_C),
        release_set(10, release_id="beta-10-info"),
        release_set(11, release_id="beta-11-info"),
        release_set(11, release_id="beta-11-required", mandatory=True),
    ],
)
def test_result_uses_remote_release_and_version_metadata_on_every_state(
    remote: ReleaseSet,
) -> None:
    by_name = {item.name: item for item in remote.components}

    result = execute(local_identity(), remote)

    assert isinstance(result, UpdateCheckResult)
    assert result.release_id == remote.release_id
    assert result.release_sequence == remote.release_sequence
    assert result.launcher_version == by_name["launcher"].version
    assert result.core_version == by_name["core"].version
    assert isinstance(result.changed_components, tuple)


def test_dev_unpublished_bootstrap_is_mandatory_and_computes_changes() -> None:
    local = local_identity(
        0,
        launcher_identity=H_A,
        core_identity=H_B,
        launcher_version="0.0.0-dev",
        core_version="0.0.0-dev",
    )
    remote = release_set(
        1,
        release_id="beta-1",
        minimum_supported_sequence=1,
        launcher_identity=H_A,
        core_identity=H_C,
    )

    result = execute(local, remote)

    assert result.state is UpdateState.MANDATORY
    assert result.mandatory is True
    assert result.changed_components == ("core",)
    assert result.diagnostic_code is None


def test_core_first_remote_still_returns_launcher_core_changed_order() -> None:
    remote = release_set(
        11,
        launcher_identity=H_C,
        core_identity=H_D,
        core_first=True,
    )

    result = execute(local_identity(), remote)

    assert result.changed_components == ("launcher", "core")
    assert result.launcher_version == "5.1.0"
    assert result.core_version == "1.2.0"


def test_policy_does_not_mutate_inputs() -> None:
    local = local_identity()
    remote = release_set(
        11,
        launcher_identity=H_C,
        core_identity=H_D,
        core_first=True,
    )
    original_local = replace(local)
    original_remote = replace(remote, components=tuple(remote.components))

    execute(local, remote, UpdateInvocationReason.MANUAL)

    assert local == original_local
    assert remote == original_remote
    assert remote.components == original_remote.components


@pytest.mark.parametrize(
    ("remote", "expected_code"),
    [
        (
            release_set(
                9,
                release_id="beta-9-secret-check",
                minimum_supported_sequence=9,
                launcher_identity=H_C,
                core_identity=H_D,
                launcher_artifact_id="launcher-secret-artifact",
                core_artifact_id="core-secret-artifact",
                launcher_artifact_sha256=H_E,
                core_artifact_sha256=H_F,
            ),
            UpdateDiagnosticCode.DOWNGRADE_REJECTED,
        ),
        (
            release_set(
                10,
                release_id="beta-10-secret-check",
                launcher_identity=H_C,
                core_identity=H_D,
                launcher_artifact_id="launcher-conflict-artifact",
                core_artifact_id="core-conflict-artifact",
                launcher_artifact_sha256=H_E,
                core_artifact_sha256=H_F,
            ),
            UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT,
        ),
    ],
    ids=["downgrade", "same-sequence-conflict"],
)
def test_failure_diagnostics_do_not_expose_component_secrets(
    remote: ReleaseSet,
    expected_code: UpdateDiagnosticCode,
) -> None:
    local = local_identity()
    result = execute(local, remote)
    diagnostic_text = str(result.diagnostic_code)

    assert result.diagnostic_code is expected_code
    assert diagnostic_text == str(expected_code)
    assert diagnostic_text

    sensitive_values = {
        local.launcher_installed_identity_sha256,
        local.core_installed_identity_sha256,
    }
    for item in remote.components:
        sensitive_values.update(
            {
                item.installed_identity_sha256,
                item.artifact_id,
                item.artifact_sha256,
            }
        )

    for sensitive_value in sensitive_values:
        assert sensitive_value not in diagnostic_text
