from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from neko_launcher import __version__
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
from neko_launcher.application.software_update_coordinator import (
    SoftwareUpdateCoordinator,
)
from neko_launcher.application.software_update_service import UpdateCheckService
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
from neko_launcher.application.software_update_models import (
    DevelopmentReleaseIdentity,
    LocalReleaseIdentity,
)
from neko_launcher.infrastructure.authenticated_release_identity import (
    AuthenticatedReleaseIdentityReader,
)
from neko_launcher.infrastructure.event_bus import EventBus
from neko_launcher.infrastructure.github_asset_downloader import (
    GitHubAssetDownloader,
    GitHubManifestDownloader,
)
from neko_launcher.infrastructure.github_release import GitHubLatestReleaseGateway
from neko_launcher.infrastructure.github_release_binding import (
    AuthenticatedReleaseGateway,
    GitHubReleaseResolver,
    GitHubReleaseResolverError,
)

from neko_launcher.infrastructure.process.game_process_manager import GameProcessManager
from neko_launcher.infrastructure.proxy_status_client import PublicProxyStatusClient
from neko_launcher.infrastructure.software_release_identity import (
    load_development_release_identity,
)
from neko_launcher.infrastructure.software_update_apply import SoftwareUpdateApplyService
from neko_launcher.infrastructure.software_update_pending_store import (
    PendingUpdateStore,
)
from neko_launcher.infrastructure.software_update_stage import (
    SoftwareUpdateStageService,
)
from neko_launcher.infrastructure.process.process_detector import ExactPso2TargetDetector
from neko_launcher.infrastructure.update_channel_profile import (
    UpdateChannelProfile,
)
from neko_launcher.updater.manifest_v2 import UPDATER_PROTOCOL_VERSION
from neko_launcher.updater.root_validator import get_expected_install_root
from neko_launcher.updater.trust_profile import (
    VerifiedUpdateTrustProfile,
    load_installed_update_trust_profile,
)
from neko_launcher.infrastructure.storage.installation import BoundInstallationIdentity
from neko_launcher.infrastructure.storage.secure_store import KeyringSecureStore
from neko_launcher.infrastructure.installation_credential import (
    create_installation_credential_provider,
)
from neko_launcher.ui.app_window import AppWindow


class _UnavailableReleaseGateway:
    def resolve(self) -> None:
        raise GitHubReleaseResolverError("GITHUB_RELEASE_UNAVAILABLE")


def _unavailable_local_identity() -> LocalReleaseIdentity:
    raise RuntimeError("Installed update trust profile unavailable")


def _profiles_match(profile_a: Any, profile_b: Any) -> bool:
    if profile_a is profile_b:
        return True
    try:
        if profile_a.profile_id != profile_b.profile_id:
            return False
        if profile_a.channel != profile_b.channel:
            return False
        if profile_a.owner != profile_b.owner:
            return False
        if profile_a.repository != profile_b.repository:
            return False
        if dict(profile_a.release_public_keys) != dict(profile_b.release_public_keys):
            return False
        return True
    except AttributeError:
        return False


