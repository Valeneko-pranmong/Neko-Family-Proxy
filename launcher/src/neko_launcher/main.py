from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from neko_launcher.bootstrap.app_factory import build_window
from neko_launcher.bootstrap.single_instance import (
    acquire_instance_mutex,
    release_instance_mutex,
    show_already_running_message,
)


def main() -> None:
    mutex_handle = acquire_instance_mutex()
    if mutex_handle is None:
        show_already_running_message()
        return
    exit_code = 0
    try:
        build_window().root.mainloop()
    except Exception as exc:
        exit_code = 1
        _report_startup_error(exc)
    finally:
        release_instance_mutex(mutex_handle)
        # Force terminate immediately after mainloop finishes to prevent
        # lingering threads (such as network polling) from keeping the
        # process alive in the background and leaving a zombie process.
        os._exit(exit_code)


def _report_startup_error(exc: Exception) -> None:
    """Persist and display only allow-listed startup failure information."""
    del exc
    log_dir = Path(os.getenv("LOCALAPPDATA", ".")) / "NEKO FAMILY"
    log_file = log_dir / "launcher-error.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file.write_text("StartupFailed\n", encoding="utf-8")
    except OSError:
        pass
    message = f"เปิด Neko Launcher ไม่สำเร็จ\n\nรายละเอียด: {log_file}"
    _show_startup_error_message(message)


def _show_startup_error_message(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "Neko Launcher", 0x10)


if __name__ == "__main__":
    main()
