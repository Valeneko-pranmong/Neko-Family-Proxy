from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from neko_launcher.bootstrap.app_factory import build_window
from neko_launcher.bootstrap.baseline_enrollment import (
    enroll_baseline_from_signed_envelope,
)
from neko_launcher.bootstrap.pending_update_bootstrap import (
    PendingUpdateBootstrapResult,
    run_pending_update_bootstrap,
)
from neko_launcher.bootstrap.single_instance import (
    acquire_instance_mutex,
    release_instance_mutex,
    show_already_running_message,
)
from neko_launcher.updater.early_dispatch import maybe_dispatch_updater_entry
from neko_launcher.updater import root_validator
from neko_launcher.updater.trust_profile import load_installed_update_trust_profile


def dispatch_baseline_enrollment(argv: list[str]) -> int:
    """Handle internal --enroll-baseline command mode; returns process exit code."""
    if len(argv) != 2 or argv[1] != "--enroll-baseline":
        return 2

    try:
        install_root = root_validator.get_expected_install_root()
        trust_profile = load_installed_update_trust_profile(install_root)
        envelope_path = install_root / "baseline" / "release-v2.json"
        result = enroll_baseline_from_signed_envelope(
            install_root=install_root,
            envelope_path=envelope_path,
            trust_profile=trust_profile,
        )
        if result.enrolled:
            return 0
        return 1
    except Exception:
        return 1


def main() -> None:
    if any(arg == "--enroll-baseline" or arg.startswith("--enroll-baseline") for arg in sys.argv[1:]):
        sys.exit(dispatch_baseline_enrollment(sys.argv))

    if maybe_dispatch_updater_entry(sys.argv):
        return

    mutex_handle = acquire_instance_mutex()
    if mutex_handle is None:
        show_already_running_message()
        return
    exit_code = 0
    try:
        bootstrap_result = run_pending_update_bootstrap()
        if bootstrap_result == PendingUpdateBootstrapResult.HANDOFF_STARTED:
            return
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
