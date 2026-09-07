"""Deterministic crash-recovery engine and recovery dispatcher."""
from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.precommit_abort import execute_precommit_abort
from neko_launcher.updater.rollback_controller import initiate_postcommit_rollback
from neko_launcher.updater.slot_selector import SelectionStatus, select_active_slot
from neko_launcher.updater.state_models import (
    Generation,
    State,
    serialize_state,
)
from neko_launcher.updater.win32_directory import get_directory_identity, open_directory_guarded


@dataclass(frozen=True)
class RecoveryResult:
    converged: bool
    status: str
    selected_generation: Generation | None
    mutations_performed: int
    final_state: State | None
    error: str | None = None


class RecoveryEngine:
    """Manages crash recovery, fault resolution, and scratch cleanup."""

    def __init__(
        self,
        root_dir: Path,
        public_keys: Mapping[str, bytes],
    ) -> None:
        self.root_dir = root_dir
        self.state_dir = root_dir / "state"
        self.public_keys = public_keys

    def _read_slot_bytes(self, filename: str) -> bytes | None:
        p = self.state_dir / filename
        if not p.is_file():
            return None
        try:
            return p.read_bytes()
        except OSError:
            return None

    def _write_next_slot(self, new_state: State, current_active_slot: str | None) -> str:
        target_slot = "b" if current_active_slot == "a" else "a"
        target_path = self.state_dir / f"slot-{target_slot}.bin"
        body = serialize_state(new_state)
        frame = SlotFrame(revision=new_state.revision, format_version=1, body_bytes=body)
        packed = pack_slot_frame(frame)
        fd = os.open(target_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0))
        try:
            os.write(fd, packed)
            os.fsync(fd)
        finally:
            os.close(fd)
        return target_slot

    def run_recovery(self) -> RecoveryResult:
        """Execute crash recovery to converge installation to OLD_FULLY_RESTORED or NEW_FULLY_COMMITTED."""
        mutations = 0

        while True:
            slot_a = self._read_slot_bytes("slot-a.bin")
            slot_b = self._read_slot_bytes("slot-b.bin")
            selection = select_active_slot(slot_a, slot_b, self.public_keys)

            if selection.status == SelectionStatus.REPAIR_REQUIRED:
                return RecoveryResult(
                    converged=False,
                    status="REPAIR_REQUIRED",
                    selected_generation=None,
                    mutations_performed=mutations,
                    final_state=None,
                    error=selection.reason,
                )

            if selection.status == SelectionStatus.ENROLLMENT_INCOMPLETE:
                return RecoveryResult(
                    converged=False,
                    status="ENROLLMENT_INCOMPLETE",
                    selected_generation=None,
                    mutations_performed=mutations,
                    final_state=None,
                    error="Enrollment incomplete",
                )

            state = selection.state
            active_slot = selection.active_slot
            assert state is not None

            if state.phase == "IDLE":
                if state.committed is not None:
                    rel_dir = (
                        self.root_dir
                        / "releases"
                        / f"g-{state.committed.binding.release_sequence:020d}-{state.committed.binding.payload_sha256}"
                    )
                    if not rel_dir.exists():
                        if state.previous is not None:
                            rb_state = initiate_postcommit_rollback(state, "CORRUPT_COMMITTED")
                            active_slot = self._write_next_slot(rb_state, active_slot)
                            mutations += 1
                            continue
                        return RecoveryResult(
                            converged=False,
                            status="REPAIR_REQUIRED",
                            selected_generation=None,
                            mutations_performed=mutations,
                            final_state=state,
                            error="Committed generation missing on disk and no previous available",
                        )

                return RecoveryResult(
                    converged=True,
                    status="OLD_FULLY_RESTORED",
                    selected_generation=state.committed,
                    mutations_performed=mutations,
                    final_state=state,
                    error=None,
                )

            elif state.phase == "PREPARING":
                # Pre-quiesce abort preserves running old family
                next_state = execute_precommit_abort(state, "RECOVERY_ABORT")
                active_slot = self._write_next_slot(next_state, active_slot)
                mutations += 1
                continue

            elif state.phase == "CLEANING":
                # Process cleanup queue
                if state.cleanup:
                    for item in state.cleanup:
                        container_path = self.root_dir / item.target / item.request_id if item.target == "incoming" else self.root_dir / "staging" / item.transaction_id
                        if container_path.exists():
                            try:
                                h = open_directory_guarded(container_path)
                                actual_id = get_directory_identity(h)
                                import ctypes
                                ctypes.windll.kernel32.CloseHandle(h)
                                if (
                                    actual_id.volume_serial == item.directory.volume_serial
                                    and actual_id.file_id == item.directory.file_id
                                ):
                                    shutil.rmtree(container_path, ignore_errors=True)
                            except Exception:  # noqa: BLE001, S110
                                pass

                next_state = State(
                    schema_version=1,
                    revision=state.revision + 1,
                    installation_id=state.installation_id,
                    helper_protocol=state.helper_protocol,
                    enrollment_complete=state.enrollment_complete,
                    phase="IDLE",
                    committed=state.committed,
                    previous=state.previous,
                    highwater=state.highwater,
                    observed=state.observed,
                    failed=state.failed,
                    transaction=None,
                    cleanup=None,
                    rollback=None,
                    last_error=state.last_error,
                    evidence=state.evidence,
                )
                active_slot = self._write_next_slot(next_state, active_slot)
                mutations += 1
                continue

            elif state.phase in ("QUIESCING", "PROBATION"):
                # Record rollback before restoring the committed generation.
                from neko_launcher.updater.state_models import Rollback

                target = state.committed
                if target is None:
                    return RecoveryResult(
                        converged=False,
                        status="REPAIR_REQUIRED",
                        selected_generation=None,
                        mutations_performed=mutations,
                        final_state=state,
                        error="Interrupted mutation has no committed rollback target",
                    )
                rollback_state = State(
                    schema_version=1,
                    revision=state.revision + 1,
                    installation_id=state.installation_id,
                    helper_protocol=state.helper_protocol,
                    enrollment_complete=state.enrollment_complete,
                    phase="ROLLING_BACK",
                    committed=state.committed,
                    previous=state.previous,
                    highwater=state.highwater,
                    observed=state.observed,
                    failed=state.observed,
                    transaction=None,
                    cleanup=None,
                    rollback=Rollback(
                        mode="precommit",
                        target=target,
                        probation_id=(state.transaction.id if state.transaction else "0" * 32),
                        scratch=[],
                        step="RESTORE_INTENT",
                    ),
                    last_error="RECOVERY_ROLLBACK",
                    evidence=state.evidence,
                )
                active_slot = self._write_next_slot(rollback_state, active_slot)
                mutations += 1
                continue

            elif state.phase == "ROLLING_BACK":
                # Complete rollback
                target = state.rollback.target if state.rollback else state.committed
                prev = None if (state.rollback and state.rollback.mode == "postcommit") else state.previous
                next_state = State(
                    schema_version=1,
                    revision=state.revision + 1,
                    installation_id=state.installation_id,
                    helper_protocol=state.helper_protocol,
                    enrollment_complete=state.enrollment_complete,
                    phase="IDLE",
                    committed=target,
                    previous=prev,
                    highwater=state.highwater,
                    observed=state.observed,
                    failed=state.failed,
                    transaction=None,
                    cleanup=None,
                    rollback=None,
                    last_error=state.last_error,
                    evidence=state.evidence,
                )
                active_slot = self._write_next_slot(next_state, active_slot)
                mutations += 1
                continue

            else:
                return RecoveryResult(
                    converged=False,
                    status="UNKNOWN_PHASE",
                    selected_generation=None,
                    mutations_performed=mutations,
                    final_state=state,
                    error=f"Unhandled phase: {state.phase}",
                )
