from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol


def sanitize_diagnostic_text(text: str) -> str:
    """Redact sensitive patterns like tokens and passwords."""
    if not text:
        return text
    # Match patterns like:
    # Authorization: Bearer abc
    # access_token=abc
    # password: secret
    # refresh_token=abc
    # service_role=abc
    pattern = re.compile(
        r"((?:authorization\s*:\s*bearer|access_token|refresh_token|password|passwd|secret|service_role)['\"]?\s*(?:[:=]\s*)?['\"]?)([^'\"\s]+)",
        re.IGNORECASE
    )
    return pattern.sub(r"\1<redacted>", text)


@dataclass(frozen=True)
class CoreDiagnosticsSnapshot:
    attempt_id: str | None
    stage: str
    process_event: str | None
    core_path: str
    pid: int | None
    runtime: float | None
    exit_code: int | None
    winerror: int | None
    last_diagnostic: str | None


class DiagnosticsSink(Protocol):
    def begin_attempt(self, attempt_id: str) -> None: ...
    def record_stage(self, stage: str, **kwargs: Any) -> None: ...
    def record_process_event(self, event: str, **kwargs: Any) -> None: ...
    def record_exception(self, exc: Exception, stage: str) -> None: ...


class CoreDiagnosticsRecorder:
    """Thread-safe state holder for development diagnostics.

    This separates technical/debugging concerns from the domain AppState.
    """

    def __init__(self, sink: DiagnosticsSink) -> None:
        self._sink = sink
        self._lock = RLock()
        self._attempt_id: str | None = None
        self._stage = "IDLE"
        self._process_event: str | None = None
        self._core_path = ""
        self._pid: int | None = None
        self._runtime: float | None = None
        self._exit_code: int | None = None
        self._winerror: int | None = None
        self._last_diagnostic: str | None = None

    def snapshot(self) -> CoreDiagnosticsSnapshot:
        with self._lock:
            return CoreDiagnosticsSnapshot(
                attempt_id=self._attempt_id,
                stage=self._stage,
                process_event=self._process_event,
                core_path=self._core_path,
                pid=self._pid,
                runtime=self._runtime,
                exit_code=self._exit_code,
                winerror=self._winerror,
                last_diagnostic=self._last_diagnostic,
            )

    @property
    def current_attempt_id(self) -> str | None:
        with self._lock:
            return self._attempt_id

    def begin_attempt(self, attempt_id: str) -> None:
        with self._lock:
            self._attempt_id = attempt_id
            self._stage = "STARTING"
            self._process_event = None
            self._core_path = ""
            self._pid = None
            self._runtime = None
            self._exit_code = None
            self._winerror = None
            self._last_diagnostic = None
            self._sink.begin_attempt(attempt_id)

    def record_stage(self, stage: str, **kwargs: Any) -> None:
        with self._lock:
            self._stage = stage
            if "core_path" in kwargs:
                self._core_path = kwargs["core_path"]
            if "pid" in kwargs:
                self._pid = kwargs["pid"]
            if "runtime" in kwargs:
                self._runtime = kwargs["runtime"]
            if "exit_code" in kwargs:
                self._exit_code = kwargs["exit_code"]
            self._sink.record_stage(stage, **kwargs)

    def record_process_event(self, event: str, **kwargs: Any) -> None:
        with self._lock:
            self._process_event = event
            if "pid" in kwargs:
                self._pid = kwargs["pid"]
            if "runtime" in kwargs:
                self._runtime = kwargs["runtime"]
            if "exit_code" in kwargs:
                self._exit_code = kwargs["exit_code"]
            self._sink.record_process_event(event, **kwargs)

    def record_exception(self, exc: Exception, stage: str) -> None:
        with self._lock:
            self._stage = stage
            winerror = getattr(exc, "winerror", None)
            self._winerror = winerror

            exc_type = type(exc).__name__
            message = sanitize_diagnostic_text(str(exc))
            
            diagnostic_msg = f"{exc_type}: {message}"
            if winerror is not None:
                diagnostic_msg += f" (WinError {winerror})"
            
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            sanitized_tb = sanitize_diagnostic_text(tb)
            self._last_diagnostic = f"{diagnostic_msg}\n{sanitized_tb}"
            
            self._sink.record_exception(exc, stage)


class NoopDiagnosticsSink:
    def begin_attempt(self, attempt_id: str) -> None: pass
    def record_stage(self, stage: str, **kwargs: Any) -> None: pass
    def record_process_event(self, event: str, **kwargs: Any) -> None: pass
    def record_exception(self, exc: Exception, stage: str) -> None: pass
