from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil

import pytest

import neko_launcher.e2e.final_windows_harness as harness_module
from neko_launcher.e2e.final_windows_harness import (
    FAILURE_MATRIX,
    ArtifactIdentityPlan,
    AuthorityLossTimeline,
    ClaimObservation,
    CleanupPlan,
    CoreOwnershipObservation,
    DisplacedObservation,
    ExecutionTopology,
    FinalExecutionGates,
    InstanceIsolation,
    InstanceId,
    PreparationAudit,
    RuntimeCatalogState,
    RuntimeConfigGateObservation,
    SafeOpaqueId,
    StageTraceObservation,
    SyntheticDataPlan,
    TransitionObservation,
    assert_secret_safe_mapping,
    default_preparation_manifest,
    admit_final_core_artifact,
    FINAL_CORE_ARTIFACT_PATH,
    FINAL_CORE_EXE_SHA256,
    FINAL_CORE_SOURCE_SHA,
    FINAL_MANIFEST_SHA256,
    FINAL_PROTECTED_PAYLOAD_SHA256,
    main,
    validate_failure_matrix,
    validate_latest_login_wins,
    validate_preparation_contract,
    validate_topology,
    write_preparation_manifest,
)


def _copy_writable_artifact(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)
    for path in destination.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode | 0o200)


def test_a_b_c_a_latest_successful_claim_wins_without_permanent_installation_lock() -> None:
    run_salt = b"final-e2e-transition-fixture"
    sessions = tuple(
        str(
            SafeOpaqueId.from_uuid(
                "sid", value, run_salt=run_salt
            )
        )
        for value in (
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000003",
            "00000000-0000-0000-0000-000000000004",
        )
    )
    installations = tuple(
        str(
            SafeOpaqueId.from_uuid(
                "iid", value, run_salt=run_salt
            )
        )
        for value in (
            "10000000-0000-0000-0000-000000000001",
            "10000000-0000-0000-0000-000000000002",
            "10000000-0000-0000-0000-000000000003",
        )
    )
    transitions = (
        TransitionObservation(
            claim=ClaimObservation(
                instance=InstanceId.INSTANCE_A,
                session_ref=sessions[0],
                installation_ref=installations[0],
                heartbeat_accepted=True,
            ),
        ),
        TransitionObservation(
            claim=ClaimObservation(
                instance=InstanceId.INSTANCE_B,
                session_ref=sessions[1],
                installation_ref=installations[1],
                heartbeat_accepted=True,
            ),
            displaced=DisplacedObservation(
                instance=InstanceId.INSTANCE_A,
                session_ref=sessions[0],
                heartbeat_accepted=False,
                future_permit_eligible=False,
            ),
        ),
        TransitionObservation(
            claim=ClaimObservation(
                instance=InstanceId.INSTANCE_C,
                session_ref=sessions[2],
                installation_ref=installations[2],
                heartbeat_accepted=True,
            ),
            displaced=DisplacedObservation(
                instance=InstanceId.INSTANCE_B,
                session_ref=sessions[1],
                heartbeat_accepted=False,
                future_permit_eligible=False,
            ),
        ),
        TransitionObservation(
            claim=ClaimObservation(
                instance=InstanceId.INSTANCE_A,
                session_ref=sessions[3],
                installation_ref=installations[0],
                heartbeat_accepted=True,
            ),
            displaced=DisplacedObservation(
                instance=InstanceId.INSTANCE_C,
                session_ref=sessions[2],
                heartbeat_accepted=False,
                future_permit_eligible=False,
            ),
        ),
    )

    result = validate_latest_login_wins(transitions)

    assert result.authoritative_instance is InstanceId.INSTANCE_A
    assert result.remembered_installation_count == 3
    assert result.returning_instance_reclaimed is True
    assert result.displaced_instances == (
        InstanceId.INSTANCE_A,
        InstanceId.INSTANCE_B,
        InstanceId.INSTANCE_C,
    )


