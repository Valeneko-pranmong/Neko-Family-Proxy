"""Broker staging and download handoff protocol coordinator."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from pathlib import Path
import secrets
from typing import Mapping

from neko_launcher.updater.canonical_json import canonical_json_loads
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from neko_launcher.updater.state_machine import validate_transition
from neko_launcher.updater.state_models import (
    Binding,
    Generation,
    State,
    Transaction,
)
from neko_launcher.updater.win32_directory import create_incoming_container


@dataclass(frozen=True)
class RequestReadyResult:
    accepted: bool
    request_id: str | None = None
    transaction_id: str | None = None
    changed: dict[str, bool] | None = None
    error: str | None = None


@dataclass(frozen=True)
class ApplyResult:
    accepted: bool
    error: str | None = None


def handle_begin_request(
    root_dir: Path,
    current_state: State,
    envelope_b64: str,
    public_keys: Mapping[str, bytes],
) -> tuple[RequestReadyResult, State | None]:
    """Handle BEGIN from Launcher, authenticate envelope, create incoming dir, and formulate next State."""
    if current_state.phase != "IDLE":
        return RequestReadyResult(accepted=False, error="LOCK_BUSY"), None

    try:
        raw_envelope_bytes = base64.b64decode(envelope_b64, validate=True)
        envelope_doc = canonical_json_loads(raw_envelope_bytes)
        if not isinstance(envelope_doc, dict):
            return RequestReadyResult(accepted=False, error="SCHEMA_INVALID"), None
        release_set_v2, payload_sha = verify_release_envelope_v2(envelope_doc, public_keys)
    except Exception:
        return RequestReadyResult(accepted=False, error="SIGNATURE_INVALID"), None

    # Protocol check: helper protocol 1 must be supported
    proto = release_set_v2.updater_protocol
    if not (proto.minimum <= 1 <= proto.maximum):
        return RequestReadyResult(accepted=False, error="PROTOCOL_UNSUPPORTED"), None

    # Anti-downgrade & conflict checks
    highwater_seq = current_state.highwater.release_sequence if current_state.highwater else 0
    observed_seq = current_state.observed.release_sequence if current_state.observed else 0
    committed_seq = current_state.committed.binding.release_sequence if current_state.committed else 0
    floor = max(highwater_seq, observed_seq, committed_seq)

    cand_seq = release_set_v2.release_sequence
    if cand_seq < floor:
        return RequestReadyResult(accepted=False, error="DOWNGRADE_REJECTED"), None
    if cand_seq == floor:
        # Same sequence check
        if current_state.observed is not None:
            if current_state.observed.payload_sha256 != payload_sha or current_state.observed.release_id != release_set_v2.release_id:
                return RequestReadyResult(accepted=False, error="SAME_SEQUENCE_CONFLICT"), None
            if current_state.failed == current_state.observed:
                return RequestReadyResult(accepted=False, error="CANDIDATE_SUPPRESSED"), None

    # Changed components calculation
    launcher_comp = release_set_v2.components["launcher"]
    core_comp = release_set_v2.components["core"]

    changed_launcher = (
        current_state.committed is None
        or current_state.committed.launcher_identity_sha256 != launcher_comp.installed_identity_sha256
    )
    changed_core = (
        current_state.committed is None
        or current_state.committed.core_identity_sha256 != core_comp.installed_identity_sha256
    )

    request_id = secrets.token_hex(16)
    transaction_id = secrets.token_hex(16)

    # Exclusively create incoming container
    try:
        handle, incoming_identity, _ = create_incoming_container(root_dir, request_id)
        import ctypes
        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return RequestReadyResult(accepted=False, error="IO_FAILED"), None

    cand_binding = Binding(
        release_sequence=cand_seq,
        release_id=release_set_v2.release_id,
        payload_sha256=payload_sha,
    )
    candidate_gen = Generation(
        binding=cand_binding,
        launcher_identity_sha256=launcher_comp.installed_identity_sha256,
        core_identity_sha256=core_comp.installed_identity_sha256,
    )

    tx = Transaction(
        id=transaction_id,
        request_id=request_id,
        candidate=candidate_gen,
        old=current_state.committed,
        incoming=incoming_identity,
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )

    next_evidence = dict(current_state.evidence)
    next_evidence[payload_sha] = envelope_b64

    next_state = State(
        schema_version=1,
        revision=current_state.revision + 1,
        installation_id=current_state.installation_id,
        helper_protocol=current_state.helper_protocol,
        enrollment_complete=current_state.enrollment_complete,
        phase="PREPARING",
        committed=current_state.committed,
        previous=current_state.previous,
        highwater=current_state.highwater,
        observed=cand_binding,
        failed=None,
        transaction=tx,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence=next_evidence,
    )

    try:
        validate_transition(current_state, next_state)
    except Exception:
        return RequestReadyResult(accepted=False, error="STATE_CORRUPT"), None

    ready_res = RequestReadyResult(
        accepted=True,
        request_id=request_id,
        transaction_id=transaction_id,
        changed={"launcher": changed_launcher, "core": changed_core},
        error=None,
    )
    return ready_res, next_state


def handle_apply_request(
    root_dir: Path,
    current_state: State,
    transaction_id: str,
    request_id: str,
    public_keys: Mapping[str, bytes],
) -> ApplyResult:
    """Handle APPLY from Launcher, verify on-disk artifacts match expected hashes, and formulate next State."""
    tx = current_state.transaction
    if tx is None or current_state.phase != "PREPARING":
        return ApplyResult(accepted=False, error="PROTOCOL_INVALID")
    if tx.id != transaction_id or tx.request_id != request_id:
        return ApplyResult(accepted=False, error="PROTOCOL_INVALID")

    incoming_dir = root_dir / "incoming" / request_id
    if not incoming_dir.exists():
        return ApplyResult(accepted=False, error="ARTIFACT_MISSING")

    # Verify expected files on disk
    expected_files: set[str] = set()
    cand = tx.candidate

    # Load signed envelope for candidate to obtain expected artifact hashes and sizes
    envelope_b64 = current_state.evidence.get(cand.binding.payload_sha256)
    if not envelope_b64:
        return ApplyResult(accepted=False, error="SIGNATURE_INVALID")
    try:
        envelope_bytes = base64.b64decode(envelope_b64, validate=True)
        envelope_doc = canonical_json_loads(envelope_bytes)
        rel_set, _ = verify_release_envelope_v2(envelope_doc, public_keys)
    except Exception:
        return ApplyResult(accepted=False, error="SIGNATURE_INVALID")

    # If launcher changed
    if current_state.committed is None or current_state.committed.launcher_identity_sha256 != cand.launcher_identity_sha256:
        launcher_file = incoming_dir / "launcher.artifact"
        if not launcher_file.exists():
            return ApplyResult(accepted=False, error="ARTIFACT_MISSING")
        data = launcher_file.read_bytes()
        expected_launcher = rel_set.components["launcher"]
        if len(data) != expected_launcher.artifact_size:
            return ApplyResult(accepted=False, error="PACKAGE_INVALID")
        if hashlib.sha256(data).hexdigest() != expected_launcher.artifact_sha256:
            return ApplyResult(accepted=False, error="HASH_MISMATCH")
        expected_files.add("launcher.artifact")

    # If core changed
    if current_state.committed is None or current_state.committed.core_identity_sha256 != cand.core_identity_sha256:
        core_file = incoming_dir / "core.artifact.zip"
        if not core_file.exists():
            return ApplyResult(accepted=False, error="ARTIFACT_MISSING")
        core_data = core_file.read_bytes()
        expected_core = rel_set.components["core"]
        if len(core_data) != expected_core.artifact_size:
            return ApplyResult(accepted=False, error="PACKAGE_INVALID")
        if hashlib.sha256(core_data).hexdigest() != expected_core.artifact_sha256:
            return ApplyResult(accepted=False, error="HASH_MISMATCH")
        expected_files.add("core.artifact.zip")

    # Check for extraneous files
    actual_files = {p.name for p in incoming_dir.iterdir() if p.is_file()}
    if actual_files != expected_files:
        return ApplyResult(accepted=False, error="PACKAGE_INVALID")

    return ApplyResult(accepted=True, error=None)
