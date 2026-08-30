from __future__ import annotations

import sys
from pathlib import Path

from neko_launcher.application.authorized_core import (
    AuthorizedCoreOrchestrator,
    LaunchAccessContext,
    OnlineHeartbeatLaunchPrecondition,
    OrchestrationTimeouts,
)
from neko_launcher.application.controller import ApplicationController
from neko_launcher.application.production_authorization import (
    CURRENT_PRODUCTION_AUTHORIZATION,
    create_production_proxy_gateway,
)
from neko_launcher.application.services import LauncherService
from neko_launcher.domain.models import AuthStatus, EntitlementStatus
from neko_launcher.infrastructure.account_recovery_gateway import (
    HttpAccountRecoveryGateway,
)
from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway
from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.infrastructure.core.authorized_proxy_gateway import AuthorizedProxyGateway
from neko_launcher.infrastructure.core.core_control_channel import NamedPipeCoreControlChannel
from neko_launcher.infrastructure.core.core_process import WindowsCoreProcessAdapter
from neko_launcher.infrastructure.core.core_telemetry_client import NamedPipeCoreTelemetryClient
from neko_launcher.infrastructure.event_bus import EventBus
from neko_launcher.infrastructure.process.game_process_manager import GameProcessManager
from neko_launcher.infrastructure.proxy_status_client import PublicProxyStatusClient
from neko_launcher.infrastructure.process.process_detector import ExactPso2TargetDetector
from neko_launcher.infrastructure.storage.installation import LocalInstallationIdentity
from neko_launcher.infrastructure.storage.secure_store import KeyringSecureStore
from neko_launcher.ui.app_window import AppWindow


def application_root() -> Path:
    """Return the source checkout or PyInstaller extraction directory."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[4]


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
    recovery_gateway = HttpAccountRecoveryGateway(config.account_recovery_api_url)
    proxy_status_client = PublicProxyStatusClient(config.proxy_status_api_url)

    from neko_launcher.infrastructure.diagnostics_logger import DevelopmentLogger

    # Support diagnostics are always-on. Debug mode only increases verbosity
    # and exposes the advanced diagnostics UI; it no longer gates log creation.
    diagnostics_sink = DevelopmentLogger(
        config.debug_log_dir,
        verbose=config.debug_mode,
    )
    diagnostics_sink.log_session_header(
        core_path=str(config.proxy_core_path),
        workspace_root=str(root),
    )

    from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder

    diagnostics_recorder = CoreDiagnosticsRecorder(diagnostics_sink)

    if CURRENT_PRODUCTION_AUTHORIZATION.is_ready:
        core_process = WindowsCoreProcessAdapter(
            config.proxy_core_path,
            diagnostics=diagnostics_recorder,
            debug_log_dir=config.debug_log_dir if config.debug_mode else None,
        )
        core_channel = NamedPipeCoreControlChannel(
            "NekoProxyCoreControl",
            expected_server_pid=core_process.owned_process_id,
        )
        detector = ExactPso2TargetDetector()
        precondition = OnlineHeartbeatLaunchPrecondition(
            lambda session_id, _installation_key_hash, timeout: (
                gateway.heartbeat_session_with_timeout(session_id, timeout)
            )
        )
        timeouts = OrchestrationTimeouts(
            target=30.0,
            control_channel=10.0,
            challenge=5.0,
            permit=10.0,
            # Launcher bounds include scheduling/transport margin beyond the
            # frozen Core's 30-second START and 15-second STOP contracts.
            start_response=40.0,
            stop_response=20.0,
            shutdown_response=20.0,
            process_exit=10.0,
        )
        orchestrator = AuthorizedCoreOrchestrator(
            process=core_process,
            channel=core_channel,
            permits=gateway,
            precondition=precondition,
            detector=detector,
            timeouts=timeouts,
            diagnostics=diagnostics_recorder,
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

        proxy_manager = AuthorizedProxyGateway(
            orchestrator=orchestrator,
            access_context_provider=access_context_provider,
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
        recovery_gateway=recovery_gateway,
    )
    telemetry_client = NamedPipeCoreTelemetryClient(event_publisher=event_bus)
    # Resolve the project Asset directory relative to application_root().
    # In source mode root is the repo root and Asset is a direct child.
    # In frozen mode (PyInstaller) root is sys._MEIPASS; the spec ships
    # setting.png flat at "." so it lives at root, not under root/Asset.
    asset_dir = root / "Asset"
    if asset_dir.is_dir():
        logo_path = asset_dir / "logo.png"
        icon_path = asset_dir / "icon_app.ico"
        settings_icon_path = asset_dir / "setting.png"
    else:
        logo_path = root / "logo.png"
        icon_path = root / "icon_app.ico"
        settings_icon_path = root / "setting.png"

    return AppWindow(
        controller,
        service,
        event_bus,
        logo_path=logo_path,
        icon_path=icon_path,
        settings_icon_path=settings_icon_path,
        game_default_path=config.game_exe,
        game_path_store=config.game_path_store,
        diagnostics=diagnostics_recorder,
        debug_mode=config.debug_mode,
        debug_log_dir=config.debug_log_dir,
        telemetry_client=telemetry_client,
        proxy_status_client=proxy_status_client,
    )
