from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.production_authorization import (
    create_production_proxy_gateway,
)
from neko_launcher.application.services import LauncherService
from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.infrastructure.event_bus import EventBus
from neko_launcher.infrastructure.game_process_manager import GameProcessManager
from neko_launcher.infrastructure.installation import LocalInstallationIdentity
from neko_launcher.infrastructure.secure_store import KeyringSecureStore
from neko_launcher.infrastructure.supabase_gateway import SupabaseGateway
from neko_launcher.ui.app_window import AppWindow
from neko_launcher.application.authorized_core import (
    AuthorizedCoreOrchestrator,
    LaunchAccessContext,
    OpaqueStartCommand,
    OrchestrationTimeouts,
)
from neko_launcher.infrastructure.authorized_proxy_gateway import AuthorizedProxyGateway
from neko_launcher.infrastructure.core_control_channel import NamedPipeCoreControlChannel
from neko_launcher.infrastructure.core_process import WindowsCoreProcessAdapter
from neko_launcher.infrastructure.process_detector import ExactPso2TargetDetector
from neko_launcher.application.production_authorization import CURRENT_PRODUCTION_AUTHORIZATION
from neko_launcher.domain.models import AuthStatus, EntitlementStatus
_INSTANCE_MUTEX_NAME = "Local\\NekoFamilyProxyLauncher"
_ERROR_ALREADY_EXISTS = 183


def application_root() -> Path:
    """Return the source checkout or PyInstaller extraction directory."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def build_window(workspace_root: Path | None = None) -> AppWindow:
    root = workspace_root or application_root()
    config = LauncherConfig.from_environment(root)
    event_bus = EventBus()
    game_manager = GameProcessManager()
    secure_store = KeyringSecureStore()
    installation = LocalInstallationIdentity(secure_store)
    gateway = SupabaseGateway(
        config.supabase_url,
        config.supabase_publishable_key,
        secure_store,
    )

    if CURRENT_PRODUCTION_AUTHORIZATION.is_ready:
        core_process = WindowsCoreProcessAdapter(config.proxy_core_path)
        core_channel = NamedPipeCoreControlChannel("NekoProxyCoreControl")
        detector = ExactPso2TargetDetector()
        timeouts = OrchestrationTimeouts(
            target=30.0,
            control_channel=10.0,
            challenge=5.0,
            permit=10.0,
            start=10.0,
        )
        orchestrator = AuthorizedCoreOrchestrator(
            process=core_process,
            channel=core_channel,
            permits=gateway,
            detector=detector,
            timeouts=timeouts,
        )

        def access_context_provider() -> LaunchAccessContext:
            state = controller.state
            return LaunchAccessContext(
                authenticated=(state.auth_status == AuthStatus.AUTHENTICATED),
                entitlement_active=(
                    state.entitlement is not None
                    and state.entitlement.status == EntitlementStatus.ACTIVE
                ),
                session_id=state.session_id or "",
                installation_key_hash=installation.key_hash,
                authenticated_transport=gateway,
            )

        def command_provider() -> OpaqueStartCommand:
            # Minimal V1 uses a hardcoded profile reference
            return OpaqueStartCommand(
                profile_reference="profile-0",
                server_reference="server-0",
            )

        proxy_manager = AuthorizedProxyGateway(
            orchestrator=orchestrator,
            access_context_provider=access_context_provider,
            command_provider=command_provider,
        )
    else:
        proxy_manager = create_production_proxy_gateway()

    controller = ApplicationController(event_bus, proxy_manager, game_manager)
    service = LauncherService(
        controller,
        gateway,
        gateway,
        installation,
        config.product_code,
    )
    logo_path = root / "image_11.png"
    icon_path = root / "icon_app.ico"
    return AppWindow(
        controller,
        service,
        event_bus,
        logo_path,
        icon_path,
        game_default_path=config.game_exe,
        game_path_store=config.game_path_store,
    )


def main() -> None:
    mutex_handle = _acquire_instance_mutex()
    if mutex_handle is None:
        _show_already_running_message()
        return
    exit_code = 0
    try:
        build_window().root.mainloop()
    except Exception as exc:
        exit_code = 1
        _report_startup_error(exc)
    finally:
        _release_instance_mutex(mutex_handle)
        # Force terminate immediately after mainloop finishes to prevent
        # lingering threads (such as network polling) from keeping the
        # process alive in the background and leaving a zombie process.
        os._exit(exit_code)


def _acquire_instance_mutex(name: str = _INSTANCE_MUTEX_NAME) -> int | None:
    """Hold a named Windows mutex for the lifetime of the launcher."""
    if sys.platform != "win32":
        return -1
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def _release_instance_mutex(handle: int) -> None:
    if sys.platform == "win32" and handle != -1:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        kernel32.CloseHandle(handle)


def _show_already_running_message() -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(
            None,
            "Neko Launcher เปิดอยู่แล้ว กรุณาใช้หน้าต่างเดิม",
            "Neko Launcher",
            0x40,
        )


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
