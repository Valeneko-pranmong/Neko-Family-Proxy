from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import neko_launcher.e2e.final_windows_harness as harness_module
from neko_launcher.e2e.final_windows_harness import (
    CleanupStep,
    FinalCoreAdmission,
    FinalExecutionGates,
    FinalWindowsE2EHarness,
    InstanceId,
    LiveClaimResult,
    RuntimeCatalogState,
    WindowsFinalSequenceDriver,
)


@pytest.fixture(autouse=True)
def deterministic_artifact_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = FinalCoreAdmission(
        source_sha="b3c9d0851cff74691500c431c0da1ec30c21927a",
        artifact_path=Path(r"E:\Temp\admitted-final-core"),
        core_exe_sha256="1" * 64,
        protected_payload_sha256="2" * 64,
        manifest_sha256="3" * 64,
        pso2_mode_sha256="4" * 64,
        manifest_controlled_file_count=245,
        physical_file_count=246,
    )
    monkeypatch.setattr(
        harness_module,
        "admit_final_core_artifact",
        lambda _path=None: admission,
    )


@dataclass
class FakeFinalDriver:
    calls: list[str]
    cleanup_failure: CleanupStep | None = None
    admitted_paths: list[str] | None = None

    def __post_init__(self) -> None:
        self.claim_count = 0
        self.active_session: tuple[InstanceId, str] | None = None
        self.installations = {
            InstanceId.INSTANCE_A: "iid_aaaaaaaaaaaaaaaa",
            InstanceId.INSTANCE_B: "iid_bbbbbbbbbbbbbbbb",
            InstanceId.INSTANCE_C: "iid_cccccccccccccccc",
        }

    def claim(
        self, instance: InstanceId, admission: FinalCoreAdmission
    ) -> LiveClaimResult:
        assert admission.source_sha
        assert admission.artifact_path.name
        if self.admitted_paths is not None:
            self.admitted_paths.append(str(admission.artifact_path))
        self.claim_count += 1
        session_ref = f"sid_{self.claim_count:016x}"
        self.active_session = (instance, session_ref)
        self.calls.append(f"claim:{instance.value}")
        return LiveClaimResult(
            instance=instance,
            session_ref=session_ref,
            installation_ref=self.installations[instance],
        )

    def heartbeat_accepted(self, instance: InstanceId, session_ref: str) -> bool:
        self.calls.append(f"heartbeat:{instance.value}:{session_ref}")
        return self.active_session == (instance, session_ref)

    def future_permit_eligible(self, instance: InstanceId, session_ref: str) -> bool:
        self.calls.append(f"permit-eligibility:{instance.value}:{session_ref}")
        return self.active_session == (instance, session_ref)

    def cleanup(self, step: CleanupStep) -> None:
        self.calls.append(f"cleanup:{step.value}")
        if step is self.cleanup_failure:
            raise RuntimeError("sanitized cleanup failure")


def test_final_sequence_is_gate_bound_and_runs_claim_authority_assertions_in_order() -> None:
    calls: list[str] = []
    admitted_paths: list[str] = []
    driver = FakeFinalDriver(calls, admitted_paths=admitted_paths)
    harness = FinalWindowsE2EHarness(
        gates=FinalExecutionGates(
            historical_pso2_mode_recovered=True,
            runtime_catalog_state=RuntimeCatalogState.UNIQUE,
            hosted_core_running_kp_passed=True,
        ),
        driver=driver,
    )

    result = harness.run()

    assert result.authoritative_instance is InstanceId.INSTANCE_A
    assert result.remembered_installation_count == 3
    assert len(set(admitted_paths)) == 1
    assert len(admitted_paths) == 4
    assert calls[:13] == [
        "claim:INSTANCE_A",
        "heartbeat:INSTANCE_A:sid_0000000000000001",
        "claim:INSTANCE_B",
        "heartbeat:INSTANCE_B:sid_0000000000000002",
        "heartbeat:INSTANCE_A:sid_0000000000000001",
        "permit-eligibility:INSTANCE_A:sid_0000000000000001",
        "claim:INSTANCE_C",
        "heartbeat:INSTANCE_C:sid_0000000000000003",
        "heartbeat:INSTANCE_B:sid_0000000000000002",
        "permit-eligibility:INSTANCE_B:sid_0000000000000002",
        "claim:INSTANCE_A",
        "heartbeat:INSTANCE_A:sid_0000000000000004",
        "heartbeat:INSTANCE_C:sid_0000000000000003",
    ]
    assert calls[13] == "permit-eligibility:INSTANCE_C:sid_0000000000000003"
    assert calls[14:] == [f"cleanup:{step.value}" for step in CleanupStep]


