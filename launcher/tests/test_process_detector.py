import subprocess
from threading import Event

import pytest

from neko_launcher.infrastructure.process.process_detector import (
    PSO2_PROCESS_NAMES,
    ExactPso2TargetDetector,
    ProcessObservationUnavailable,
    TargetProcess,
    _snapshot_processes,
    is_any_process_running,
)


def test_auto_connect_watches_only_the_running_game_process() -> None:
    assert PSO2_PROCESS_NAMES == frozenset({"pso2.exe"})


def test_exact_detector_returns_only_pso2_target() -> None:
    snapshots = [
        (TargetProcess(1, "Tweaker.exe", 10),),
        (TargetProcess(2, "pso2.exe", 20),),
    ]
    detector = ExactPso2TargetDetector(
        snapshot=lambda: snapshots.pop(0),
        poll_interval=0.001,
    )

    target = detector.wait_for_exact_pso2(0.1, Event())

    assert target == TargetProcess(2, "pso2.exe", 20)


def test_exact_detector_is_bounded_and_cancellable() -> None:
    cancellation = Event()
    cancellation.set()
    detector = ExactPso2TargetDetector(snapshot=lambda: (), poll_interval=0.001)

    assert detector.wait_for_exact_pso2(0.1, cancellation) is None


def test_same_target_check_requires_matching_pid_and_exact_name() -> None:
    target = TargetProcess(42, "pso2.exe", 100)
    current = [TargetProcess(43, "pso2.exe", 100)]
    detector = ExactPso2TargetDetector(snapshot=lambda: tuple(current))

    assert detector.is_same_target_still_running(target) is False

    current[:] = [target]

    assert detector.is_same_target_still_running(target) is True


def test_same_target_check_rejects_pid_reuse_with_new_creation_identity() -> None:
    target = TargetProcess(42, "pso2.exe", 100)
    detector = ExactPso2TargetDetector(
        snapshot=lambda: (TargetProcess(42, "pso2.exe", 101),)
    )

    assert detector.is_same_target_still_running(target) is False


def test_same_target_check_preserves_process_observation_failure() -> None:
    target = TargetProcess(42, "pso2.exe", 100)

    def fail_snapshot() -> tuple[TargetProcess, ...]:
        raise ProcessObservationUnavailable

    detector = ExactPso2TargetDetector(snapshot=fail_snapshot)

    with pytest.raises(ProcessObservationUnavailable):
        detector.is_same_target_still_running(target)


def test_process_name_check_preserves_nonzero_process_command_exit(monkeypatch) -> None:
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="access denied"
        ),
    )

    assert is_any_process_running() is None


def test_exact_snapshot_preserves_nonzero_process_command_exit(monkeypatch) -> None:
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="access denied"
        ),
    )

    with pytest.raises(ProcessObservationUnavailable):
        _snapshot_processes()


def test_exact_snapshot_preserves_pso2_creation_identity_lookup_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.os.name", "nt"
    )
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout='"pso2.exe","42"\n', stderr=""
        ),
    )
    monkeypatch.setattr(
        "neko_launcher.infrastructure.process.process_detector._windows_creation_identity",
        lambda _pid: None,
    )

    with pytest.raises(ProcessObservationUnavailable):
        _snapshot_processes()
