from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from neko_launcher.application.software_update_models import (
    LocalReleaseIdentity,
    UpdateCheckResult,
    UpdateState,
)
from neko_launcher.application.software_update_pending import (
    UpdateLifecycleState,
    VerifiedPendingUpdate,
)
from neko_launcher.infrastructure.software_update_stage import (
    SoftwareUpdateStageError,
)

if TYPE_CHECKING:
    from neko_launcher.application.software_update_service import UpdateCheckService
    from neko_launcher.infrastructure.github_release_binding import (
        ResolvedGitHubRelease,
    )
    from neko_launcher.infrastructure.software_update_pending_store import (
        PendingUpdateStore,
    )
    from neko_launcher.infrastructure.software_update_stage import (
        SoftwareUpdateStageService,
    )

__all__ = [
    "SoftwareUpdateCoordinator",
    "UpdateLifecycleSnapshot",
]


@dataclass(frozen=True)
class UpdateLifecycleSnapshot:
    state: UpdateLifecycleState
    check_result: UpdateCheckResult | None
    pending: VerifiedPendingUpdate | None
    diagnostic_code: str | None


class SoftwareUpdateCoordinator:
    def __init__(
        self,
        check_service: UpdateCheckService,
        stage_service: SoftwareUpdateStageService,
        pending_store: PendingUpdateStore | None = None,
        local_identity_provider: Callable[[], LocalReleaseIdentity] | None = None,
    ) -> None:
        self._check_service = check_service
        self._stage_service = stage_service
        self._pending_store = pending_store or getattr(
            stage_service, "_pending_store", None
        )
        if self._pending_store is None:
            raise ValueError("pending_store is required")

        self._local_identity_provider = local_identity_provider or getattr(
            check_service, "_local_identity_provider", None
        )
        if self._local_identity_provider is None:
            raise ValueError("local_identity_provider is required")

        self._lock = threading.Lock()
        self._startup_condition = threading.Condition(self._lock)
        self._startup_checking: bool = False
        self._startup_done: bool = False
        self._startup_snapshot: UpdateLifecycleSnapshot | None = None
        self._current_snapshot: UpdateLifecycleSnapshot | None = None
        self._startup_callbacks: list[
            Callable[[UpdateLifecycleSnapshot], None]
        ] = []
        self._operation_lock = threading.Lock()

    def current(self) -> UpdateLifecycleSnapshot:
        with self._lock:
            if self._current_snapshot is not None:
                return self._current_snapshot

        local = self._safe_get_local_identity()
        pending = (
            self._safe_load_verified(local) if local is not None else None
        )
        state = (
            UpdateLifecycleState.UPDATE_PENDING
            if pending is not None
            else UpdateLifecycleState.IDLE
        )
        snapshot = UpdateLifecycleSnapshot(
            state=state,
            check_result=None,
            pending=pending,
            diagnostic_code=None,
        )
        with self._lock:
            if self._current_snapshot is None:
                self._current_snapshot = snapshot
            return self._current_snapshot

    def startup(
        self,
        callback: Callable[[UpdateLifecycleSnapshot], None] | None = None,
    ) -> UpdateLifecycleSnapshot:
        with self._lock:
            if callback is not None:
                self._startup_callbacks.append(callback)
            if self._startup_done:
                snapshot = self._startup_snapshot
                assert snapshot is not None
                if callback is not None:
                    self._invoke_callback_safe(callback, snapshot)
                return snapshot
            if self._startup_checking:
                while self._startup_checking:
                    self._startup_condition.wait()
                assert self._startup_snapshot is not None
                return self._startup_snapshot
            self._startup_checking = True

        snapshot: UpdateLifecycleSnapshot | None = None
        try:
            with self._operation_lock:
                snapshot, _ = self._run_startup()
        except Exception:
            local = self._safe_get_local_identity()
            pending = (
                self._safe_load_verified(local) if local is not None else None
            )
            state = (
                UpdateLifecycleState.UPDATE_PENDING
                if pending is not None
                else UpdateLifecycleState.IDLE
            )
            snapshot = UpdateLifecycleSnapshot(
                state=state,
                check_result=None,
                pending=pending,
                diagnostic_code="UPDATE_CHECK_INTERNAL_FAILURE",
            )
        finally:
            with self._lock:
                self._startup_snapshot = snapshot
                self._current_snapshot = snapshot
                self._startup_done = True
                self._startup_checking = False
                callbacks = list(self._startup_callbacks)
                self._startup_callbacks.clear()
                self._startup_condition.notify_all()

            for cb in callbacks:
                self._invoke_callback_safe(cb, snapshot)

        return snapshot

    def manual_check(
        self,
        callback: Callable[[UpdateLifecycleSnapshot], None] | None = None,
    ) -> UpdateLifecycleSnapshot:
        snapshot: UpdateLifecycleSnapshot
        try:
            with self._operation_lock:
                snapshot = self._run_manual_check()
        except Exception:
            local = self._safe_get_local_identity()
            pending = (
                self._safe_load_verified(local) if local is not None else None
            )
            state = (
                UpdateLifecycleState.UPDATE_PENDING
                if pending is not None
                else UpdateLifecycleState.IDLE
            )
            snapshot = UpdateLifecycleSnapshot(
                state=state,
                check_result=None,
                pending=pending,
                diagnostic_code="UPDATE_CHECK_INTERNAL_FAILURE",
            )

        with self._lock:
            self._current_snapshot = snapshot

        if callback is not None:
            self._invoke_callback_safe(callback, snapshot)

        return snapshot

    def _run_startup(
        self,
    ) -> tuple[UpdateLifecycleSnapshot, VerifiedPendingUpdate | None]:
        local = self._local_identity_provider()
        pending = self._safe_load_verified(local)
        try:
            self._pending_store.cleanup_incomplete()
        except Exception:
            pass

        with self._lock:
            self._current_snapshot = UpdateLifecycleSnapshot(
                state=(
                    UpdateLifecycleState.UPDATE_PENDING
                    if pending is not None
                    else UpdateLifecycleState.IDLE
                ),
                check_result=None,
                pending=pending,
                diagnostic_code=None,
            )

        check_result, resolved = (
            self._check_service.check_startup_with_resolved()
        )
        return self._handle_check_and_stage(
            local=local,
            existing_pending=pending,
            check_result=check_result,
            resolved=resolved,
        )

    def _run_manual_check(
        self,
    ) -> UpdateLifecycleSnapshot:
        local = self._local_identity_provider()
        pending = self._safe_load_verified(local)

        check_result, resolved = (
            self._check_service.check_manual_with_resolved()
        )
        snapshot, _ = self._handle_check_and_stage(
            local=local,
            existing_pending=pending,
            check_result=check_result,
            resolved=resolved,
        )
        return snapshot

    def _handle_check_and_stage(
        self,
        *,
        local: LocalReleaseIdentity,
        existing_pending: VerifiedPendingUpdate | None,
        check_result: UpdateCheckResult,
        resolved: ResolvedGitHubRelease | None,
    ) -> tuple[UpdateLifecycleSnapshot, VerifiedPendingUpdate | None]:
        pending = existing_pending

        if check_result.diagnostic_code is not None or check_result.state in (
            UpdateState.UNAVAILABLE,
            UpdateState.VERIFY_FAILED,
        ):
            diag_code = (
                check_result.diagnostic_code.value
                if hasattr(check_result.diagnostic_code, "value")
                else (
                    str(check_result.diagnostic_code)
                    if check_result.diagnostic_code is not None
                    else "UPDATE_CHECK_INTERNAL_FAILURE"
                )
            )
            state = (
                UpdateLifecycleState.UPDATE_PENDING
                if pending is not None
                else UpdateLifecycleState.IDLE
            )
            return (
                UpdateLifecycleSnapshot(
                    state=state,
                    check_result=check_result,
                    pending=pending,
                    diagnostic_code=diag_code,
                ),
                pending,
            )

        if check_result.state == UpdateState.LATEST:
            state = (
                UpdateLifecycleState.UPDATE_PENDING
                if pending is not None
                else UpdateLifecycleState.IDLE
            )
            return (
                UpdateLifecycleSnapshot(
                    state=state,
                    check_result=check_result,
                    pending=pending,
                    diagnostic_code=None,
                ),
                pending,
            )

        if (
            check_result.state in (UpdateState.AVAILABLE, UpdateState.MANDATORY)
            and resolved is not None
        ):
            with self._lock:
                self._current_snapshot = UpdateLifecycleSnapshot(
                    state=UpdateLifecycleState.STAGING,
                    check_result=check_result,
                    pending=pending,
                    diagnostic_code=None,
                )

            diag_code: str | None = None
            try:
                staged = self._stage_service.stage(resolved, local)
                if staged is not None:
                    pending = staged
            except SoftwareUpdateStageError as err:
                diag_code = err.code
            except Exception:
                diag_code = "STAGE_FAILED"

            state = (
                UpdateLifecycleState.UPDATE_PENDING
                if pending is not None
                else UpdateLifecycleState.IDLE
            )
            return (
                UpdateLifecycleSnapshot(
                    state=state,
                    check_result=check_result,
                    pending=pending,
                    diagnostic_code=diag_code,
                ),
                pending,
            )

        state = (
            UpdateLifecycleState.UPDATE_PENDING
            if pending is not None
            else UpdateLifecycleState.IDLE
        )
        return (
            UpdateLifecycleSnapshot(
                state=state,
                check_result=check_result,
                pending=pending,
                diagnostic_code=None,
            ),
            pending,
        )

    def _safe_get_local_identity(self) -> LocalReleaseIdentity | None:
        try:
            return self._local_identity_provider()
        except Exception:
            return None

    def _safe_load_verified(
        self,
        local: LocalReleaseIdentity | None,
    ) -> VerifiedPendingUpdate | None:
        if local is None:
            return None
        try:
            return self._pending_store.load_verified(local)
        except Exception:
            return None

    @staticmethod
    def _invoke_callback_safe(
        callback: Callable[[UpdateLifecycleSnapshot], None],
        snapshot: UpdateLifecycleSnapshot,
    ) -> None:
        try:
            callback(snapshot)
        except Exception:
            pass
