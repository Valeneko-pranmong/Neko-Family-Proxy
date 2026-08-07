from threading import Event

from neko_launcher.infrastructure.process.process_detector import (
    PSO2_PROCESS_NAMES,
    ExactPso2TargetDetector,
    TargetProcess,
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