def test_three_vm_topology_isolates_persisted_state_without_weakening_singletons() -> None:
    instances = tuple(
        InstanceIsolation(
            instance=instance,
            windows_host_ref=f"host_{instance.value[-1].lower()}",
            windows_user_ref=f"user_{instance.value[-1].lower()}",
            credential_vault_ref=f"vault_{instance.value[-1].lower()}",
            local_app_data_root=r"%LOCALAPPDATA%\NEKO FAMILY",
            debug_log_root=r"%LOCALAPPDATA%\NEKO FAMILY\logs\final-e2e",
            temporary_runtime_root=rf"%TEMP%\neko-final-e2e\{instance.value}",
            process_ownership_ledger=(
                rf"%TEMP%\neko-final-e2e\{instance.value}\owned-core.json"
            ),
        )
        for instance in InstanceId
    )
    topology = ExecutionTopology.separate_windows_vms(instances)

    validate_topology(topology)

    assert topology.production_launcher_mutex == r"Local\NekoFamilyProxyLauncher"
    assert topology.production_core_pipe == "NekoProxyCoreControl"
    assert topology.production_singletons_unchanged is True
    assert topology.description == (
        "three separate Windows VMs; one dedicated Windows user, Launcher, "
        "credential vault, and at most one production Core host per VM"
    )


def test_backend_identifiers_are_recorded_only_as_salted_opaque_references() -> None:
    raw_session_id = "47a39b21-7d47-4583-a9d6-6495395cc814"
    raw_installation_id = "1480c33b-0f3c-4a9c-b09c-7f25161ea235"

    session_ref = SafeOpaqueId.from_uuid(
        "launcher_session", raw_session_id, run_salt=b"final-e2e-run-001"
    )
    installation_ref = SafeOpaqueId.from_uuid(
        "installation", raw_installation_id, run_salt=b"final-e2e-run-001"
    )

    rendered = f"{session_ref!r} {session_ref} {installation_ref!r} {installation_ref}"
    assert raw_session_id not in rendered
    assert raw_installation_id not in rendered
    assert str(session_ref).startswith("launcher_session_")
    assert str(installation_ref).startswith("installation_")
    assert session_ref != SafeOpaqueId.from_uuid(
        "launcher_session", raw_session_id, run_salt=b"different-run"
    )


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "Authorization: Bearer secret-value",
        "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature",
        "-----BEGIN PRIVATE KEY-----",
        "47a39b21-7d47-4583-a9d6-6495395cc814",
    ],
)
def test_secret_safety_rejects_forbidden_values_under_innocent_keys(
    unsafe_value: str,
) -> None:
    with pytest.raises(ValueError, match="secret-bearing evidence value"):
        assert_secret_safe_mapping({"message": unsafe_value})


def test_authority_loss_metrics_use_ordered_utc_timestamps_and_graceful_exit() -> None:
    replaced_at = datetime(2026, 8, 11, 10, 0, 0, tzinfo=UTC)
    timeline = AuthorityLossTimeline(
        authority_replaced_at=replaced_at,
        old_launcher_detected_at=replaced_at + timedelta(seconds=2, milliseconds=125),
        shutdown_requested_at=replaced_at + timedelta(seconds=2, milliseconds=150),
        core_exited_at=replaced_at + timedelta(seconds=2, milliseconds=900),
        graceful_shutdown=True,
        emergency_fallback_used=False,
        broad_kill_used=False,
    )

    metrics = timeline.validate_and_measure()

    assert metrics.replacement_to_authority_invalidation_ms == 2_125
    assert metrics.authority_invalidation_to_core_exit_ms == 775
    assert metrics.shutdown_request_to_core_exit_ms == 750
    assert metrics.graceful_pass is True


def test_artifact_identity_requires_exact_commits_manifest_exe_and_five_dll_hashes(
    tmp_path: Path,
) -> None:
    artifacts = {
        "launcher.exe": b"launcher",
        "core-manifest.json": b"manifest",
        "NekoProxyCore.exe": b"core",
        "NekoProxyCore.dll": b"entry",
        "NekoProxyCore.Core.dll": b"core-library",
        "NekoProxyCore.Legacy.dll": b"legacy",
        "NekoProxyCore.Windows.dll": b"windows",
        "Netch.dll": b"netch",
    }
    for name, payload in artifacts.items():
        (tmp_path / name).write_bytes(payload)

    plan = ArtifactIdentityPlan.capture(
        launcher_commit="c515141e33245b9fe4182cc4244092f01b286b70",
        launcher_exe=tmp_path / "launcher.exe",
        core_commit=FINAL_CORE_SOURCE_SHA,
        core_manifest=tmp_path / "core-manifest.json",
        core_exe=tmp_path / "NekoProxyCore.exe",
        critical_core_dlls=tuple(
            tmp_path / name
            for name in (
                "NekoProxyCore.dll",
                "NekoProxyCore.Core.dll",
                "NekoProxyCore.Legacy.dll",
                "NekoProxyCore.Windows.dll",
                "Netch.dll",
            )
        ),
    )

    plan.validate()
    assert len(plan.critical_core_dll_sha256) == 5
    assert all(len(value) == 64 for value in plan.critical_core_dll_sha256.values())

    (tmp_path / "Netch.dll").write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact bytes changed"):
        plan.validate()


