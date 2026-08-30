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
    session_logs = list(log_dir.glob("neko-support-*.log"))
    assert len(session_logs) == 1
    assert "NEKO FAMILY PROXY SUPPORT DIAGNOSTIC SESSION" in latest
    assert "DEBUG_VERBOSE = NO" in latest
    assert hashlib.sha256(b"core-exe").hexdigest() in latest
    assert hashlib.sha256(b"core-dll").hexdigest() in latest
    assert "should-not-leak" not in latest
    assert "<redacted>" in latest


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


def test_application_factory_always_constructs_support_logger() -> None:
    source = Path(__file__).parents[1].joinpath(
        "src", "neko_launcher", "bootstrap", "app_factory.py"
    ).read_text(encoding="utf-8")
    assert "DevelopmentLogger(" in source
    assert "verbose=config.debug_mode" in source
    diagnostics_section = source.split("DevelopmentLogger")[1].split("CoreDiagnosticsRecorder")[0]
    assert "NoopDiagnosticsSink" not in diagnostics_section
