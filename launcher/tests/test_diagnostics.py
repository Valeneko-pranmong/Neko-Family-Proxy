from neko_launcher.application.diagnostics import (
    sanitize_diagnostic_text,
    CoreDiagnosticsRecorder,
    NoopDiagnosticsSink,
)


def test_sanitize_diagnostic_text():
    # Ordinary text
    assert sanitize_diagnostic_text("normal error") == "normal error"
    
    # Redaction
    assert sanitize_diagnostic_text("Authorization: Bearer mytoken123") == "Authorization: Bearer <redacted>"
    assert sanitize_diagnostic_text("authorization:bearer 123") == "authorization:bearer <redacted>"
    assert sanitize_diagnostic_text("access_token=secret123") == "access_token=<redacted>"
    assert sanitize_diagnostic_text("access_token: secret123") == "access_token: <redacted>"
    assert sanitize_diagnostic_text('"access_token": "secret123"') == '"access_token": "<redacted>"'
    assert sanitize_diagnostic_text("password=abc") == "password=<redacted>"
    assert sanitize_diagnostic_text("password: abc") == "password: <redacted>"
    assert sanitize_diagnostic_text("refresh_token=123") == "refresh_token=<redacted>"
    assert sanitize_diagnostic_text("service_role=123") == "service_role=<redacted>"

    # Idempotent
    text = "access_token=123"
    sanitized = sanitize_diagnostic_text(text)
    assert sanitize_diagnostic_text(sanitized) == sanitized


def test_core_diagnostics_recorder_state():
    sink = NoopDiagnosticsSink()
    recorder = CoreDiagnosticsRecorder(sink)

    # Initial state
    snapshot = recorder.snapshot()
    assert snapshot.attempt_id is None
    assert snapshot.stage == "IDLE"
    assert snapshot.process_event is None

    # Begin attempt resets everything
    recorder.begin_attempt("ATTEMPT-1")
    snapshot = recorder.snapshot()
    assert snapshot.attempt_id == "ATTEMPT-1"
    assert snapshot.stage == "STARTING"
    assert snapshot.process_event is None
    assert snapshot.core_path == ""

    # Record stage
    recorder.record_stage("HOST_START", core_path="dummy.exe", pid=123)
    snapshot = recorder.snapshot()
    assert snapshot.stage == "HOST_START"
    assert snapshot.core_path == "dummy.exe"
    assert snapshot.pid == 123
    assert snapshot.process_event is None

    # Record process event independent of stage
    recorder.record_process_event("PROCESS_EXITED_EARLY", exit_code=1)
    snapshot = recorder.snapshot()
    assert snapshot.stage == "HOST_START"
    assert snapshot.process_event == "PROCESS_EXITED_EARLY"
    assert snapshot.exit_code == 1

    # Exception
    exc = Exception("raw token=abc")
    recorder.record_exception(exc, "CONTROL_CHANNEL_WAIT")
    snapshot = recorder.snapshot()
    assert snapshot.stage == "CONTROL_CHANNEL_WAIT"
    assert "Exception" in snapshot.last_diagnostic