def test_closed_final_gates_cannot_reach_claim_or_cleanup_driver_calls() -> None:
    calls: list[str] = []
    harness = FinalWindowsE2EHarness(
        gates=FinalExecutionGates(
            historical_pso2_mode_recovered=False,
            runtime_catalog_state=RuntimeCatalogState.EMPTY,
            hosted_core_running_kp_passed=False,
        ),
        driver=FakeFinalDriver(calls),
    )

    with pytest.raises(ValueError, match="final execution gates are closed"):
        harness.run()

    assert calls == []


def test_failed_artifact_admission_cannot_reach_claim_challenge_or_permit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "neko_launcher.e2e.final_windows_harness.admit_final_core_artifact",
        lambda _path=None: (_ for _ in ()).throw(ValueError("Core executable hash mismatch")),
    )
    harness = FinalWindowsE2EHarness(
        gates=FinalExecutionGates(
            historical_pso2_mode_recovered=True,
            runtime_catalog_state=RuntimeCatalogState.UNIQUE,
            hosted_core_running_kp_passed=True,
        ),
        driver=FakeFinalDriver(calls),
    )

    with pytest.raises(ValueError, match="Core executable hash mismatch"):
        harness.run()

    assert calls == []


def test_cleanup_failure_runs_every_scoped_cleanup_step_and_fails_the_run() -> None:
    calls: list[str] = []
    harness = FinalWindowsE2EHarness(
        gates=FinalExecutionGates(
            historical_pso2_mode_recovered=True,
            runtime_catalog_state=RuntimeCatalogState.UNIQUE,
            hosted_core_running_kp_passed=True,
        ),
        driver=FakeFinalDriver(
            calls,
            cleanup_failure=CleanupStep.DELETE_TEST_LAUNCHER_SESSIONS,
        ),
    )

    with pytest.raises(ValueError, match="scoped cleanup steps failed"):
        harness.run()

    assert calls[-len(CleanupStep) :] == [
        f"cleanup:{step.value}" for step in CleanupStep
    ]


class ConcreteProcess:
    def __init__(self, calls):
        self.calls = calls
        self.identity = None

    def start_admitted_core(self, admission):
        self.calls.append(("spawn", admission.artifact_path))
        self.identity = SimpleNamespace(provenance_verified=True)
        return self.identity

    def wait_for_control_channel(self, timeout):
        self.calls.append(("pipe", timeout))

    def owned_process_id(self):
        return 2468 if self.identity is not None else None

    def wait_for_owned_process_exit(self, expected_pid, timeout):
        self.calls.append(("wait", expected_pid, timeout))
        self.identity = None
        return 0

    def terminate_owned_process_after_timeout(self, expected_pid, timeout):
        self.calls.append(("kill", expected_pid, timeout))
        self.identity = None
        return 1


class ConcreteControl:
    def status(self, correlation_id, timeout):
        return object()

    def shutdown(self, correlation_id, timeout):
        return SimpleNamespace(kind=SimpleNamespace(value="Stopped"))


def test_final_harness_can_use_concrete_production_composed_driver() -> None:
    calls = []
    process = ConcreteProcess(calls)
    authority = FakeFinalDriver(calls)
    driver = WindowsFinalSequenceDriver(
        authority=authority,
        process=process,
        control=ConcreteControl(),
        control_channel_timeout=3.0,
        shutdown_timeout=4.0,
    )
    harness = FinalWindowsE2EHarness(
        gates=FinalExecutionGates(
            historical_pso2_mode_recovered=True,
            runtime_catalog_state=RuntimeCatalogState.UNIQUE,
            hosted_core_running_kp_passed=True,
        ),
        driver=driver,
    )

    result = harness.run()

    assert result.authoritative_instance is InstanceId.INSTANCE_A
    assert [kind for kind, *_rest in calls if kind == "spawn"] == ["spawn"]
    assert any(kind == "pipe" for kind, *_rest in calls)
    assert any(kind == "wait" for kind, *_rest in calls)
