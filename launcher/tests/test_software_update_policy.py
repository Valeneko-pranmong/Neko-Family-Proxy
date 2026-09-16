from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    ComponentRelease,
    DevelopmentReleaseIdentity,
    LocalReleaseIdentity,
    ReleaseSet,
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.application.software_update_policy import (
    SoftwareUpdatePolicyError,
    StartupUpdateDisposition,
    classify_startup_release,
    evaluate_release,
)
from neko_launcher.updater.manifest_v2 import UpdaterProtocol

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
    payload_sha256: str | None = None,
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
    effective_release_id = release_id or f"beta-{sequence}"
    if payload_sha256 is None:
        if (
            launcher_identity == H_A
            and core_identity == H_B
            and effective_release_id == f"beta-{sequence}"
        ):
            effective_payload_sha = f"{sequence:04x}".ljust(64, "0")
        else:
            effective_payload_sha = hashlib.sha256(
                f"{sequence}:{effective_release_id}:{launcher_identity}:{core_identity}".encode()
            ).hexdigest()
    else:
        effective_payload_sha = payload_sha256

    try:
        return ReleaseSet(
            schema_version=1,
            channel="beta",
            release_sequence=sequence,
            release_id=effective_release_id,
            mandatory=mandatory,
            minimum_supported_sequence=minimum_supported_sequence,
            components=components,
            payload_sha256=effective_payload_sha,
        )
    except TypeError:
        # Before ReleaseSet gains payload_sha256 in RED phase
        return ReleaseSet(
            schema_version=1,
            channel="beta",
            release_sequence=sequence,
            release_id=effective_release_id,
            mandatory=mandatory,
            minimum_supported_sequence=minimum_supported_sequence,
            components=components,
        )


def bind(
    seq: int,
    release_id: str | None = None,
    payload_sha: str | None = None,
) -> AuthenticatedReleaseBinding:
    effective_id = release_id or f"beta-{seq}"
    effective_sha = payload_sha or f"{seq:04x}".ljust(64, "0")
    return AuthenticatedReleaseBinding(
        release_sequence=seq,
        release_id=effective_id,
        payload_sha256=effective_sha,
    )


def local_with(
    committed: AuthenticatedReleaseBinding,
    high_water: AuthenticatedReleaseBinding,
    observed: AuthenticatedReleaseBinding,
    failed: AuthenticatedReleaseBinding | None = None,
    launcher_identity: str = H_A,
    core_identity: str = H_B,
    updater_identity: str = H_C,
    launcher_version: str = "5.0.0",
    core_version: str = "1.1.0",
    updater_version: str = "5.0.0",
) -> LocalReleaseIdentity:
    return LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=observed,
        failed=failed,
        launcher_version=launcher_version,
        launcher_installed_identity_sha256=launcher_identity,
        updater_version=updater_version,
        updater_installed_identity_sha256=updater_identity,
        core_version=core_version,
        core_installed_identity_sha256=core_identity,
    )


def release_for(
    binding: AuthenticatedReleaseBinding,
    *,
    mandatory: bool = False,
    minimum_supported_sequence: int = 1,
    launcher_identity: str = H_C,
    core_identity: str = H_D,
    launcher_version: str = "5.1.0",
    core_version: str = "1.2.0",
) -> ReleaseSet:
    return release_set(
        binding.release_sequence,
        release_id=binding.release_id,
        payload_sha256=binding.payload_sha256,
        mandatory=mandatory,
        minimum_supported_sequence=minimum_supported_sequence,
        launcher_identity=launcher_identity,
        core_identity=core_identity,
        launcher_version=launcher_version,
        core_version=core_version,
    )


def local_identity(
    sequence: int = 10,
    *,
    release_id: str | None = None,
    launcher_identity: str = H_A,
    core_identity: str = H_B,
    updater_identity: str = H_C,
    launcher_version: str = "5.0.0",
    core_version: str = "1.1.0",
    updater_version: str = "5.0.0",
    committed: AuthenticatedReleaseBinding | None = None,
    high_water: AuthenticatedReleaseBinding | None = None,
    observed: AuthenticatedReleaseBinding | None = None,
    failed: AuthenticatedReleaseBinding | None = None,
) -> LocalReleaseIdentity:
    if sequence == 0 and committed is None:
        raise ValueError("Authenticated LocalReleaseIdentity rejects sequence 0")

    if committed is None:
        effective_release_id = release_id or f"beta-{sequence}"
        payload_sha = f"{sequence:04x}".ljust(64, "0")
        committed = AuthenticatedReleaseBinding(
            release_sequence=sequence,
            release_id=effective_release_id,
            payload_sha256=payload_sha,
        )
    if high_water is None:
        high_water = committed
    if observed is None:
        observed = high_water

    return LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=observed,
        failed=failed,
        launcher_version=launcher_version,
        launcher_installed_identity_sha256=launcher_identity,
        updater_version=updater_version,
        updater_installed_identity_sha256=updater_identity,
        core_version=core_version,
        core_installed_identity_sha256=core_identity,
    )


