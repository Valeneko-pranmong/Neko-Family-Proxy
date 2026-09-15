"""Current-Session Retirement Pre-Delete Validator (No DELETE Capability).

Validates fresh live readback state against approved forensic snapshots,
dependency audit evidence, custody bindings, canonical tag authority,
and the append-only Project Release-Audit Ledger.

This module validates evidence only. It has NO function that deletes a repository.
"""
from __future__ import annotations

import dataclasses
from enum import Enum
import json
from pathlib import Path
import re
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.capture_installer_repo_forensics import (  # noqa: E402
    ForensicSnapshot,
)
from scripts.project_release_audit_ledger import (  # noqa: E402
    EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
    EVENT_TYPE_RETIREMENT_PRECONDITIONS_RECORDED,
    OWNER_DISPOSITION_DELETE,
    QUALIFICATION_STATUS_KNOWN_BROKEN,
    ArtifactCustodyEvidence,
    ReleaseAuditEvent,
)
from scripts.release_dependency_audit import (  # noqa: E402
    DependencyAuditEvidence,
)

__all__ = [
    "PreDeleteCheckResult",
    "RetirementBlocker",
    "check_predelete_freshness",
]

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")


class RetirementBlocker(str, Enum):
    """Enumeration of all retirement pre-delete blocker codes.

    Contract: contains exactly TARGET_IDENTITY_MISMATCH, FORENSIC_STATE_CHANGED,
    DEPENDENCY_AUDIT_STALE, FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE,
    TAG_AUTHORITY_BLOCKED, and RETIREMENT_BLOCKED.
    """

    TARGET_IDENTITY_MISMATCH = "TARGET_IDENTITY_MISMATCH"
    FORENSIC_STATE_CHANGED = "FORENSIC_STATE_CHANGED"
    DEPENDENCY_AUDIT_STALE = "DEPENDENCY_AUDIT_STALE"
    FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE = "FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE"
    TAG_AUTHORITY_BLOCKED = "TAG_AUTHORITY_BLOCKED"
    RETIREMENT_BLOCKED = "RETIREMENT_BLOCKED"


@dataclasses.dataclass(frozen=True)
class PreDeleteCheckResult:
    """Outcome of pre-delete freshness verification."""

    allowed_now: bool
    blockers: tuple[RetirementBlocker, ...]
    live_inventory_sha256: str
    live_dependency_snapshot_sha256: str


