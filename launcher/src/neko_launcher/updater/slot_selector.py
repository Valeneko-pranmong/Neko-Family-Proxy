"""Pairwise slot selector implementing the 6-predicate hierarchy from Section 8.1."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from neko_launcher.updater.binary_frame import FrameCorruptError, unpack_slot_frame
from neko_launcher.updater.canonical_json import canonical_json_loads
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from neko_launcher.updater.state_models import Binding, State, deserialize_state


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    ENROLLMENT_INCOMPLETE = "ENROLLMENT_INCOMPLETE"


@dataclass(frozen=True)
class SelectionResult:
    status: SelectionStatus
    state: State | None = None
    active_slot: str | None = None  # "a" or "b"
    reason: str | None = None


def _authenticate_evidence(state: State, public_keys: Mapping[str, bytes]) -> bool:
    """Verify that every binding referenced in state has an authenticated envelope in evidence."""
    referenced_bindings: list[Binding] = []
    if state.committed is not None:
        referenced_bindings.append(state.committed.binding)
    if state.previous is not None:
        referenced_bindings.append(state.previous.binding)
    if state.highwater is not None:
        referenced_bindings.append(state.highwater)
    if state.observed is not None:
        referenced_bindings.append(state.observed)
    if state.failed is not None:
        referenced_bindings.append(state.failed)
    if state.transaction is not None:
        referenced_bindings.append(state.transaction.candidate.binding)
        if state.transaction.old is not None:
            referenced_bindings.append(state.transaction.old.binding)
    if state.rollback is not None:
        referenced_bindings.append(state.rollback.target.binding)

    for binding in referenced_bindings:
        p_sha = binding.payload_sha256
        if p_sha not in state.evidence:
            return False

        envelope_b64 = state.evidence[p_sha]
        try:
            envelope_bytes = base64.b64decode(envelope_b64, validate=True)
            envelope_doc = canonical_json_loads(envelope_bytes)
            if not isinstance(envelope_doc, dict):
                return False
            release_set_v2, payload_sha256 = verify_release_envelope_v2(envelope_doc, public_keys)
        except Exception:
            return False

        if payload_sha256 != p_sha:
            return False
        if release_set_v2.release_sequence != binding.release_sequence:
            return False
        if release_set_v2.release_id != binding.release_id:
            return False

    return True


def _classify_slot(raw: bytes | None) -> tuple[bool, State | None, int | None, str | None]:
    """Return (frame_valid, state_or_none, revision, error_description)."""
    if raw is None:
        return False, None, None, "missing"
    try:
        frame = unpack_slot_frame(raw)
    except (FrameCorruptError, ValueError) as err:
        return False, None, None, f"torn frame: {err}"

    try:
        state = deserialize_state(frame.body_bytes)
        return True, state, frame.revision, None
    except ValueError as err:
        return True, None, frame.revision, f"malformed schema: {err}"


def select_active_slot(
    slot_a_bytes: bytes | None,
    slot_b_bytes: bytes | None,
    public_keys: Mapping[str, bytes],
) -> SelectionResult:
    """Classify and select the authoritative active slot according to Section 8.1."""
    if slot_a_bytes is None and slot_b_bytes is None:
        return SelectionResult(
            status=SelectionStatus.ENROLLMENT_INCOMPLETE,
            reason="No slots exist on disk",
        )

    a_frame_valid, state_a, rev_a, err_a = _classify_slot(slot_a_bytes)
    b_frame_valid, state_b, rev_b, err_b = _classify_slot(slot_b_bytes)

    # Case 1: Both frames are frame-valid
    if a_frame_valid and b_frame_valid:
        assert rev_a is not None and rev_b is not None

        # Check schema validity
        if state_a is None or state_b is None:
            if rev_a > rev_b:
                if state_a is None:
                    return SelectionResult(
                        status=SelectionStatus.REPAIR_REQUIRED,
                        reason="Malformed higher slot A",
                    )
                return SelectionResult(
                    status=SelectionStatus.REPAIR_REQUIRED,
                    reason="Malformed stale history slot B",
                )
            elif rev_b > rev_a:
                if state_b is None:
                    return SelectionResult(
                        status=SelectionStatus.REPAIR_REQUIRED,
                        reason="Malformed higher slot B",
                    )
                return SelectionResult(
                    status=SelectionStatus.REPAIR_REQUIRED,
                    reason="Malformed stale history slot A",
                )
            else:
                return SelectionResult(
                    status=SelectionStatus.REPAIR_REQUIRED,
                    reason="Equal revision malformed slot",
                )

        # Both have valid schema; check evidence authentication
        if not _authenticate_evidence(state_a, public_keys):
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason="Evidence unauthenticated in slot A",
            )
        if not _authenticate_evidence(state_b, public_keys):
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason="Evidence unauthenticated in slot B",
            )

        # Equal revisions check
        if rev_a == rev_b:
            if (
                rev_a == 1
                and state_a.phase == "ENROLLING"
                and state_b.phase == "ENROLLING"
                and state_a == state_b
            ):
                return SelectionResult(
                    status=SelectionStatus.SELECTED,
                    state=state_a,
                    active_slot="a",
                )
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason=f"Equal revision {rev_a} with differing content or illegal phase",
            )

        # Check revision adjacency
        if abs(rev_a - rev_b) != 1:
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason=f"Nonadjacent revisions: {rev_a} and {rev_b}",
            )

        if rev_b > rev_a:
            return SelectionResult(
                status=SelectionStatus.SELECTED,
                state=state_b,
                active_slot="b",
            )
        else:
            return SelectionResult(
                status=SelectionStatus.SELECTED,
                state=state_a,
                active_slot="a",
            )

    # Case 2: Exactly one frame is frame-valid
    if a_frame_valid and not b_frame_valid:
        if state_a is None:
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason="Malformed schema in sole valid frame A",
            )
        if not _authenticate_evidence(state_a, public_keys):
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason="Evidence unauthenticated in sole frame A",
            )
        return SelectionResult(
            status=SelectionStatus.SELECTED,
            state=state_a,
            active_slot="a",
        )

    if b_frame_valid and not a_frame_valid:
        if state_b is None:
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason="Malformed schema in sole valid frame B",
            )
        if not _authenticate_evidence(state_b, public_keys):
            return SelectionResult(
                status=SelectionStatus.REPAIR_REQUIRED,
                reason="Evidence unauthenticated in sole frame B",
            )
        return SelectionResult(
            status=SelectionStatus.SELECTED,
            state=state_b,
            active_slot="b",
        )

    # Case 3: Neither frame is frame-valid
    return SelectionResult(
        status=SelectionStatus.REPAIR_REQUIRED,
        reason=f"Both frames torn or invalid: A ({err_a}), B ({err_b})",
    )
