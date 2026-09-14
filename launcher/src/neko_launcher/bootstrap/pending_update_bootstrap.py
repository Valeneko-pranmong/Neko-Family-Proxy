from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path

from neko_launcher.application.software_update_models import LocalReleaseIdentity
from neko_launcher.infrastructure.software_update_apply import (
    SoftwareUpdateApplyService,
)
from neko_launcher.infrastructure.authenticated_release_identity import (
    AuthenticatedReleaseIdentityReader,
)
from neko_launcher.infrastructure.software_update_pending_store import (
    PendingUpdateStore,
)
from neko_launcher.updater.trust_profile import (
    VerifiedUpdateTrustProfile,
    load_installed_update_trust_profile,
)


class PendingUpdateBootstrapResult(str, Enum):
    NONE = "none"
    DEFERRED = "deferred"
    HANDOFF_STARTED = "handoff_started"


def try_apply_pending_on_launch(
    *,
    pending_store: PendingUpdateStore,
    apply_service: SoftwareUpdateApplyService,
    game_active: Callable[[], bool],
    local_identity_provider: Callable[[], LocalReleaseIdentity],
) -> PendingUpdateBootstrapResult:
    """Evaluate and attempt to hand off a verified staged update at early launch.

    Executed after single-instance mutex acquisition but before ordinary UI
    construction. Requires no network access.
    - Safe/no-game + valid pending update -> hand off to updater helper.
    - Active game -> defer and preserve pending update.
    - Stale pending update (already-current or older) -> clear record safely and open normally.
    - Tampered/invalid pending update -> reject and open normally.
    - Apply preparation failure -> fail closed, preserve pending update, and open normally.
    """
    try:
        local_identity = local_identity_provider()
    except Exception:
        return PendingUpdateBootstrapResult.NONE

    # Safely clear stale pending record if local installation already has equal
    # or higher release sequence.
    if hasattr(pending_store, "clear_if_stale"):
        try:
            pending_store.clear_if_stale(local_identity)
        except Exception:
            pass
    else:
        read_ptr = getattr(pending_store, "_read_active_pointer", None)
        if callable(read_ptr):
            try:
                ptr = read_ptr()
                if (
                    ptr
                    and isinstance(ptr.get("release_sequence"), int)
                    and isinstance(ptr.get("release_id"), str)
                ):
                    if ptr["release_sequence"] <= local_identity.release_sequence:
                        pending_store.clear(ptr["release_id"], ptr["release_sequence"])
            except Exception:
                pass

    try:
        pending = pending_store.load_verified(local_identity)
    except Exception:
        return PendingUpdateBootstrapResult.NONE

    if pending is None:
        return PendingUpdateBootstrapResult.NONE

    try:
        if game_active():
            return PendingUpdateBootstrapResult.DEFERRED
    except Exception:
        # Observation failure must fail closed to protect any running game session.
        return PendingUpdateBootstrapResult.DEFERRED

    try:
        prepared = apply_service.prepare_pending(pending)
        if prepared is not None and hasattr(prepared, "release"):
            prepared.release()
        return PendingUpdateBootstrapResult.HANDOFF_STARTED
    except Exception:
        # Fail closed on apply error: preserve pending update for subsequent launch or user UI.
        return PendingUpdateBootstrapResult.DEFERRED


def is_game_active_early() -> bool:
    """Check if game process is active during early startup without UI."""
    from neko_launcher.infrastructure.process.process_detector import (
        ExactPso2TargetDetector,
        is_any_process_running,
    )

    try:
        if ExactPso2TargetDetector().observe_exact_pso2() is not None:
            return True
        return bool(is_any_process_running())
    except Exception:
        return False


def run_pending_update_bootstrap(
    workspace_root: Path | None = None,
    *,
    game_active: Callable[[], bool] | None = None,
    verified_profile: VerifiedUpdateTrustProfile | None = None,
    identity_reader: AuthenticatedReleaseIdentityReader | None = None,
    root_dir: Path | None = None,
) -> PendingUpdateBootstrapResult:
    """Compose dependencies and evaluate pending update apply before constructing UI."""
    try:
        from neko_launcher.bootstrap.app_factory import (
            application_root,
            compose_update_apply_service,
        )
        from neko_launcher.infrastructure.config import LauncherConfig
        from neko_launcher.infrastructure.software_update_pending_store import (
            PendingUpdateStore,
        )
        from neko_launcher.updater.manifest_v2 import UPDATER_PROTOCOL_VERSION
        from neko_launcher.updater.root_validator import get_expected_install_root

        root = workspace_root or application_root()
        config = LauncherConfig.from_environment(root)
        install_root = root_dir or (Path(workspace_root) if workspace_root is not None else get_expected_install_root())

        profile = verified_profile
        if profile is None:
            reader_prof = getattr(identity_reader, "trust_profile", getattr(identity_reader, "_trust_profile", None))
            if reader_prof is not None:
                profile = reader_prof
            else:
                profile = load_installed_update_trust_profile(install_root)

        if identity_reader is None:
            reader = AuthenticatedReleaseIdentityReader(profile)
        else:
            reader = identity_reader

        if profile is None:
            return PendingUpdateBootstrapResult.NONE

        pending_store = PendingUpdateStore(
            root_dir=install_root,
            key_registry=profile.release_public_keys,
            updater_protocol=UPDATER_PROTOCOL_VERSION,
        )

        apply_service = compose_update_apply_service(
            config,
            verified_profile=profile,
            root_dir=install_root,
        )

        def identity_provider() -> LocalReleaseIdentity:
            return reader.read(install_root)

        checker = game_active or is_game_active_early

        return try_apply_pending_on_launch(
            pending_store=pending_store,
            apply_service=apply_service,
            game_active=checker,
            local_identity_provider=identity_provider,
        )
    except Exception:
        return PendingUpdateBootstrapResult.NONE
