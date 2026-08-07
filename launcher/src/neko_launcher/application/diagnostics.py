from __future__ import annotations

import traceback
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol


@dataclass(frozen=True)
class CoreDiagnosticsSnapshot:
    attempt_id: str | None
    stage: str
    core_path: str
    pid: int | None
    runtime: float | None
    exit_code: int | None
    winerror: int | None
    last_diagnostic: str | None


class DiagnosticsSink(Protocol):
    def begin_attempt(self, attempt_id: str) -> None: ...
    def record_stage(self, stage: str, **kwargs: Any) -> None: ...
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

    def record_exception(self, exc: Exception, stage: str) -> None:
        with self._lock:
            self._stage = stage
            winerror = getattr(exc, "winerror", None)
            self._winerror = winerror

            exc_type = type(exc).__name__
            message = str(exc)
            # Safe sanitization without exposing secrets: just type and message
            diagnostic_msg = f"{exc_type}: {message}"
            if winerror is not None:
                diagnostic_msg += f" (WinError {winerror})"
            
            tb = traceback.format_exc()
            self._last_diagnostic = f"{diagnostic_msg}\n{tb}"
            
            self._sink.record_exception(exc, stage)


class NoopDiagnosticsSink:
    def begin_attempt(self, attempt_id: str) -> None: pass
    def record_stage(self, stage: str, **kwargs: Any) -> None: pass
    def record_exception(self, exc: Exception, stage: str) -> None: pass