def execute(
    local: LocalReleaseIdentity,
    remote: ReleaseSet,
    reason: UpdateInvocationReason = UpdateInvocationReason.STARTUP,
) -> UpdateCheckResult:
    if not isinstance(local, LocalReleaseIdentity):
        raise TypeError(
            f"Production policy requires LocalReleaseIdentity, got {type(local).__name__}"
        )
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


def test_dev_unpublished_bootstrap_rejected_by_production_policy() -> None:
    with pytest.raises(ValueError):
        local_identity(
            0,
            launcher_identity=H_A,
            core_identity=H_B,
            launcher_version="0.0.0-dev",
            core_version="0.0.0-dev",
        )
    dev = DevelopmentReleaseIdentity(
        release_sequence=0,
        release_id="dev-unpublished",
        launcher_version="0.0.0-dev",
        launcher_installed_identity_sha256=H_A,
        core_version="0.0.0-dev",
        core_installed_identity_sha256=H_B,
    )
    remote = release_set(
        1,
        release_id="beta-1",
        minimum_supported_sequence=1,
        launcher_identity=H_A,
        core_identity=H_C,
    )
    with pytest.raises(TypeError, match="LocalReleaseIdentity"):
        execute(dev, remote)  # type: ignore[arg-type]


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


def test_can_apply_update_enforces_idle_session() -> None:
    from neko_launcher.application.software_update_policy import can_apply_update

    can_apply, reason = can_apply_update(is_proxy_active=True)
    assert can_apply is False
    assert reason == "BUSY_SESSION"

    can_apply, reason = can_apply_update(is_proxy_active=False)
    assert can_apply is True
    assert reason is None


def test_production_policy_fixture_rejects_sequence_zero() -> None:
    with pytest.raises(ValueError):
        local_identity(0)


def test_production_policy_fixture_rejects_development_identity() -> None:
    dev = DevelopmentReleaseIdentity(
        release_sequence=0,
        release_id="dev-unpublished",
        launcher_version="5.0.0",
        launcher_installed_identity_sha256=H_A,
        core_version="1.1.0",
        core_installed_identity_sha256=H_B,
    )
    with pytest.raises(TypeError, match="LocalReleaseIdentity"):
        execute(dev, release_set(11))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("remote_seq", "mandatory_flag", "minimum", "expected_state"),
    [
        (9, False, 8, UpdateState.AVAILABLE),
        (9, True, 8, UpdateState.MANDATORY),
        (9, False, 9, UpdateState.MANDATORY),
    ],
)
def test_newer_release_uses_committed_sequence_for_mandatory(
    remote_seq: int,
    mandatory_flag: bool,
    minimum: int,
    expected_state: UpdateState,
) -> None:
    local = local_with(committed=bind(8), high_water=bind(8), observed=bind(8))
    remote = release_for(
        bind(remote_seq),
        mandatory=mandatory_flag,
        minimum_supported_sequence=minimum,
    )
    result = evaluate_release(local, remote, UpdateInvocationReason.STARTUP)
    assert result.state == expected_state