@pytest.mark.parametrize(
    "observation",
    [
        RuntimeConfigGateObservation(
            state=RuntimeCatalogState.EMPTY,
            candidate_count=0,
            error_code="RUNTIME_CONFIGURATION_UNAVAILABLE",
            validated_candidate=None,
            frozen_candidate=None,
            permit_calls=0,
        ),
        RuntimeConfigGateObservation(
            state=RuntimeCatalogState.UNIQUE,
            candidate_count=1,
            error_code=None,
            validated_candidate=("profile-17", "server-42"),
            frozen_candidate=("profile-17", "server-42"),
            permit_calls=1,
        ),
        RuntimeConfigGateObservation(
            state=RuntimeCatalogState.MULTIPLE,
            candidate_count=2,
            error_code="RUNTIME_CONFIGURATION_SELECTION_REQUIRED",
            validated_candidate=None,
            frozen_candidate=None,
            permit_calls=0,
        ),
    ],
)
def test_runtime_config_gate_preserves_empty_unique_multiple_policy(
    observation: RuntimeConfigGateObservation,
) -> None:
    observation.validate()


def test_stage_trace_requires_the_full_launcher_sequence_and_running_status() -> None:
    trace = StageTraceObservation(
        stages=(
            "GAME_PROCESS_DETECTED",
            "PROXY_START_REQUESTED",
            "COMMAND_VALIDATE",
            "ACCESS_CONTEXT_VALIDATE",
            "TARGET_WAIT",
            "HOST_START",
            "CONTROL_CHANNEL_WAIT",
            "RUNTIME_CONFIG_CATALOG",
            "RUNTIME_CONFIG_VALIDATE",
            "TARGET_RECHECK",
            "CHALLENGE_REQUEST",
            "TARGET_BIND",
            "PERMIT_REQUEST",
            "AUTHORIZED_START",
            "RUNNING_VERIFY",
        ),
        final_core_status="CoreStatus.RUNNING",
    )

    trace.validate_success()


def test_core_ownership_binds_pipe_shutdown_and_exit_to_exact_owned_pid() -> None:
    observation = CoreOwnershipObservation(
        launcher_owned_core_pid=4_321,
        named_pipe_server_pid=4_321,
        shutdown_requested_pid=4_321,
        exited_core_pid=4_321,
        unrelated_core_pids_before=frozenset({8_888}),
        unrelated_core_pids_after=frozenset({8_888}),
        taskkill_commands=(),
        orphan_core_pids=frozenset(),
        singleton_released=True,
        graceful_shutdown=True,
        emergency_fallback_used=False,
    )

    observation.validate()


def test_synthetic_cleanup_failure_matrix_and_closed_execution_gates_are_ready() -> None:
    SyntheticDataPlan.minimum().validate()
    CleanupPlan.deterministic().validate()
    validate_failure_matrix(FAILURE_MATRIX)
    PreparationAudit().validate()

    gates = FinalExecutionGates(
        historical_pso2_mode_recovered=False,
        runtime_catalog_state=RuntimeCatalogState.EMPTY,
        hosted_core_running_kp_passed=False,
    )
    assert gates.blockers() == (
        "HISTORICAL_PSO2_MODE_SOURCE_REQUIRED",
        "UNIQUE_RUNTIME_CONFIGURATION_REQUIRED",
        "HOSTED_CORE_RUNNING_KP_REQUIRED",
    )
    with pytest.raises(ValueError, match="final execution gates are closed"):
        gates.require_final_ready()


def test_preparation_manifest_is_secret_safe_and_records_zero_live_actions(
    tmp_path: Path,
) -> None:
    output = tmp_path / "preparation-manifest.json"

    validate_preparation_contract()
    write_preparation_manifest(output)
    manifest = default_preparation_manifest()
    written = output.read_text(encoding="utf-8")

    assert '"permit_calls": 0' in written
    assert '"authorized_core_start_calls": 0' in written
    assert '"a_b_c_a_executed": false' in written
    assert manifest["permit_semantics"] == {
        "already_issued_permit_max_seconds": 30,
        "replacement_blocks_future_permit_issuance": True,
        "retroactive_core_revocation_required": False,
    }
    assert all(
        forbidden not in written.lower()
        for forbidden in (
            "access_token",
            "refresh_token",
            "raw_jwt",
            "service_role_key",
            "launch_permit",
        )
    )