def check_predelete_freshness(
    *,
    approved_forensic: ForensicSnapshot,
    live_forensic: ForensicSnapshot,
    dependency_evidence: DependencyAuditEvidence,
    live_dependency_snapshot_sha256: str,
    custody: ArtifactCustodyEvidence,
    latest_retirement_event: ReleaseAuditEvent,
    approved_final_source_sha: str,
    live_tag_commit_sha: str,
    live_replacement_readiness_sha256: str,
) -> PreDeleteCheckResult:
    """Validate fresh live readback state against approved evidence in current session.

    Derives approved replacement-readiness digest from latest_retirement_event.evidence.
    Performs pure comparison logic; does not cache PASS across sessions or calls.
    Contains no capability or parameters to execute a deletion.
    """
    blockers: list[RetirementBlocker] = []

    def _add_blocker(b: RetirementBlocker) -> None:
        if b not in blockers:
            blockers.append(b)

    # -------------------------------------------------------------------------
    # 1. Immutable Target Identity Validation
    # -------------------------------------------------------------------------
    live_repo = live_forensic.repository
    approved_repo = approved_forensic.repository

    target_identity_mismatch = (
        live_repo.numeric_id != approved_repo.numeric_id
        or live_repo.node_id != approved_repo.node_id
        or live_repo.owner.lower() != approved_repo.owner.lower()
        or live_repo.name.lower() != approved_repo.name.lower()
        or live_repo.numeric_id != latest_retirement_event.target_repository_id
        or live_repo.node_id != latest_retirement_event.target_repository_node_id
        or live_repo.owner.lower() != latest_retirement_event.target_owner.lower()
        or live_repo.name.lower() != latest_retirement_event.target_name.lower()
        or approved_repo.numeric_id != latest_retirement_event.target_repository_id
        or approved_repo.node_id != latest_retirement_event.target_repository_node_id
        or approved_repo.owner.lower() != latest_retirement_event.target_owner.lower()
        or approved_repo.name.lower() != latest_retirement_event.target_name.lower()
    )
    if target_identity_mismatch:
        _add_blocker(RetirementBlocker.TARGET_IDENTITY_MISMATCH)

    # -------------------------------------------------------------------------
    # 2. Complete Forensic Inventory Validation
    # -------------------------------------------------------------------------
    event_forensic_digest = (
        latest_retirement_event.evidence.get("forensic_inventory_digest")
        or latest_retirement_event.evidence.get("complete_forensic_inventory_sha256")
        or latest_retirement_event.evidence.get("forensic_inventory_sha256")
    )

    forensic_changed = (
        live_forensic.release_inventory_sha256 != approved_forensic.release_inventory_sha256
        or live_forensic.asset_inventory_sha256 != approved_forensic.asset_inventory_sha256
        or live_forensic.ref_inventory_sha256 != approved_forensic.ref_inventory_sha256
        or not event_forensic_digest
        or approved_forensic.complete_forensic_inventory_sha256 != event_forensic_digest
    )
    if not target_identity_mismatch:
        if (
            live_forensic.complete_forensic_inventory_sha256
            != approved_forensic.complete_forensic_inventory_sha256
            or live_forensic.repository_identity_sha256
            != approved_forensic.repository_identity_sha256
        ):
            forensic_changed = True

    if forensic_changed:
        _add_blocker(RetirementBlocker.FORENSIC_STATE_CHANGED)

    # -------------------------------------------------------------------------
    # 3. Dependency Audit Freshness Validation
    # -------------------------------------------------------------------------
    event_dep_in = (
        latest_retirement_event.evidence.get("dependency_input_digest")
        or latest_retirement_event.evidence.get("dependency_input_snapshot_sha256")
    )
    event_dep_res = (
        latest_retirement_event.evidence.get("dependency_result_digest")
        or latest_retirement_event.evidence.get("dependency_audit_result_sha256")
    )

    if (
        live_dependency_snapshot_sha256 != dependency_evidence.input_snapshot_sha256
        or not event_dep_in
        or dependency_evidence.input_snapshot_sha256 != event_dep_in
        or not event_dep_res
        or dependency_evidence.result_sha256 != event_dep_res
    ):
        _add_blocker(RetirementBlocker.DEPENDENCY_AUDIT_STALE)

    # -------------------------------------------------------------------------
    # 4. Forensic Artifact Custody Validation
    # -------------------------------------------------------------------------
    custody_error = False

    if custody.qualification_status != QUALIFICATION_STATUS_KNOWN_BROKEN:
        custody_error = True

    if (
        not isinstance(custody.known_broken_evidence_ref, str)
        or not custody.known_broken_evidence_ref.strip()
    ):
        custody_error = True

    if (
        not isinstance(custody.known_broken_evidence_sha256, str)
        or not _HEX64_RE.match(custody.known_broken_evidence_sha256)
    ):
        custody_error = True

    # Compare custody against latest_retirement_event custody binding
    event_custody_obj = (
        latest_retirement_event.evidence.get("custody")
        or latest_retirement_event.evidence.get("installer_custody")
        or latest_retirement_event.evidence.get("artifact_custody")
    )
    if event_custody_obj is None:
        event_custody_obj = latest_retirement_event.evidence

    if dataclasses.is_dataclass(event_custody_obj) and not isinstance(event_custody_obj, type):
        c_dict: dict[str, Any] = dataclasses.asdict(event_custody_obj)
    elif isinstance(event_custody_obj, dict):
        c_dict = event_custody_obj
    else:
        c_dict = {}
        custody_error = True

    if "sha256" in c_dict and custody.sha256 != c_dict["sha256"]:
        custody_error = True
    if "size" in c_dict and custody.size != c_dict["size"]:
        custody_error = True
    if "asset_id" in c_dict and custody.asset_id != c_dict["asset_id"]:
        custody_error = True
    if "release_id" in c_dict and custody.release_id != c_dict["release_id"]:
        custody_error = True
    if "repository_id" in c_dict and custody.repository_id != c_dict["repository_id"]:
        custody_error = True
    if "repository_node_id" in c_dict and custody.repository_node_id != c_dict["repository_node_id"]:
        custody_error = True
    if "known_broken_evidence_ref" in c_dict and (
        custody.known_broken_evidence_ref != c_dict["known_broken_evidence_ref"]
    ):
        custody_error = True
    if "known_broken_evidence_sha256" in c_dict and (
        custody.known_broken_evidence_sha256 != c_dict["known_broken_evidence_sha256"]
    ):
        custody_error = True
    if "qualification_status" in c_dict and (
        custody.qualification_status != c_dict["qualification_status"]
    ):
        custody_error = True

    # Verify custody asset exists in approved forensic assets
    try:
        raw_assets = approved_forensic.canonical_assets_json
        if isinstance(raw_assets, bytes):
            assets_list = json.loads(raw_assets.decode("utf-8"))
        elif isinstance(raw_assets, str):
            assets_list = json.loads(raw_assets)
        else:
            assets_list = []

        matching_asset = next(
            (a for a in assets_list if isinstance(a, dict) and a.get("id") == custody.asset_id),
            None,
        )
        if matching_asset is None or matching_asset.get("size") != custody.size:
            custody_error = True
    except Exception:
        custody_error = True

    if custody_error:
        _add_blocker(RetirementBlocker.FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE)

    # -------------------------------------------------------------------------
    # 5. Canonical Tag Authority Validation
    # -------------------------------------------------------------------------
    if (
        not isinstance(live_tag_commit_sha, str)
        or not _HEX40_RE.match(live_tag_commit_sha)
        or not isinstance(approved_final_source_sha, str)
        or not _HEX40_RE.match(approved_final_source_sha)
        or live_tag_commit_sha.lower() != approved_final_source_sha.lower()
    ):
        _add_blocker(RetirementBlocker.TAG_AUTHORITY_BLOCKED)

    # -------------------------------------------------------------------------
    # 6. Retirement Status and Replacement Readiness Validation
    # -------------------------------------------------------------------------
    retirement_blocked = False

    # Event type must be RETIREMENT_EVIDENCE_READY or RETIREMENT_PRECONDITIONS_RECORDED
    if latest_retirement_event.event_type not in (
        EVENT_TYPE_RETIREMENT_EVIDENCE_READY,
        EVENT_TYPE_RETIREMENT_PRECONDITIONS_RECORDED,
    ):
        retirement_blocked = True

    # delete_authorized is forbidden in evidence
    if "delete_authorized" in latest_retirement_event.evidence:
        retirement_blocked = True

    # Owner disposition must be DELETE
    if (
        latest_retirement_event.evidence.get("owner_disposition")
        != OWNER_DISPOSITION_DELETE
    ):
        retirement_blocked = True

    # Derived approved replacement-readiness digest from event evidence
    event_rep_ready = (
        latest_retirement_event.evidence.get("replacement_readiness_digest")
        or latest_retirement_event.evidence.get("replacement_readiness_sha256")
    )
    if (
        not event_rep_ready
        or not isinstance(live_replacement_readiness_sha256, str)
        or live_replacement_readiness_sha256.lower() != str(event_rep_ready).lower()
    ):
        retirement_blocked = True

    # Operational dependencies must be zero
    if dependency_evidence.operational_matches:
        retirement_blocked = True

    if retirement_blocked:
        _add_blocker(RetirementBlocker.RETIREMENT_BLOCKED)

    return PreDeleteCheckResult(
        allowed_now=len(blockers) == 0,
        blockers=tuple(blockers),
        live_inventory_sha256=live_forensic.complete_forensic_inventory_sha256,
        live_dependency_snapshot_sha256=live_dependency_snapshot_sha256,
    )
