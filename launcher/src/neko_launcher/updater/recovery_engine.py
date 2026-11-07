"""Deterministic crash-recovery engine and recovery dispatcher."""
from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.precommit_abort import execute_precommit_abort
from neko_launcher.updater.rollback_controller import initiate_postcommit_rollback
from neko_launcher.updater.slot_selector import SelectionStatus, select_active_slot
from neko_launcher.updater.state_machine import validate_transition
from neko_launcher.updater.state_models import (
    Generation,
    State,
    prune_unreferenced_evidence,
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

    def complete_committed_cleanup(
        self, expected_committed: Generation, expected_installation_id: str
    ) -> RecoveryResult:
        selection = select_active_slot(
            self._read_slot_bytes("slot-a.bin"),
            self._read_slot_bytes("slot-b.bin"),
            self.public_keys,
        )
        if selection.status != SelectionStatus.SELECTED or selection.state is None:
            return RecoveryResult(False, "REPAIR_REQUIRED", None, 0, None, selection.reason)
        state = selection.state
        if state.phase != "CLEANING":
            return RecoveryResult(False, "REPAIR_REQUIRED", state.committed, 0, state, "LOCK_BUSY")
        if state.installation_id != expected_installation_id or state.committed != expected_committed:
            return RecoveryResult(False, "REPAIR_REQUIRED", state.committed, 0, state, "STATE_CHANGED")

        generation_dir = self.root_dir / "releases" / (
            f"g-{expected_committed.binding.release_sequence:020d}-{expected_committed.binding.payload_sha256}"
        )
        try:
            generation_handle = open_directory_guarded(generation_dir)
        except OSError:
            return RecoveryResult(False, "REPAIR_REQUIRED", state.committed, 0, state, "COMMITTED_STORAGE_MISSING")
        try:
            launcher = generation_dir / "NekoLauncher.exe"
            core_manifest = generation_dir / "ProxyCore" / "core-manifest.json"
            if not core_manifest.is_file():
                core_manifest = generation_dir / "ProxyCore" / "canonical-core-manifest.json"
            if not launcher.is_file() or not core_manifest.is_file():
                return RecoveryResult(False, "REPAIR_REQUIRED", state.committed, 0, state, "COMMITTED_STORAGE_MISSING")
            with launcher.open("rb") as stream:
                launcher_sha = hashlib.file_digest(stream, "sha256").hexdigest()
            with core_manifest.open("rb") as stream:
                core_sha = hashlib.file_digest(stream, "sha256").hexdigest()
            if launcher_sha != expected_committed.launcher_identity_sha256 or core_sha != expected_committed.core_identity_sha256:
                return RecoveryResult(False, "REPAIR_REQUIRED", state.committed, 0, state, "COMMITTED_STORAGE_MISMATCH")

            for item in state.cleanup or []:
                path = self.root_dir / item.target / (
                    item.request_id if item.target == "incoming" else item.transaction_id
                )
                if not path.exists():
                    continue
                handle = open_directory_guarded(path)
                try:
                    identity = get_directory_identity(handle)
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
                if identity != item.directory:
                    return RecoveryResult(False, "REPAIR_REQUIRED", state.committed, 0, state, "DIRECTORY_IDENTITY_MISMATCH")
                shutil.rmtree(path)

            next_state = replace(
                state, revision=state.revision + 1, phase="IDLE", cleanup=None,
                transaction=None, rollback=None,
            )
            validate_transition(state, next_state)
            self._write_next_slot(next_state, selection.active_slot)
            final = select_active_slot(
                self._read_slot_bytes("slot-a.bin"), self._read_slot_bytes("slot-b.bin"), self.public_keys
            )
            if final.status != SelectionStatus.SELECTED or final.state != next_state:
                return RecoveryResult(False, "REPAIR_REQUIRED", state.committed, 1, final.state, "STATE_CHANGED")
            return RecoveryResult(True, "NEW_FULLY_COMMITTED", expected_committed, 1, next_state)
        finally:
            ctypes.windll.kernel32.CloseHandle(generation_handle)

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
                next_state = prune_unreferenced_evidence(next_state)
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
                rollback_state = prune_unreferenced_evidence(rollback_state)
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
                next_state = prune_unreferenced_evidence(next_state)
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