def test_prepare_cli_cannot_call_network_or_spawn_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_live_action(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("preparation attempted a live action")

    monkeypatch.setattr("socket.create_connection", forbidden_live_action)
    monkeypatch.setattr("subprocess.Popen", forbidden_live_action)
    output = tmp_path / "offline-preparation.json"

    assert main(["prepare", "--output", str(output)]) == 0

    written = output.read_text(encoding="utf-8")
    assert '"permit_calls": 0' in written
    assert '"authorized_core_start_calls": 0' in written


def test_final_core_identity_is_pinned_to_the_required_provenance() -> None:
    assert FINAL_CORE_SOURCE_SHA == "b3c9d0851cff74691500c431c0da1ec30c21927a"
    assert FINAL_CORE_ARTIFACT_PATH == Path(
        r"E:\Temp\neko-phase25-core-final-b3c9d085-FROZEN"
    )
    assert FINAL_CORE_EXE_SHA256 == (
        "1b9b0ba313ac1f8c879f07f678a2f01e5b334c29fc17323533017aed2cbffcfe"
    )
    assert FINAL_PROTECTED_PAYLOAD_SHA256 == (
        "3046c165a8d0c2516915a341c9816877c919b0a05353d72953eb3cd3282bc982"
    )
    assert FINAL_MANIFEST_SHA256 == (
        "2826a78a34f4b536c38c9a038c72ed6a4802d3da044f94cd18b895e7193f9841"
    )


def test_final_core_admission_accepts_the_pinned_artifact() -> None:
    admission = admit_final_core_artifact()

    assert admission.source_sha == FINAL_CORE_SOURCE_SHA
    assert admission.artifact_path == FINAL_CORE_ARTIFACT_PATH
    assert admission.core_exe_sha256 == FINAL_CORE_EXE_SHA256
    assert admission.protected_payload_sha256 == FINAL_PROTECTED_PAYLOAD_SHA256
    assert admission.manifest_sha256 == FINAL_MANIFEST_SHA256


@pytest.mark.parametrize(
    ("relative_path", "expected_error"),
    [
        ("NekoProxyCore.exe", "Core executable hash mismatch"),
        ("runtime-settings.nkps", "protected payload hash mismatch"),
        ("manifest.json", "manifest hash mismatch"),
    ],
)
def test_final_core_admission_rejects_changed_pinned_bytes(
    tmp_path: Path,
    relative_path: str,
    expected_error: str,
) -> None:
    _copy_writable_artifact(FINAL_CORE_ARTIFACT_PATH, tmp_path / "artifact")
    changed = tmp_path / "artifact" / relative_path
    changed.write_bytes(changed.read_bytes() + b"changed")

    with pytest.raises(ValueError, match=expected_error):
        admit_final_core_artifact(tmp_path / "artifact")


def test_final_core_admission_rejects_missing_executable(tmp_path: Path) -> None:
    _copy_writable_artifact(FINAL_CORE_ARTIFACT_PATH, tmp_path / "artifact")
    (tmp_path / "artifact" / "NekoProxyCore.exe").unlink()

    with pytest.raises(ValueError, match="artifact is unavailable"):
        admit_final_core_artifact(tmp_path / "artifact")


def test_final_core_admission_accepts_an_alternate_path_with_identical_bytes(
    tmp_path: Path,
) -> None:
    _copy_writable_artifact(FINAL_CORE_ARTIFACT_PATH, tmp_path / "alternate")

    admission = admit_final_core_artifact(tmp_path / "alternate")

    assert admission.core_exe_sha256 == FINAL_CORE_EXE_SHA256


def test_final_core_admission_rejects_manifest_verification_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_manifest_verification(_artifact_path: Path) -> str:
        raise ValueError("manifest verification failed")

    monkeypatch.setattr(harness_module, "_manifest_digest", failed_manifest_verification)

    with pytest.raises(ValueError, match="manifest verification failed"):
        admit_final_core_artifact()


def test_final_core_admission_rejects_superseded_artifact(
    tmp_path: Path,
) -> None:
    _copy_writable_artifact(FINAL_CORE_ARTIFACT_PATH, tmp_path / "superseded")
    exe = tmp_path / "superseded" / "NekoProxyCore.exe"
    exe.write_bytes(exe.read_bytes() + b"superseded")

    with pytest.raises(ValueError, match="Core executable hash mismatch"):
        admit_final_core_artifact(tmp_path / "superseded")