def application_root() -> Path:
    """Return the source checkout or PyInstaller extraction directory."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[4]


def compose_update_check_service(
    config: LauncherConfig,
    *,
    verified_profile: VerifiedUpdateTrustProfile | None = None,
    resolver: AuthenticatedReleaseGateway | None = None,
    root_dir: Path | None = None,
    identity_reader: AuthenticatedReleaseIdentityReader | None = None,
) -> UpdateCheckService:
    install_root = root_dir or get_expected_install_root()

    profile = verified_profile
    if profile is None:
        reader_prof = getattr(
            identity_reader, "trust_profile", getattr(identity_reader, "_trust_profile", None)
        )
        if reader_prof is not None:
            profile = reader_prof
        else:
            try:
                profile = load_installed_update_trust_profile(install_root)
            except Exception:
                return UpdateCheckService(
                    resolver or _UnavailableReleaseGateway(),
                    _unavailable_local_identity,
                )

    if not isinstance(profile, VerifiedUpdateTrustProfile):
        raise TypeError("verified_profile must be a VerifiedUpdateTrustProfile")

    if identity_reader is not None:
        reader_prof = getattr(
            identity_reader, "trust_profile", getattr(identity_reader, "_trust_profile", None)
        )
        if reader_prof is not None and not _profiles_match(reader_prof, profile):
            raise ValueError(
                f"Trust profile mismatch between verified profile and identity reader: {reader_prof} != {profile}"
            )

    if resolver is None:
        channel_profile = UpdateChannelProfile.from_verified(profile)
        release_resolver: AuthenticatedReleaseGateway = GitHubReleaseResolver(
            release_gateway=GitHubLatestReleaseGateway(channel_profile=channel_profile),
            manifest_downloader=GitHubManifestDownloader(channel_profile=channel_profile),
            channel_profile=channel_profile,
            install_root=install_root,
            updater_protocol=UPDATER_PROTOCOL_VERSION,
        )
    else:
        resolver_prof = getattr(
            resolver, "channel_profile", getattr(resolver, "_channel_profile", None)
        )
        if resolver_prof is not None and not _profiles_match(resolver_prof, profile):
            raise ValueError(
                f"Trust profile mismatch between gateway and profile/identity reader: {resolver_prof} != {profile}"
            )
        release_resolver = resolver

    if identity_reader is None:
        reader = AuthenticatedReleaseIdentityReader(profile)
    else:
        reader = identity_reader

    def local_identity_provider() -> LocalReleaseIdentity:
        return reader.read(install_root)

    return UpdateCheckService(
        release_resolver,
        local_identity_provider,
    )


def compose_development_update_check_service(
    config: LauncherConfig,
    *,
    resolver: AuthenticatedReleaseGateway | None = None,
    root_dir: Path | None = None,
) -> UpdateCheckService:
    del root_dir
    if resolver is None:
        raise ValueError("resolver must be provided for development update check service")

    launcher_executable = (
        Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__).resolve()
    )
    core_manifest = config.proxy_core_path.with_name("canonical-core-manifest.json")

    def local_identity_provider() -> DevelopmentReleaseIdentity:
        return load_development_release_identity(
            launcher_version=__version__,
            launcher_executable=launcher_executable,
            core_version="dev-unpublished",
            core_manifest=core_manifest,
        )

    return UpdateCheckService(
        resolver,
        local_identity_provider,  # type: ignore[arg-type]
    )


def compose_update_apply_service(
    config: LauncherConfig,
    *,
    verified_profile: VerifiedUpdateTrustProfile | None = None,
    resolver: AuthenticatedReleaseGateway | None = None,
    root_dir: Path | None = None,
    asset_downloader: GitHubAssetDownloader | None = None,
) -> SoftwareUpdateApplyService:
    del verified_profile, resolver, asset_downloader
    install_root = root_dir or get_expected_install_root()
    return SoftwareUpdateApplyService(
        root_dir=install_root,
    )


def compose_update_coordinator(
    config: LauncherConfig,
    *,
    check_service: UpdateCheckService | None = None,
    stage_service: SoftwareUpdateStageService | None = None,
    pending_store: PendingUpdateStore | None = None,
    verified_profile: VerifiedUpdateTrustProfile | None = None,
    resolver: AuthenticatedReleaseGateway | None = None,
    root_dir: Path | None = None,
    asset_downloader: GitHubAssetDownloader | None = None,
    identity_reader: AuthenticatedReleaseIdentityReader | None = None,
    admission_service: Any | None = None,
) -> SoftwareUpdateCoordinator:
    install_root = root_dir or get_expected_install_root()
    shared_downloader = (
        asset_downloader if asset_downloader is not None else GitHubAssetDownloader()
    )
    if verified_profile is None and pending_store is None:
        try:
            verified_profile = load_installed_update_trust_profile(install_root)
        except Exception:
            verified_profile = None

    store = (
        pending_store
        if pending_store is not None
        else PendingUpdateStore(
            root_dir=install_root,
            key_registry=(
                verified_profile.release_public_keys if verified_profile is not None else {}
            ),
            updater_protocol=UPDATER_PROTOCOL_VERSION,
        )
    )
    staging = (
        stage_service
        if stage_service is not None
        else SoftwareUpdateStageService(
            pending_store=store,
            asset_downloader=shared_downloader,
        )
    )
    checking = (
        check_service
        if check_service is not None
        else compose_update_check_service(
            config,
            verified_profile=verified_profile,
            resolver=resolver,
            root_dir=install_root,
            identity_reader=identity_reader,
        )
    )
    from neko_launcher.infrastructure.software_update_authority_admission import (
        SoftwareUpdateAuthorityAdmissionService,
    )

    admission = (
        admission_service
        if admission_service is not None
        else SoftwareUpdateAuthorityAdmissionService(root_dir=install_root)
    )
    return SoftwareUpdateCoordinator(
        check_service=checking,
        stage_service=staging,
        pending_store=store,
        local_identity_provider=checking._local_identity_provider,
        admission_service=admission,
    )


def build_window(workspace_root: Path | None = None) -> AppWindow:
    root = workspace_root or application_root()
    config = LauncherConfig.from_environment(root)
    install_root = get_expected_install_root()
    try:
        verified_profile = load_installed_update_trust_profile(install_root)
        channel_profile = UpdateChannelProfile.from_verified(verified_profile)
    except Exception:
        verified_profile = None
        channel_profile = None

    if channel_profile is not None:
        shared_resolver = GitHubReleaseResolver(
            release_gateway=GitHubLatestReleaseGateway(channel_profile=channel_profile),
            manifest_downloader=GitHubManifestDownloader(channel_profile=channel_profile),
            channel_profile=channel_profile,
            install_root=install_root,
            updater_protocol=UPDATER_PROTOCOL_VERSION,
        )
        shared_downloader = GitHubAssetDownloader(channel_profile=channel_profile)
        pending_store = PendingUpdateStore(
            root_dir=install_root,
            key_registry=dict(channel_profile.release_public_keys),
            updater_protocol=UPDATER_PROTOCOL_VERSION,
        )
    else:
        shared_resolver = _UnavailableReleaseGateway()
        shared_downloader = GitHubAssetDownloader()
        pending_store = PendingUpdateStore(
            root_dir=install_root,
            key_registry={},
            updater_protocol=UPDATER_PROTOCOL_VERSION,
        )

    stage_service = SoftwareUpdateStageService(
        pending_store=pending_store,
        asset_downloader=shared_downloader,
    )
    update_check_service = compose_update_check_service(
        config,
        verified_profile=verified_profile,
        resolver=shared_resolver,
        root_dir=install_root,
    )
    from neko_launcher.infrastructure.software_update_authority_admission import (
        SoftwareUpdateAuthorityAdmissionService,
    )

    admission_service = SoftwareUpdateAuthorityAdmissionService(root_dir=install_root)
    update_coordinator = SoftwareUpdateCoordinator(
        check_service=update_check_service,
        stage_service=stage_service,
        pending_store=pending_store,
        local_identity_provider=update_check_service._local_identity_provider,
        admission_service=admission_service,
    )
    update_apply_service = compose_update_apply_service(
        config,
        root_dir=install_root,
    )
    event_bus = EventBus()
    game_manager = GameProcessManager()
    secure_store = KeyringSecureStore()

    credential_provider = create_installation_credential_provider(install_root)
    # Direct downloaded Launcher without credential fails before login
    credential_provider.load_public_identity()

    installation = BoundInstallationIdentity(credential_provider)
    gateway = SupabaseGateway(
        config.supabase_url,
        config.supabase_publishable_key,
        secure_store,
        credential_provider=credential_provider,
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
        update_check_service=update_check_service,
        update_apply_service=update_apply_service,
        update_coordinator=update_coordinator,
    )
