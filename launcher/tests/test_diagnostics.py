from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    PermitDiagnosticCode,
)
from neko_launcher.application.diagnostics import (
    sanitize_diagnostic_text,
    CoreDiagnosticsRecorder,
    NoopDiagnosticsSink,
)
from neko_launcher.infrastructure.diagnostics_logger import DevelopmentLogger


class DiagnosticSpoofError(RuntimeError):
    diagnostic_code = "ACCESS_TOKEN=RAW_JWT_SENTINEL"
    diagnostic_context = {
        "function": "RAW_FUNCTION_SENTINEL",
        "stage": "RAW_STAGE_SENTINEL",
        "http_status": "RAW_STATUS_SENTINEL",
        "correlation_id": "RAW_CORRELATION_SENTINEL",
        "elapsed_ms": "RAW_ELAPSED_SENTINEL",
        "exception_class": "RAW_EXCEPTION_SENTINEL",
    }


def test_sanitize_diagnostic_text():
    # Ordinary text
    assert sanitize_diagnostic_text("normal error") == "normal error"

    # Redaction
    assert (
        sanitize_diagnostic_text("Authorization: Bearer mytoken123")
        == "Authorization: Bearer <redacted>"
    )
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


def permit_not_found_error() -> AuthorizedCoreError:
    return AuthorizedCoreError(
        AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
        diagnostic_code=PermitDiagnosticCode.PERMIT_FUNCTION_NOT_FOUND,
        diagnostic_context={
            "function": "issue_launch_permit",
            "stage": "PERMIT_REQUEST",
            "http_status": 404,
            "correlation_id": "0123456789abcdef0123456789abcdef",
            "elapsed_ms": 12,
            "exception_class": "FunctionsHttpError",
            "access_token": "sentinel-secret",
        },
    )


def test_permit_diagnostic_snapshot_contains_only_sanitized_context():
    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    recorder.begin_attempt("DBG-123")

    recorder.record_exception(permit_not_found_error(), "PERMIT_REQUEST")

    diagnostic = recorder.snapshot().last_diagnostic or ""
    assert "PERMIT_FUNCTION_NOT_FOUND" in diagnostic
    assert "http_status=404" in diagnostic
    assert "function=issue_launch_permit" in diagnostic
    assert "sentinel-secret" not in diagnostic
    assert "access_token" not in diagnostic


def test_permit_diagnostic_logs_only_sanitized_category_and_context(tmp_path):
    logger = DevelopmentLogger(tmp_path)
    logger.begin_attempt("DBG-123")
    error = permit_not_found_error()

    logger.record_exception(error, "PERMIT_REQUEST")

    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "PERMIT_FUNCTION_NOT_FOUND" in log_text
    assert "http_status=404" in log_text
    assert "function=issue_launch_permit" in log_text
    assert "correlation_id=0123456789abcdef0123456789abcdef" in log_text
    assert "sentinel-secret" not in log_text
    assert "access_token" not in log_text


def test_permit_diagnostic_rejects_untrusted_allow_list_values(tmp_path):
    logger = DevelopmentLogger(tmp_path)
    logger.begin_attempt("DBG-123")
    error = AuthorizedCoreError(
        AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE,
        diagnostic_code=PermitDiagnosticCode.PERMIT_UNAVAILABLE,
        diagnostic_context={
            "function": "RAW_JWT_SENTINEL_XYZ",
            "stage": "RAW_REFRESH_TOKEN_SENTINEL",
            "http_status": "RAW_STATUS_SENTINEL",
            "correlation_id": "RAW_CORRELATION_SENTINEL",
            "elapsed_ms": "RAW_ELAPSED_SENTINEL",
            "exception_class": "RAW_EXCEPTION_SENTINEL",
        },
    )

    logger.record_exception(error, "PERMIT_REQUEST")

    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "PERMIT_UNAVAILABLE" in log_text
    assert "RAW_" not in log_text
    assert error.diagnostic_context == {}


def test_diagnostic_formatter_rejects_spoofed_exception_metadata(tmp_path):
    logger = DevelopmentLogger(tmp_path)
    logger.begin_attempt("DBG-123")

    logger.record_exception(DiagnosticSpoofError("customer-safe failure"), "PERMIT_REQUEST")

    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "customer-safe failure" in log_text
    assert "RAW_" not in log_text
    assert "ACCESS_TOKEN" not in log_text


def test_authorized_start_stage_logs_only_allow_listed_fields(tmp_path):
    logger = DevelopmentLogger(tmp_path)
    logger.begin_attempt("DBG-123")

    logger.record_stage(
        "AUTHORIZED_START_RESULT",
        elapsed_ms=31_234,
        failure_category="START_RESPONSE_TIMEOUT",
        core_pid=4321,
        core_alive=True,
        transport_outcome="CORE_ALIVE_NO_RESPONSE",
        permit="RAW_PERMIT_SENTINEL",
        challenge="RAW_CHALLENGE_SENTINEL",
        access_token="RAW_TOKEN_SENTINEL",
    )

    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    assert "elapsed_ms=31234" in log_text
    assert "failure_category=START_RESPONSE_TIMEOUT" in log_text
    assert "core_pid=4321" in log_text
    assert "core_alive=True" in log_text
    assert "transport_outcome=CORE_ALIVE_NO_RESPONSE" in log_text
    assert "RAW_" not in log_text
    assert "permit" not in log_text.lower()
    assert "challenge" not in log_text.lower()


def test_secret_redaction_unit_gate(tmp_path, capsys):
    """SECRET REDACTION UNIT GATE: verify all synthetic secrets are redacted before write."""
    synthetic_bearer = "Bearer synthetic_bearer_token_xyz987"
    synthetic_jwt = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMTIzIn0.synthetic_signature_abcdef1234567890"
    synthetic_refresh = "synthetic_refresh_token_abc"
    synthetic_password = "synthetic_secret_password_p@ss123"
    synthetic_challenge = "synthetic_challenge_payload_abcdef1234567890"
    synthetic_pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0syntheticprivatekeydata12345\n-----END RSA PRIVATE KEY-----"

    secret_sentinels = [
        "synthetic_bearer_token_xyz987",
        synthetic_jwt,
        synthetic_refresh,
        synthetic_password,
        synthetic_challenge,
        "MIIEowIBAAKCAQEA0syntheticprivatekeydata12345",
    ]

    logger = DevelopmentLogger(tmp_path)
    logger.begin_attempt("SECRET-GATE")

    # 1. Test message write with secrets
    logger.record_stage("STAGE_A", auth=synthetic_bearer, token=synthetic_jwt)
    logger.record_process_event("EVENT_A", refresh_token=synthetic_refresh, password=synthetic_password)

    # 2. Test exception with secrets in message and traceback
    try:
        raise ValueError(f"Failed with challenge={synthetic_challenge} and {synthetic_pem}")
    except ValueError as exc:
        logger.record_exception(exc, "SECRET_STAGE")

    # Verify log file
    log_text = (tmp_path / "debug.log").read_text(encoding="utf-8")
    for sentinel in secret_sentinels:
        assert sentinel not in log_text, f"Secret sentinel '{sentinel}' leaked in log file!"

    # Verify console output
    captured = capsys.readouterr()
    for sentinel in secret_sentinels:
        assert sentinel not in captured.out, f"Secret sentinel '{sentinel}' leaked in console stdout!"
        assert sentinel not in captured.err, f"Secret sentinel '{sentinel}' leaked in console stderr!"
