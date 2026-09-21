from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
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
from neko_launcher.infrastructure.installation_credential import (
    create_installation_credential_provider,
)


def dispatch_baseline_enrollment(argv: list[str]) -> int:
    """Handle internal --enroll-baseline command mode; returns process exit code."""
    if len(argv) < 2 or argv[1] != "--enroll-baseline":
        return 2

    try:
        cwd = Path.cwd().resolve()
        if (cwd / "baseline" / "release-v2.json").is_file():
            install_root = cwd
        elif len(argv) >= 3 and argv[2]:
            install_root = Path(argv[2]).resolve()
        else:
            install_root = root_validator.get_expected_install_root()

        trust_profile = load_installed_update_trust_profile(install_root)
        envelope_path = install_root / "baseline" / "release-v2.json"
        result = enroll_baseline_from_signed_envelope(
            install_root=install_root,
            envelope_path=envelope_path,
            trust_profile=trust_profile,
        )
        if result.enrolled:
            credential_provider = create_installation_credential_provider(install_root)
            credential_provider.provision()
            return 0
        return 1
    except Exception:
        return 1


def _maybe_sync_committed_generation(install_root: Path) -> None:
    """If a committed generation is newer than the running launcher, safely replace and relaunch."""
    try:
        current_exe = Path(sys.executable).resolve()
        if not current_exe.is_file() or current_exe.name.lower() != "nekolauncher.exe":
            return
        if current_exe.parent != install_root:
            return

        old_backup = current_exe.with_name("NekoLauncher.exe.old")
        if old_backup.is_file():
            try:
                old_backup.unlink()
            except OSError:
                pass

        state_dir = install_root / "state"
        slot_a = state_dir / "slot-a.bin"
        slot_b = state_dir / "slot-b.bin"
        if not (slot_a.is_file() and slot_b.is_file()):
            return

        profile = load_installed_update_trust_profile(install_root)
        if profile is None:
            return

        from neko_launcher.infrastructure.software_release_identity import sha256_file
        from neko_launcher.updater.slot_selector import SelectionStatus
        from neko_launcher.updater.slot_store import SlotStore

        store = SlotStore(slot_a, slot_b, profile.release_public_keys)
        try:
            selection = store.load()
        finally:
            store.close()

        if selection.status != SelectionStatus.SELECTED or selection.state is None:
            return
        committed = selection.state.committed
        if committed is None:
            return

        current_sha = sha256_file(current_exe)
        if current_sha == committed.launcher_identity_sha256:
            return

        committed_id = f"g-{committed.binding.release_sequence:020d}-{committed.binding.payload_sha256}"
        committed_exe = install_root / "releases" / committed_id / "NekoLauncher.exe"
        if not committed_exe.is_file():
            return
        if sha256_file(committed_exe) != committed.launcher_identity_sha256:
            return

        os.replace(current_exe, old_backup)
        shutil.copy2(committed_exe, current_exe)

        committed_core = install_root / "releases" / committed_id / "ProxyCore"
        root_core = install_root / "ProxyCore"
        if committed_core.is_dir() and root_core.is_dir():
            manifest_candidates = [
                root_core / "core-manifest.json",
                root_core / "canonical-core-manifest.json",
            ]
            cur_manifest = next((p for p in manifest_candidates if p.is_file()), None)
            if cur_manifest is None or sha256_file(cur_manifest) != committed.core_identity_sha256:
                shutil.copytree(committed_core, root_core, dirs_exist_ok=True)

        subprocess.Popen([str(current_exe)] + sys.argv[1:])
        sys.exit(0)
    except Exception:
        pass


def main() -> None:
    if any(arg == "--enroll-baseline" or arg.startswith("--enroll-baseline") for arg in sys.argv[1:]):
        sys.exit(dispatch_baseline_enrollment(sys.argv))

    if maybe_dispatch_updater_entry(sys.argv):
        return

    try:
        install_root = root_validator.get_expected_install_root()
        _maybe_sync_committed_generation(install_root)
    except Exception:
        pass

    mutex_handle = acquire_instance_mutex()
    if mutex_handle is None:
        show_already_running_message()
        return
    exit_code = 0
    try:
        bootstrap_result = run_pending_update_bootstrap()
        if bootstrap_result == PendingUpdateBootstrapResult.HANDOFF_STARTED:
            if sys.platform == "win32" and getattr(sys, "frozen", False):
                relaunch_cmd = f'cmd.exe /c timeout /t 3 /nobreak >nul & start "" "{sys.executable}"'
                cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                try:
                    subprocess.Popen(relaunch_cmd, shell=False, creationflags=cflags)
                except Exception:
                    pass
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