def test_committed_exact_high_water_is_latest() -> None:
    local = local_with(committed=bind(8), high_water=bind(8), observed=bind(8))
    result = evaluate_release(local, release_for(bind(8)), UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.LATEST
    assert result.mandatory is False


def test_exact_failed_high_water_is_known_not_fresh_update() -> None:
    local = local_with(committed=bind(8), high_water=bind(9), observed=bind(9), failed=bind(9))
    result = evaluate_release(local, release_for(bind(9)), UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.LATEST
    assert result.mandatory is False
    assert result.changed_components == ()


def test_exact_observed_unfailed_high_water_is_retryable_mandatory() -> None:
    local = local_with(committed=bind(8), high_water=bind(9), observed=bind(9), failed=None)
    remote = release_for(bind(9), mandatory=True, minimum_supported_sequence=8)
    result = evaluate_release(local, remote, UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.LATEST  # no new authority
    assert result.mandatory is True
    assert result.retry_staging is True
    assert result.changed_components == ("launcher", "core")


def test_same_sequence_identity_conflict_different_release_id() -> None:
    local = local_with(committed=bind(8), high_water=bind(9), observed=bind(9))
    remote = release_for(
        bind(9, release_id="beta-9-conflict", payload_sha=f"{9:04x}".ljust(64, "0"))
    )
    result = evaluate_release(local, remote, UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.VERIFY_FAILED
    assert result.diagnostic_code == UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT


def test_same_sequence_identity_conflict_different_payload_sha() -> None:
    local = local_with(committed=bind(8), high_water=bind(9), observed=bind(9))
    remote = release_for(
        bind(9, payload_sha="f" * 64)
    )
    result = evaluate_release(local, remote, UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.VERIFY_FAILED
    assert result.diagnostic_code == UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT


def test_lower_than_high_water_rejected_even_if_above_committed() -> None:
    local = local_with(committed=bind(8), high_water=bind(10), observed=bind(10))
    remote = release_for(bind(9))
    result = evaluate_release(local, remote, UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.VERIFY_FAILED
    assert result.diagnostic_code == UpdateDiagnosticCode.DOWNGRADE_REJECTED


def test_semantic_version_does_not_affect_ordering() -> None:
    # Lower semantic version but newer sequence is accepted
    local = local_with(committed=bind(8), high_water=bind(8), observed=bind(8))
    remote_newer = release_for(bind(9), launcher_version="0.1.0", core_version="0.1.0")
    result = evaluate_release(local, remote_newer, UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.AVAILABLE

    # Higher semantic version but lower sequence is rejected
    remote_older = release_for(bind(7), launcher_version="99.9.9", core_version="99.9.9")
    result_older = evaluate_release(local, remote_older, UpdateInvocationReason.STARTUP)
    assert result_older.state == UpdateState.VERIFY_FAILED
    assert result_older.diagnostic_code == UpdateDiagnosticCode.DOWNGRADE_REJECTED

    # Same sequence different payload_sha with identical semantic version is conflict
    remote_conflict = release_for(
        bind(8, payload_sha="e" * 64),
        launcher_version="5.0.0",
        core_version="1.1.0",
    )
    result_conflict = evaluate_release(local, remote_conflict, UpdateInvocationReason.STARTUP)
    assert result_conflict.state == UpdateState.VERIFY_FAILED
    assert result_conflict.diagnostic_code == UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT


def local_release_identity(
    version: str = "5.1.2",
    sequence: int = 8,
    *,
    release_id: str | None = None,
    payload_sha: str | None = None,
    high_water_sequence: int | None = None,
    high_water_release_id: str | None = None,
    high_water_payload_sha: str | None = None,
    failed: AuthenticatedReleaseBinding | None = None,
    launcher_identity: str = H_A,
    core_identity: str = H_B,
    updater_identity: str = H_C,
    updater_version: str = "5.0.0",
    core_version: str = "1.1.0",
) -> LocalReleaseIdentity:
    eff_release_id = release_id or f"beta-{sequence}"
    eff_payload_sha = payload_sha or f"{sequence:04x}".ljust(64, "0")
    committed = AuthenticatedReleaseBinding(
        release_sequence=sequence,
        release_id=eff_release_id,
        payload_sha256=eff_payload_sha,
    )
    if high_water_sequence is not None:
        hw_id = high_water_release_id or f"beta-{high_water_sequence}"
        hw_sha = high_water_payload_sha or f"{high_water_sequence:04x}".ljust(64, "0")
        high_water = AuthenticatedReleaseBinding(
            release_sequence=high_water_sequence,
            release_id=hw_id,
            payload_sha256=hw_sha,
        )
    else:
        high_water = committed

    return LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=failed,
        launcher_version=version,
        launcher_installed_identity_sha256=launcher_identity,
        updater_version=updater_version,
        updater_installed_identity_sha256=updater_identity,
        core_version=core_version,
        core_installed_identity_sha256=core_identity,
    )


def bound_release(
    version: str = "5.1.3",
    sequence: int = 9,
    *,
    release_id: str | None = None,
    mandatory: bool = True,
    payload_sha: str | None = None,
    updater_protocol: Any = None,
    minimum_supported_sequence: int = 1,
    launcher_identity: str = H_C,
    core_identity: str = H_D,
) -> ReleaseSet:
    return release_set(
        sequence,
        release_id=release_id,
        mandatory=mandatory,
        minimum_supported_sequence=minimum_supported_sequence,
        launcher_identity=launcher_identity,
        core_identity=core_identity,
        launcher_version=version,
        core_version="1.2.0",
        payload_sha256=payload_sha,
    )


def test_startup_classification_5_1_2_to_5_1_3_is_mandatory() -> None:
    result = classify_startup_release(
        local=local_release_identity(version="5.1.2", sequence=8),
        remote=bound_release(version="5.1.3", sequence=9, mandatory=True),
    )
    assert result is StartupUpdateDisposition.MANDATORY_UPDATE


def test_startup_classification_exact_same_release_is_current() -> None:
    local = local_release_identity(version="5.1.2", sequence=8)
    remote = bound_release(
        version="5.1.2",
        sequence=8,
        release_id=local.committed.release_id,
        payload_sha=local.committed.payload_sha256,
        launcher_identity=local.launcher_installed_identity_sha256,
        core_identity=local.core_installed_identity_sha256,
    )
    result = classify_startup_release(local=local, remote=remote)
    assert result is StartupUpdateDisposition.CURRENT


def test_newer_same_major_is_mandatory_even_if_manifest_flag_false() -> None:
    result = classify_startup_release(
        local=local_release_identity(version="5.1.2", sequence=8),
        remote=bound_release(version="5.1.3", sequence=9, mandatory=False),
    )
    assert result is StartupUpdateDisposition.MANDATORY_UPDATE


def test_next_major_requires_reinstall() -> None:
    result = classify_startup_release(
        local=local_release_identity(version="5.1.3", sequence=9),
        remote=bound_release(version="6.0.0", sequence=10, mandatory=True),
    )
    assert result is StartupUpdateDisposition.REINSTALL_REQUIRED


def test_startup_classification_incompatible_updater_protocol_requires_reinstall() -> None:
    # If ReleaseSet doesn't have updater_protocol, we attach it as an attribute or pass stub
    class BoundWithProto:
        def __init__(self, base: Any, proto: Any) -> None:
            self._base = base
            self.updater_protocol = proto
            self.version = getattr(base, "launcher_version", "5.1.3")
            self.release_sequence = base.release_sequence
            self.release_id = base.release_id
            self.mandatory = base.mandatory
            self.payload_sha256 = base.payload_sha256
            self.components = base.components
            self.minimum_supported_sequence = base.minimum_supported_sequence

    stub = BoundWithProto(bound_release(version="5.1.3", sequence=9), UpdaterProtocol(minimum=2, maximum=2))
    result = classify_startup_release(
        local=local_release_identity(version="5.1.2", sequence=8),
        remote=stub,
    )
    assert result is StartupUpdateDisposition.REINSTALL_REQUIRED

    # Incompatible updater protocol across major boundary requires reinstall
    stub_major = BoundWithProto(bound_release(version="6.0.0", sequence=10), UpdaterProtocol(minimum=2, maximum=3))
    result_major = classify_startup_release(
        local=local_release_identity(version="5.1.2", sequence=8),
        remote=stub_major,
    )
    assert result_major is StartupUpdateDisposition.REINSTALL_REQUIRED


def test_startup_classification_invalid_untrusted_conflicting_remote_fails_closed() -> None:
    # Rollback / downgrade attempt
    local = local_release_identity(version="5.1.3", sequence=9)
    remote_downgrade = bound_release(version="5.1.2", sequence=8)
    with pytest.raises((SoftwareUpdatePolicyError, ValueError)):
        classify_startup_release(local=local, remote=remote_downgrade)

    # Same sequence conflict (different release_id)
    remote_conflict_id = bound_release(
        version="5.1.3",
        sequence=9,
        release_id="beta-9-conflict",
    )
    with pytest.raises((SoftwareUpdatePolicyError, ValueError)):
        classify_startup_release(local=local, remote=remote_conflict_id)

    # Same sequence conflict (different payload_sha256)
    remote_conflict_sha = bound_release(
        version="5.1.3",
        sequence=9,
        payload_sha=H_5,
    )
    with pytest.raises((SoftwareUpdatePolicyError, ValueError)):
        classify_startup_release(local=local, remote=remote_conflict_sha)

    # Invalid local identity
    with pytest.raises(TypeError, match="LocalReleaseIdentity"):
        classify_startup_release(local=None, remote=bound_release(version="5.1.3", sequence=9))  # type: ignore[arg-type]
