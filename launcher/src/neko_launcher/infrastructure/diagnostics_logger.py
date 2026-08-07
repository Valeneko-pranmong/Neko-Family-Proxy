from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any


class DevelopmentLogger:
    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._log_dir / "debug.log"
        self._attempt_id: str | None = None

    def begin_attempt(self, attempt_id: str) -> None:
        self._attempt_id = attempt_id
        self._write(f"=== BEGIN ATTEMPT {attempt_id} ===")

    def record_stage(self, stage: str, **kwargs: Any) -> None:
        msg = f"[CORE] [{stage}]"
        if kwargs:
            details = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            msg += f" {details}"
        self._write(msg)

    def record_exception(self, exc: Exception, stage: str) -> None:
        exc_type = type(exc).__name__
        msg = f"[CORE] [{stage}] FAILED - {exc_type}: {exc}"
        winerror = getattr(exc, "winerror", None)
        if winerror is not None:
            msg += f" (WinError {winerror})"
        self._write(msg)

    def _write(self, message: str) -> None:
        now = datetime.datetime.now()
        ts = now.strftime("%H:%M:%S.%f")[:-3]
        attempt = f"[{self._attempt_id}]" if self._attempt_id else "[]"
        
        log_line = f"[{ts}] {attempt} {message}\n"
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
        except OSError:
            pass
