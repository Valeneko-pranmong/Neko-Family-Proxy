from __future__ import annotations

import hashlib
from pathlib import Path

from neko_launcher.infrastructure.diagnostics_logger import DevelopmentLogger


def test_support_log_is_created_without_debug_mode_and_records_artifact_hashes(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    core_dir = tmp_path / "ProxyCore"
    core_dir.mkdir()
    core_exe = core_dir / "NekoProxyCore.exe"
    core_dll = core_dir / "NekoProxyCore.dll"
    core_exe.write_bytes(b"core-exe")
    core_dll.write_bytes(b"core-dll")

    logger = DevelopmentLogger(log_dir, verbose=False)
    logger.log_session_header(core_path=str(core_exe), workspace_root=str(tmp_path))
    logger.record_stage("LAUNCHER_START", support_log="enabled")
    logger.record_stage("AUTH_TEST", password="should-not-leak")

    latest = (log_dir / "support.log").read_text(encoding="utf-8")
    debug = (log_dir / "debug.log").read_text(encoding="utf-8")
    session_logs = list(log_dir.glob("neko-support-*.log"))
    assert len(session_logs) == 1
    session = session_logs[0].read_text(encoding="utf-8")
    for content in (latest, debug, session):
        assert "NEKO FAMILY PROXY SUPPORT DIAGNOSTIC SESSION" in content
        assert "DEBUG_VERBOSE = NO" in content
        assert hashlib.sha256(b"core-exe").hexdigest() in content
        assert hashlib.sha256(b"core-dll").hexdigest() in content
        assert "should-not-leak" not in content
        assert "<redacted>" in content


def test_support_log_rotation_keeps_at_most_ten_session_logs(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    for index in range(12):
        path = log_dir / f"neko-support-old-{index:02d}.log"
        path.write_text(str(index), encoding="utf-8")
        path.touch()

    logger = DevelopmentLogger(log_dir, verbose=False)
    logger.log_session_header()

    assert len(list(log_dir.glob("neko-support-*.log"))) <= 10


def test_logger_writes_without_reopening_log_files(
    tmp_path: Path, monkeypatch
) -> None:
    log_dir = tmp_path / "logs"
    logger = DevelopmentLogger(log_dir, verbose=False)
    original_open = Path.open

    def fail_open(*args, **kwargs):
        raise AssertionError("log writes must not reopen files")

    monkeypatch.setattr(Path, "open", fail_open)
    try:
        logger.record_stage("STREAM_WRITE_TEST")
    finally:
        monkeypatch.setattr(Path, "open", original_open)

    try:
        for path in (
            log_dir / "support.log",
            log_dir / "debug.log",
            next(log_dir.glob("neko-support-*.log")),
        ):
            assert "STREAM_WRITE_TEST" in path.read_text(encoding="utf-8")
    finally:
        logger.close()


def test_structured_events_include_category_event_timing_and_redaction(
    tmp_path: Path,
) -> None:
    logger = DevelopmentLogger(tmp_path, verbose=False)

    logger.record_event(
        "AUTH",
        "FLOW_PHASE",
        phase="waiting_for_browser",
        elapsed_ms=1250,
        access_token="synthetic-access-token",
        reason="customer\nretry",
    )

    text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "[AUTH] [FLOW_PHASE]" in text
    assert "phase=waiting_for_browser" in text
    assert "elapsed_ms=1250" in text
    assert "synthetic-access-token" not in text
    assert "access_token=<redacted>" in text
    assert "customer\\nretry" in text


def test_session_header_includes_machine_and_runtime_context(
    tmp_path: Path,
) -> None:
    logger = DevelopmentLogger(tmp_path, verbose=False)
    logger.log_session_header(
        workspace_root=str(tmp_path),
        install_root=str(tmp_path),
    )

    header = (tmp_path / "support.log").read_text(encoding="utf-8")
    for marker in (
        "SUPPORT_LOG_SCHEMA = 2",
        "TIMESTAMP_LOCAL =",
        "TIMEZONE =",
        "OS_VERSION =",
        "OS_BUILD =",
        "ARCHITECTURE =",
        "CPU_COUNT =",
        "LOCALE =",
        "LAUNCHER_EXE_PATH =",
        "LOG_DIR =",
        "INSTALL_ROOT =",
        "DISK_FREE_MB =",
    ):
        assert marker in header


def test_exception_events_can_use_a_non_core_support_category(
    tmp_path: Path,
) -> None:
    logger = DevelopmentLogger(tmp_path, verbose=False)

    logger.record_exception(
        ValueError("safe failure"),
        "BACKGROUND_TASK",
        category="APP",
    )

    text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "[APP] [BACKGROUND_TASK] FAILED - ValueError: safe failure" in text


def test_application_factory_always_constructs_support_logger() -> None:
    source = Path(__file__).parents[1].joinpath(
        "src", "neko_launcher", "bootstrap", "app_factory.py"
    ).read_text(encoding="utf-8")
    assert "DevelopmentLogger(" in source
    assert "verbose=config.debug_mode" in source
    diagnostics_section = source.split("DevelopmentLogger")[1].split("CoreDiagnosticsRecorder")[0]
    assert "NoopDiagnosticsSink" not in diagnostics_section
