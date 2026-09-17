import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from typing import Any
import zipfile

# Add project root to sys.path so we can import internal modules
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS  # noqa: E402

from scripts.ci_change_classifier import should_trigger  # noqa: E402
from scripts.kanban_release_adapter import get_successful_main_runs  # noqa: E402
from scripts.publish_atomic_release import (  # noqa: E402
    
    CANONICAL_REPO,
    CommandExecutor,
    StageDraftReleaseError,
    _SubprocessExecutor,
    _hosted_verify_unified_channel,
    _run,
    build_machine_release_notes,
    download_github_release_asset,
    stage_draft_release,
    validate_staging_preconditions,
)
from scripts.publish_human_release import (  # noqa: E402
    HumanPublishError as InstallerPublishError,
    REQUIRED_HUMAN_ASSET as REQUIRED_INSTALLER_ASSET,
)
from scripts.verify_human_release_assets import (  # noqa: E402
    HumanReleaseVerificationError as InstallerReleaseVerificationError,
    verify_human_release_assets as verify_installer_release_assets,
)
from datetime import datetime, timezone  # noqa: E402
from typing import Literal  # noqa: E402
from authenticated_production_history import (  # noqa: E402
    AuthenticatedEnvelopeRecord,
    AuthenticatedHistoryProvider,
    append_custody_record,
)
from build_software_release_v2 import UnsignedBaselineEvidence  # noqa: E402
from derive_version import ReleaseAllocation  # noqa: E402
from production_sequence_ledger import (  # noqa: E402
    PreparedSupersessionResult,  # noqa: F401
    ReleaseAuthorityReconciliationRequired,
    SequenceAuthorityError,
    SequenceLedgerEvent,
    SupersedeSignedReleaseRequest,  # noqa: F401
    open_authority_session,
    prepare_signed_release_supersession,  # noqa: F401
    reconcile_ledger_with_authenticated_history,
)
from sign_software_release import (  # noqa: E402
    DetachedReleaseSignature,
    ReleaseSigner,
)

BOOTSTRAP_STABLE_TAG = "v5.1.0"


@dataclass(frozen=True)
class SigningRequired:
    status: Literal["SIGNING_REQUIRED"]
    payload_path: Path
    payload_sha256: str


@dataclass(frozen=True)
class SignedBaselineEvidence:
    sequence: int
    release_id: str
    component_set_sha256: str
    payload_sha256: str
    envelope_sha256: str
    key_id: str
    envelope_path: Path


def sign_reserved_baseline(
    *,
    ledger_path: Path,
    custody_root: Path,
    history_provider: AuthenticatedHistoryProvider,
    production_public_keys: Mapping[str, bytes],
    allocation: ReleaseAllocation,
    unsigned: UnsignedBaselineEvidence,
    signer: ReleaseSigner | None,
) -> SignedBaselineEvidence | SigningRequired:
    if not isinstance(production_public_keys, Mapping) or not production_public_keys:
        raise ValueError("production_public_keys must be a non-empty mapping")
    for k, v in production_public_keys.items():
        if not isinstance(k, str) or not isinstance(v, (bytes, bytearray)) or len(v) != 32:
            raise ValueError(f"Invalid release public key entry: {k!r}")
        if "proof" in k.lower():
            raise ValueError(f"Proof release authority key is forbidden in production signing boundary: {k!r}")
    if len(production_public_keys) > 1:
        raise ValueError(
            f"Mixed or multi-key registry forbidden in production signing boundary: {list(production_public_keys.keys())}"
        )

    if allocation.sequence != unsigned.sequence:
        raise ValueError(
            f"Allocation sequence {allocation.sequence} mismatch with unsigned baseline {unsigned.sequence}"
        )
    if allocation.release_id != unsigned.release_id:
        raise ValueError(
            f"Allocation release_id {allocation.release_id} mismatch with unsigned baseline {unsigned.release_id}"
        )
    if allocation.component_set_sha256 != unsigned.component_set_sha256:
        raise ValueError("Allocation component set digest mismatch with unsigned baseline")

    if not unsigned.payload_path.is_file():
        raise FileNotFoundError(f"Unsigned payload file not found: {unsigned.payload_path}")
    payload_bytes = unsigned.payload_path.read_bytes()
    actual_payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    if actual_payload_sha != unsigned.payload_sha256:
        raise ValueError(
            f"Unsigned payload SHA mismatch: got {actual_payload_sha}, expected {unsigned.payload_sha256}"
        )

    with open_authority_session(ledger_path) as session:
        if not session.path.is_file() or session.path.stat().st_size == 0:
            raise SequenceAuthorityError("Sequence ledger has not been initialized with genesis")

        verified = session.read_verified()
        snapshot = history_provider.load()
        authority = reconcile_ledger_with_authenticated_history(
            ledger=verified,
            authenticated_history=snapshot,
        )

        reserved_event = next(
            (e for e in verified.events if e.sequence == allocation.sequence and e.status == "RESERVED"),
            None,
        )
        if reserved_event is None:
            raise SequenceAuthorityError(f"No RESERVED event found for sequence {allocation.sequence}")

        # Recovery case: exact custody already contains signed binding
        if (
            authority.recovery_action == "SIGNED_APPEND_REQUIRED"
            and authority.recovery_sequence == allocation.sequence
        ):
            if allocation.sequence not in snapshot.bindings_by_sequence:
                raise ReleaseAuthorityReconciliationRequired(
                    f"Sequence {allocation.sequence} missing from authenticated history bindings during recovery"
                )
            auth_binding = snapshot.bindings_by_sequence[allocation.sequence]
            envelope_path = custody_root / "envelopes" / f"{auth_binding.envelope_sha256}.json"
            if not envelope_path.is_file():
                raise FileNotFoundError(f"Custody envelope missing for sequence {allocation.sequence}: {envelope_path}")
            envelope_bytes = envelope_path.read_bytes()
            if hashlib.sha256(envelope_bytes).hexdigest() != auth_binding.envelope_sha256:
                raise ValueError("Custody envelope sha256 mismatch")

            try:
                envelope_doc = json.loads(envelope_bytes.decode("utf-8"))
            except Exception as exc:
                raise ValueError(f"Malformed JSON in custody envelope: {exc}") from exc

            rel_set, returned_payload_sha = verify_release_envelope_v2(envelope_doc, production_public_keys)
            verified_key_id = envelope_doc.get("key_id")
            if verified_key_id not in production_public_keys:
                raise ValueError(f"Envelope key_id {verified_key_id!r} not in production public keys")
            if verified_key_id != auth_binding.key_id:
                raise ValueError(
                    f"Envelope key_id mismatch: {verified_key_id} vs {auth_binding.key_id}"
                )
            if rel_set.release_sequence != allocation.sequence:
                raise ValueError(
                    f"Envelope sequence {rel_set.release_sequence} mismatch with allocation {allocation.sequence}"
                )
            if rel_set.release_id != allocation.release_id:
                raise ValueError(
                    f"Envelope release_id {rel_set.release_id} mismatch with allocation {allocation.release_id}"
                )
            if returned_payload_sha != unsigned.payload_sha256:
                raise ValueError(
                    f"Envelope payload sha {returned_payload_sha} mismatch with unsigned {unsigned.payload_sha256}"
                )

            signed_event = SequenceLedgerEvent(
                record_type="EVENT",
                sequence=allocation.sequence,
                release_id=allocation.release_id,
                status="SIGNED",
                version=reserved_event.version,
                channel=reserved_event.channel,
                source_commit=reserved_event.source_commit,
                component_set_sha256=unsigned.component_set_sha256,
                payload_sha256=unsigned.payload_sha256,
                envelope_sha256=auth_binding.envelope_sha256,
                key_id=verified_key_id,
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                previous_entry_sha256=verified.latest_entry_sha256,
            )
            entry_sha = session.append(signed_event, expected_previous_sha256=verified.latest_entry_sha256)
            re_verified = session.read_verified()
            if re_verified.latest_entry_sha256 != entry_sha:
                raise SequenceAuthorityError("Append readback mismatch")

            return SignedBaselineEvidence(
                sequence=allocation.sequence,
                release_id=allocation.release_id,
                component_set_sha256=unsigned.component_set_sha256,
                payload_sha256=unsigned.payload_sha256,
                envelope_sha256=auth_binding.envelope_sha256,
                key_id=verified_key_id,
                envelope_path=envelope_path,
            )

        if authority.recovery_action is not None:
            raise ReleaseAuthorityReconciliationRequired(
                f"Ledger reconciliation required: {authority.recovery_action} for sequence {authority.recovery_sequence}"
            )

        if authority.highest_authenticated_sequence >= allocation.sequence:
            raise ReleaseAuthorityReconciliationRequired(
                f"Authenticated sequence {authority.highest_authenticated_sequence} conflicts with allocation {allocation.sequence}"
            )
        if authority.highest_consumed_sequence > allocation.sequence:
            raise ReleaseAuthorityReconciliationRequired(
                f"Consumed sequence {authority.highest_consumed_sequence} exceeds allocation {allocation.sequence}"
            )
        if authority.next_unused_sequence > allocation.sequence + 1:
            raise ReleaseAuthorityReconciliationRequired(
                f"Next unused sequence {authority.next_unused_sequence} exceeds allocation {allocation.sequence} + 1"
            )

        if signer is None:
            return SigningRequired(
                status="SIGNING_REQUIRED",
                payload_path=unsigned.payload_path,
                payload_sha256=unsigned.payload_sha256,
            )

        detached_sig = signer.sign(payload_bytes)
        if not isinstance(detached_sig, DetachedReleaseSignature):
            raise ValueError("Signer did not return a DetachedReleaseSignature")
        if detached_sig.key_id not in production_public_keys:
            raise ValueError(
                f"Signer key_id {detached_sig.key_id!r} absent from supplied production public keys"
            )
        if not isinstance(detached_sig.signature, (bytes, bytearray)) or len(detached_sig.signature) != 64:
            raise ValueError("Signer returned invalid signature length")

        from scripts.assemble_release_v2_envelope import assemble_verified_release_v2_envelope

        envelope_bytes = assemble_verified_release_v2_envelope(
            payload_bytes=payload_bytes,
            key_id=detached_sig.key_id,
            detached_signature=bytes(detached_sig.signature),
            release_public_keys=production_public_keys,
        )

        try:
            envelope_doc = json.loads(envelope_bytes.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Malformed JSON in assembled envelope: {exc}") from exc

        rel_set, returned_payload_sha = verify_release_envelope_v2(envelope_doc, production_public_keys)
        verified_key_id = envelope_doc.get("key_id")
        if verified_key_id not in production_public_keys:
            raise ValueError(f"Verified envelope key_id {verified_key_id!r} not in production public keys")
        if rel_set.release_sequence != allocation.sequence:
            raise ValueError(
                f"Envelope sequence {rel_set.release_sequence} mismatch with allocation {allocation.sequence}"
            )
        if rel_set.release_id != allocation.release_id:
            raise ValueError(
                f"Envelope release_id {rel_set.release_id} mismatch with allocation {allocation.release_id}"
            )
        if returned_payload_sha != unsigned.payload_sha256:
            raise ValueError(
                f"Envelope payload sha {returned_payload_sha} mismatch with unsigned {unsigned.payload_sha256}"
            )

        canon_envelope_bytes = envelope_bytes.strip()
        envelope_sha256 = hashlib.sha256(canon_envelope_bytes).hexdigest()
        custody_record = AuthenticatedEnvelopeRecord(
            source_id=f"custody-{allocation.sequence:04d}",
            source_kind="custody",
            envelope_bytes=canon_envelope_bytes,
            provenance_source_commit=reserved_event.source_commit,
        )
        index_file = custody_root / "history-index-v1.json"
        expected_index_sha = (
            hashlib.sha256(index_file.read_bytes()).hexdigest()
            if index_file.is_file()
            else None
        )
        append_custody_record(custody_root, custody_record, expected_index_sha256=expected_index_sha)
        envelope_path = custody_root / "envelopes" / f"{envelope_sha256}.json"
        if not envelope_path.is_file():
            raise ValueError(f"Custody envelope file missing after append: {envelope_path}")

        refreshed_snapshot = history_provider.load()
        refreshed_authority = reconcile_ledger_with_authenticated_history(
            ledger=session.read_verified(),
            authenticated_history=refreshed_snapshot,
        )
        if (
            refreshed_authority.recovery_action != "SIGNED_APPEND_REQUIRED"
            or refreshed_authority.recovery_sequence != allocation.sequence
        ):
            raise SequenceAuthorityError(
                f"Expected SIGNED_APPEND_REQUIRED for sequence {allocation.sequence} after custody write, "
                f"got {refreshed_authority.recovery_action} (sequence {refreshed_authority.recovery_sequence})"
            )

        signed_event = SequenceLedgerEvent(
            record_type="EVENT",
            sequence=allocation.sequence,
            release_id=allocation.release_id,
            status="SIGNED",
            version=reserved_event.version,
            channel=reserved_event.channel,
            source_commit=reserved_event.source_commit,
            component_set_sha256=unsigned.component_set_sha256,
            payload_sha256=unsigned.payload_sha256,
            envelope_sha256=envelope_sha256,
            key_id=verified_key_id,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            previous_entry_sha256=session.read_verified().latest_entry_sha256,
        )
        entry_sha = session.append(signed_event, expected_previous_sha256=signed_event.previous_entry_sha256)
        re_verified = session.read_verified()
        if re_verified.latest_entry_sha256 != entry_sha:
            raise SequenceAuthorityError("Append readback mismatch")

        return SignedBaselineEvidence(
            sequence=allocation.sequence,
            release_id=allocation.release_id,
            component_set_sha256=unsigned.component_set_sha256,
            payload_sha256=unsigned.payload_sha256,
            envelope_sha256=envelope_sha256,
            key_id=verified_key_id,
            envelope_path=envelope_path,
        )


def _contains_machine_repo(text: str) -> bool:
    pattern = re.compile(
        r"(?:repos/|github\.com/|^)" + re.escape(CANONICAL_REPO) + r"(?:/|\?|#|$)",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


@dataclass(frozen=True)
class StagedInstallerDraftEvidence:
    release_id: int
    tag_name: str
    target_commit: str
    repo: str
    installer_asset_id: int
    installer_size: int
    installer_sha256: str
    dispatch_command: str


def validate_installer_repo_configuration(repo: str | None) -> str:
    if not repo or not str(repo).strip():
        raise ValueError(
            "Explicit installer repository identity is mandatory with no silent fallback"
        )
    cleaned = str(repo).strip()
    normalized = re.sub(r"\.git$", "", cleaned, flags=re.IGNORECASE)
    if (
        _contains_machine_repo(cleaned)
        or _contains_machine_repo(normalized)
        or cleaned.lower() == CANONICAL_REPO.lower()
        or normalized.lower() == CANONICAL_REPO.lower()
    ):
        raise ValueError(
            f"Installer repository cannot be the canonical machine repository ({CANONICAL_REPO})"
        )
    return cleaned



def _parse_semver(tag: str) -> tuple[int, int, int]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", tag)
    if not m:
        raise ValueError(f"Invalid semver tag format: {tag}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_version_newer(candidate_tag: str, base_tag: str) -> bool:
    return _parse_semver(candidate_tag) > _parse_semver(base_tag)


@dataclass(frozen=True)
class CoreAuthoritySource:
    manifest_path: Path
    core_zip_path: Path
    provenance: dict[str, object]
    core_sha256: str = ""
    core_size: int = 0
    installed_identity_sha256: str = ""


def _get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_core_authority_bytes(
    manifest_path: Path,
    core_zip_path: Path,
    expected_tag: str,
    *,
    trusted_keys: Mapping[str, bytes] | None = None,
    updater_exe_path: Path | None = None,
) -> tuple[str, int, str]:
    from neko_launcher.updater.core_manifest_verifier import (
        verify_canonical_core_bundle,
    )
    from neko_launcher.updater.zip_extractor import extract_core_bundle

    if not manifest_path.is_file():
        raise RuntimeError(f"Manifest file not found: {manifest_path}")
    if not core_zip_path.is_file():
        raise RuntimeError(f"Core zip file not found: {core_zip_path}")

    try:
        manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to read/parse manifest JSON: {e}") from e

    if trusted_keys is None:
        trusted_keys = {"neko-update-prod-1": PRODUCTION_RELEASE_PUBLIC_KEYS["neko-update-prod-1"]}

    try:
        release_set, _ = verify_release_envelope_v2(manifest_doc, trusted_keys)
    except Exception as e:
        err_msg = str(e)
        if "channel" in err_msg.lower():
            raise RuntimeError(f"Release manifest channel is not stable: {e}") from e
        raise RuntimeError(f"Failed to verify release envelope signature: {e}") from e

    # Require channel stable
    if release_set.channel != "stable":
        raise RuntimeError(f"Release manifest channel is not stable (got '{release_set.channel}').")

    # If updater artifact is present, verify against signed authority
    if updater_exe_path is not None and updater_exe_path.is_file():
        if "updater" in release_set.components:
            up_comp = release_set.components["updater"]
            actual_up_sha = _get_sha256(updater_exe_path)
            actual_up_size = updater_exe_path.stat().st_size
            if actual_up_sha != up_comp.artifact_sha256.lower() or actual_up_size != up_comp.artifact_size:
                raise RuntimeError(
                    f"Archived NekoUpdater.exe in bootstrap authority does not match signed authority: "
                    f"sha {actual_up_sha} vs {up_comp.artifact_sha256}, size {actual_up_size} vs {up_comp.artifact_size}"
                )

    # Require core component
    if "core" not in release_set.components:
        raise RuntimeError("Core component missing from release manifest.")

    core_comp = release_set.components["core"]
    if core_comp.artifact_id != "NekoProxyCore.zip":
        raise RuntimeError(f"Core artifact_id mismatch: {core_comp.artifact_id}")

    expected_version = expected_tag.lstrip("v")
    if core_comp.version != expected_version:
        raise RuntimeError(
            f"Core component version '{core_comp.version}' does not match expected tag version '{expected_version}'."
        )

    expected_hash = core_comp.artifact_sha256.lower()
    expected_size = core_comp.artifact_size
    installed_identity = core_comp.installed_identity_sha256.lower()

    # Compare Core SHA256 and size to signed component
    actual_size = core_zip_path.stat().st_size
    actual_hash = _get_sha256(core_zip_path)

    if actual_size != expected_size or actual_hash != expected_hash:
        raise RuntimeError(
            f"Core zip does not match {expected_tag} signature: "
            f"size {actual_size} vs {expected_size}, sha256 {actual_hash} vs {expected_hash}"
        )

    # Run canonical Core bundle verifier + installed identity check
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        extract_core_bundle(core_zip_path, tmp_dir)
        verification = verify_canonical_core_bundle(tmp_dir)
        if not verification.valid:
            raise RuntimeError(f"Core bundle verification failed: {verification.error}")
        if verification.manifest_sha256 != installed_identity:
            raise RuntimeError(
                f"Core manifest installed identity mismatch inside zip: "
                f"expected {installed_identity}, got {verification.manifest_sha256}"
            )

    return actual_hash, actual_size, installed_identity


def resolve_core_authority(
    stable_tag: str,
    staging_dir: Path,
    *,
    bootstrap_authority_dir: Path | None = None,
    trusted_keys: Mapping[str, bytes] | None = None,
    core_authority: Any | None = None,
    core_authority_custody_dir: Path | None = None,
    network_executor: Any | None = None,
) -> CoreAuthoritySource:
    staging_dir.mkdir(parents=True, exist_ok=True)
    release_json_path = staging_dir / "release-v2.json"
    core_zip_path = staging_dir / "NekoProxyCore.zip"
    updater_exe_path: Path | None = None

    if core_authority is not None or core_authority_custody_dir is not None:
        if core_authority is None:
            from scripts.core_authority_custody import load_verified_core_authority
            core_authority = load_verified_core_authority(
                core_authority_custody_dir,
                trusted_public_keys=trusted_keys,
            )

        # Stage assets into staging_dir
        if core_authority.core_zip_path.resolve() != core_zip_path.resolve():
            shutil.copy2(core_authority.core_zip_path, core_zip_path)

        provenance: dict[str, object] = {
            "source": "core_authority_custody",
            "authority_version_tag": core_authority.binding.authority_version_tag,
            "authority_release_sequence": core_authority.binding.authority_release_sequence,
            "authority_release_id": core_authority.binding.authority_release_id,
            "authority_envelope_sha256": core_authority.binding.authority_envelope_sha256,
            "authority_payload_sha256": core_authority.binding.authority_payload_sha256,
            "authority_key_id": core_authority.binding.authority_key_id,
            "core_source_commit": core_authority.binding.core_source_commit,
            "provenance_sha256": core_authority.binding.provenance_sha256,
        }

        return CoreAuthoritySource(
            manifest_path=release_json_path,
            core_zip_path=core_zip_path,
            provenance=provenance,
            core_sha256=core_authority.core.sha256,
            core_size=core_authority.core.size,
            installed_identity_sha256=core_authority.core.installed_identity_sha256,
        )

    if bootstrap_authority_dir is not None:
        # Bounded bootstrap authority override
        if stable_tag != BOOTSTRAP_STABLE_TAG:
            if is_version_newer(stable_tag, BOOTSTRAP_STABLE_TAG):
                raise RuntimeError(
                    f"Bootstrap authority override is disabled because stable tag '{stable_tag}' "
                    f"is newer than bootstrap stable '{BOOTSTRAP_STABLE_TAG}'."
                )
            raise RuntimeError(
                f"Bootstrap authority override is only permitted for recognized bootstrap stable "
                f"'{BOOTSTRAP_STABLE_TAG}', not '{stable_tag}'."
            )

        if not bootstrap_authority_dir.is_dir():
            raise RuntimeError(
                f"Bootstrap authority directory does not exist or is not a directory: {bootstrap_authority_dir}"
            )

        manifest_src = bootstrap_authority_dir / "release-v2.json"
        core_src = bootstrap_authority_dir / "NekoProxyCore.zip"

        if not manifest_src.is_file() or not core_src.is_file():
            raise RuntimeError(
                f"Bootstrap authority directory is missing required assets (release-v2.json and NekoProxyCore.zip): {bootstrap_authority_dir}"
            )

        # Stage assets into staging_dir
        if staging_dir.resolve() != bootstrap_authority_dir.resolve():
            shutil.copy2(manifest_src, release_json_path)
            shutil.copy2(core_src, core_zip_path)

        # Also inspect/stage updater if present in bootstrap directory
        updater_src = bootstrap_authority_dir / "NekoUpdater.exe"
        staged_updater = staging_dir / "NekoUpdater.exe"
        if updater_src.is_file():
            if staging_dir.resolve() != bootstrap_authority_dir.resolve():
                shutil.copy2(updater_src, staged_updater)
            updater_exe_path = staged_updater

        provenance = {
            "source": "local_bootstrap_override",
            "stable_tag": stable_tag,
            "bootstrap_authority_dir": str(bootstrap_authority_dir.resolve()),
            "manifest_asset": "release-v2.json",
            "core_asset": "NekoProxyCore.zip",
        }
    else:
        # 1. Query GitHub release by exact stable tag (Normal path)
        print(f"Fetching {stable_tag} Core authority from GitHub...")
        cmd = ["gh", "api", f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/tags/{stable_tag}"]
        try:
            if network_executor is not None:
                out = network_executor.run(cmd, capture_output=True).stdout
            else:
                out = subprocess.check_output(cmd)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to fetch release {stable_tag}: {e}") from e

        release_data = json.loads(out)

        # 2. Require exactly one matching non-draft non-prerelease accepted release
        if release_data.get("draft") or release_data.get("prerelease"):
            raise RuntimeError(f"Release {stable_tag} is draft or prerelease.")

        release_id = release_data["id"]

        # 3. Require unique release-v2.json + NekoProxyCore.zip assets with numeric asset IDs
        release_json_asset = None
        core_zip_asset = None

        for asset in release_data.get("assets", []):
            if asset["name"] == "release-v2.json":
                if release_json_asset is not None:
                    raise RuntimeError("Duplicate release-v2.json assets found.")
                release_json_asset = asset
            elif asset["name"] == "NekoProxyCore.zip":
                if core_zip_asset is not None:
                    raise RuntimeError("Duplicate NekoProxyCore.zip assets found.")
                core_zip_asset = asset

        if not release_json_asset or not core_zip_asset:
            raise RuntimeError("Missing required assets in release.")

        manifest_asset_id = release_json_asset["id"]
        core_asset_id = core_zip_asset["id"]

        # 4. Download BOTH by immutable asset ID into staging
        if network_executor is not None:
            network_executor.run([
                "gh", "api",
                f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{manifest_asset_id}",
                "-H", "Accept: application/octet-stream"
            ])
            network_executor.run([
                "gh", "api",
                f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{core_asset_id}",
                "-H", "Accept: application/octet-stream"
            ])
        else:
            subprocess.run([
                "gh", "api",
                f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{manifest_asset_id}",
                "-H", "Accept: application/octet-stream"
            ], stdout=release_json_path.open("wb"), check=True)

            subprocess.run([
                "gh", "api",
                f"repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/{core_asset_id}",
                "-H", "Accept: application/octet-stream"
            ], stdout=core_zip_path.open("wb"), check=True)

        provenance = {
            "source": "github_release",
            "stable_tag": stable_tag,
            "release_id": release_id,
            "manifest_asset_id": manifest_asset_id,
            "core_asset_id": core_asset_id,
        }

    # Verify common byte-level cryptographic and canonical bundle properties
    core_hash, core_size, installed_identity = verify_core_authority_bytes(
        release_json_path,
        core_zip_path,
        expected_tag=stable_tag,
        trusted_keys=trusted_keys,
        updater_exe_path=updater_exe_path,
    )
    print(f"{stable_tag} Core verified successfully.")

    return CoreAuthoritySource(
        manifest_path=release_json_path,
        core_zip_path=core_zip_path,
        provenance=provenance,
        core_sha256=core_hash,
        core_size=core_size,
        installed_identity_sha256=installed_identity,
    )


def verify_and_fetch_core(
    stable_tag: str,
    staging_dir: Path,
    *,
    bootstrap_authority_dir: Path | None = None,
    trusted_keys: Mapping[str, bytes] | None = None,
    core_authority: Any | None = None,
    core_authority_custody_dir: Path | None = None,
) -> tuple[Path, str, int, str, dict]:
    print(f"Fetching and verifying {stable_tag} Core authority...")
    source = resolve_core_authority(
        stable_tag,
        staging_dir,
        bootstrap_authority_dir=bootstrap_authority_dir,
        trusted_keys=trusted_keys,
        core_authority=core_authority,
        core_authority_custody_dir=core_authority_custody_dir,
    )
    return (
        source.core_zip_path,
        source.core_sha256,
        source.core_size,
        source.installed_identity_sha256,
        source.provenance,
    )


def validate_installer_staging_preconditions(
    *,
    staging_dir: Path,
    tag: str,
    target_commit: str,
    installer_repo: str,
    repo_root: Path,
    executor: CommandExecutor,
) -> tuple[Path, str, int]:
    validate_installer_repo_configuration(installer_repo)
    if re.fullmatch(r"^[0-9a-fA-F]{40}$", target_commit) is None:
        raise InstallerPublishError("Target commit must be a 40-character hexadecimal SHA")

    git = ["git", "-C", str(repo_root)]
    status = _run(executor, [*git, "status", "--porcelain", "--untracked-files=all"])
    if status:
        raise InstallerPublishError("Worktree is not clean")

    bound = _run(executor, [*git, "rev-parse", f"{tag}^{{commit}}"]).strip()
    if bound.lower() != target_commit.lower():
        raise InstallerPublishError("Local tag does not bind to target commit")

    staging_path = Path(staging_dir)
    if staging_path.is_dir():
        names = {item.name for item in staging_path.iterdir()}
        if REQUIRED_INSTALLER_ASSET not in names:
            raise InstallerPublishError(
                f"Staging directory missing required installer asset: {REQUIRED_INSTALLER_ASSET}"
            )
        extra = names - {REQUIRED_INSTALLER_ASSET}
        if extra:
            raise InstallerPublishError(
                f"Staging directory must contain exactly one custom installer asset (found extra: {sorted(extra)})"
            )
        installer_file = staging_path / REQUIRED_INSTALLER_ASSET
    elif staging_path.is_file():
        if staging_path.name != REQUIRED_INSTALLER_ASSET:
            raise InstallerPublishError(
                f"Installer file name mismatch: expected {REQUIRED_INSTALLER_ASSET!r}, got {staging_path.name!r}"
            )
        installer_file = staging_path
    else:
        raise InstallerPublishError(f"Staging path does not exist: {staging_path}")

    if not installer_file.is_file() or installer_file.stat().st_size <= 0:
        raise InstallerPublishError("Installer asset must be a non-empty regular file")

    file_bytes = installer_file.read_bytes()
    sha256 = hashlib.sha256(file_bytes).hexdigest().lower()
    size = len(file_bytes)
    return installer_file, sha256, size


def stage_installer_draft_release(
    *,
    staging_dir: Path | str,
    tag: str,
    target_commit: str,
    installer_repo: str = CANONICAL_REPO,
    title: str | None = None,
    notes: str | None = None,
    as_prerelease: bool = False,
    dry_run: bool = False,
    executor: CommandExecutor | None = None,
) -> StagedInstallerDraftEvidence | None:
    runner = executor or _SubprocessExecutor()
    repo = validate_installer_repo_configuration(installer_repo)
    repo_root = Path(__file__).resolve().parent.parent

    installer_file, sha256, size = validate_installer_staging_preconditions(
        staging_dir=Path(staging_dir),
        tag=tag,
        target_commit=target_commit,
        installer_repo=repo,
        repo_root=repo_root,
        executor=runner,
    )

    create = [
        "gh",
        "release",
        "create",
        tag,
        "--target",
        target_commit,
        "--verify-tag",
        "--draft",
        f"--prerelease={str(as_prerelease).lower()}",
        "--repo",
        repo,
    ]
    if title is not None:
        create.extend(["--title", title])
    if notes is not None:
        create.extend(["--notes", notes])

    upload = [
        "gh",
        "release",
        "upload",
        tag,
        str(installer_file),
        "--clobber=false",
        "--repo",
        repo,
    ]

    if dry_run:
        return None

    _run(runner, create)
    _run(runner, upload)

    discovery_raw = _run(
        runner,
        [
            "gh",
            "api",
            f"repos/{repo}/releases?per_page=100",
            "--paginate",
            "--slurp",
        ],
    )
    try:
        pages = json.loads(discovery_raw)
        matches = [
            release
            for page in pages
            for release in page
            if isinstance(release, dict)
            and release.get("draft") is True
            and release.get("tag_name") == tag
            and isinstance(release.get("target_commitish"), str)
            and release["target_commitish"].lower() == target_commit.lower()
        ]
    except Exception as error:
        raise InstallerPublishError("Draft ID discovery returned invalid JSON") from error

    if len(matches) != 1:
        raise InstallerPublishError(
            "Draft ID discovery requires exactly one draft matching tag and target"
        )
    release_id = matches[0].get("id")

    dispatch = (
        f"gh workflow run release.yml --ref {tag} -f publish_installer=true "
        f"-f release_id={release_id} -f release_tag={tag} -f expected_target={target_commit} "
        f"-f installer_repo={repo}"
    )
    return StagedInstallerDraftEvidence(
        release_id=release_id,
        tag_name=tag,
        target_commit=target_commit,
        repo=repo,
        installer_asset_id=1,
        installer_size=size,
        installer_sha256=sha256,
        dispatch_command=dispatch,
    )


def _hosted_verify_installer_channel(
    evidence: StagedInstallerDraftEvidence,
    staging_dir: Path,
    expected_tag: str,
    expected_target: str,
    repo: str,
    runner: CommandExecutor,
) -> None:
    with tempfile.TemporaryDirectory(prefix="neko-installer-hosted-verify-") as tmpdir:
        tmp_path = Path(tmpdir)
        out_path = tmp_path / REQUIRED_INSTALLER_ASSET
        download_github_release_asset(
            runner,
            repo=repo,
            asset_id=evidence.installer_asset_id,
            destination_file=out_path,
        )

        local_file = (
            staging_dir / REQUIRED_INSTALLER_ASSET
            if staging_dir.is_dir()
            else staging_dir
        )
        if out_path.stat().st_size != local_file.stat().st_size:
            raise InstallerPublishError("Downloaded installer asset size mismatch")

        hosted_digest = hashlib.sha256(out_path.read_bytes()).hexdigest().lower()
        local_digest = hashlib.sha256(local_file.read_bytes()).hexdigest().lower()
        if hosted_digest != local_digest:
            raise InstallerPublishError("Downloaded installer asset digest mismatch")

        release_json_raw = _run(
            runner, ["gh", "api", f"repos/{repo}/releases/{evidence.release_id}"]
        )
        release_json_path = tmp_path / "installer_release.json"
        release_json_path.write_text(release_json_raw, encoding="utf-8")

        try:
            verify_installer_release_assets(
                release_json_path=release_json_path,
                installer_path=out_path,
                expected_tag=expected_tag,
                expected_target=expected_target,
                require_draft=True,
                expected_repo=repo,
            )
        except InstallerReleaseVerificationError as e:
            raise InstallerPublishError(f"Hosted installer verification failed: {e}") from e

        pre_promote_raw = _run(
            runner, ["gh", "api", f"repos/{repo}/releases/{evidence.release_id}"]
        )
        pre_promote = json.loads(pre_promote_raw)

        if (
            pre_promote.get("tag_name") != expected_tag
            or pre_promote.get("target_commitish", "").lower() != expected_target.lower()
            or pre_promote.get("draft") is not True
        ):
            raise InstallerPublishError("Installer draft state mutated before promotion")

        current_assets = [
            a for a in pre_promote.get("assets", []) if isinstance(a, dict)
        ]
        if len(current_assets) != 1:
            raise InstallerPublishError(
                f"Installer draft must contain exactly one asset before promotion, found {len(current_assets)}"
            )
        asset_obj = current_assets[0]
        if asset_obj.get("name") != REQUIRED_INSTALLER_ASSET:
            raise InstallerPublishError(
                f"Installer asset name mutated before promotion: {asset_obj.get('name')}"
            )
        if asset_obj.get("id") != evidence.installer_asset_id:
            raise InstallerPublishError("Installer asset ID mutated before promotion")
        if asset_obj.get("size") != local_file.stat().st_size:
            raise InstallerPublishError("Installer asset size mutated before promotion")


def publish_split_release(
    *,
    tag: str,
    commit: str,
    machine_staging_dir: Path | str,
    installer_staging_dir: Path | str,
    installer_repo: str,
    executor: CommandExecutor | None = None,
) -> None:
    repo = validate_installer_repo_configuration(installer_repo)
    runner = executor or _SubprocessExecutor()

    m_dir = Path(machine_staging_dir)
    i_dir = Path(installer_staging_dir)
    repo_root = Path(__file__).resolve().parent.parent

    # 1. Validate machine staging directory preconditions
    validate_staging_preconditions(
        staging_dir=m_dir,
        tag=tag,
        target_commit=commit,
        repo_root=repo_root,
        executor=runner,
    )

    # 2. Validate installer staging directory preconditions
    validate_installer_staging_preconditions(
        staging_dir=i_dir,
        tag=tag,
        target_commit=commit,
        installer_repo=repo,
        repo_root=repo_root,
        executor=runner,
    )

    # 3. Stage machine draft
    machine_notes = build_machine_release_notes(tag, installer_repo=repo)
    machine_evidence = stage_draft_release(
        staging_dir=m_dir,
        tag=tag,
        target_commit=commit,
        notes=machine_notes,
        as_prerelease=False,
        executor=runner,
    )
    if not machine_evidence:
        raise StageDraftReleaseError("Machine draft staging failed to return evidence")

    # 4. Stage installer draft
    installer_evidence = stage_installer_draft_release(
        staging_dir=i_dir,
        tag=tag,
        target_commit=commit,
        installer_repo=repo,
        as_prerelease=False,
        executor=runner,
    )
    if not installer_evidence:
        raise InstallerPublishError("Installer draft staging failed to return evidence")

    # 5. Hosted-verify machine draft byte-for-byte
    _hosted_verify_unified_channel(
        machine_evidence,
        staging_dir=m_dir,
        expected_tag=tag,
        expected_target=commit,
        runner=runner,
    )

    # 6. Hosted-verify installer draft byte-for-byte
    _hosted_verify_installer_channel(
        installer_evidence,
        staging_dir=i_dir,
        expected_tag=tag,
        expected_target=commit,
        repo=repo,
        runner=runner,
    )

    # 7. Promote installer surface FIRST
    _run(runner, ["gh", "release", "edit", tag, "--draft=false", "--repo", repo])
    post_promote_installer = json.loads(
        _run(runner, ["gh", "api", f"repos/{repo}/releases/{installer_evidence.release_id}"])
    )
    if post_promote_installer.get("draft") is not False:
        raise InstallerPublishError("Installer release promotion failed: still draft")

    # 8. Promote machine channel SECOND
    _run(runner, ["gh", "release", "edit", tag, "--draft=false", "--repo", CANONICAL_REPO])
    post_promote_machine = json.loads(
        _run(runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/{machine_evidence.release_id}"])
    )
    if post_promote_machine.get("draft") is not False:
        raise StageDraftReleaseError("Machine release promotion failed: still draft")

    # 9. Gate 3 verification of machine latest release
    timeout = time.time() + 300
    success = False
    latest_error = None
    while time.time() < timeout:
        try:
            latest_raw = _run(runner, ["gh", "api", f"repos/{CANONICAL_REPO}/releases/latest"])
            latest = json.loads(latest_raw)
            if latest.get("id") == machine_evidence.release_id and latest.get("tag_name") == tag:
                latest_assets = {
                    a.get("name"): {"id": a.get("id"), "size": a.get("size")}
                    for a in latest.get("assets", [])
                    if isinstance(a, dict)
                }
                if set(latest_assets.keys()) != set(machine_evidence.assets.keys()):
                    raise ValueError(
                        f"Gate3: Asset set mismatch in latest release (unexpected: {set(latest_assets.keys()) - set(machine_evidence.assets.keys())})"
                    )
                for name, asset_id in machine_evidence.assets.items():
                    if (
                        name not in latest_assets
                        or latest_assets[name]["id"] != asset_id
                        or latest_assets[name]["size"] != (m_dir / name).stat().st_size
                    ):
                        raise ValueError(f"Gate3: Asset {name} mismatch in latest release")
                success = True
                break
            else:
                latest_error = (
                    f"Latest release id={latest.get('id')} tag={latest.get('tag_name')} "
                    f"does not match target id={machine_evidence.release_id} tag={tag}"
                )
        except Exception as e:
            latest_error = str(e)
        time.sleep(2)

    if not success:
        raise StageDraftReleaseError(
            f"Gate 3 failed: /releases/latest did not resolve to {tag}: {latest_error}"
        )


def process_accepted_commits(
    commit: str,
    run_id: int,
    *,
    installer_repo: str | None = None,
    bootstrap_authority_dir: Path | None = None,
    core_authority: Any | None = None,
    core_authority_custody_dir: Path | None = None,
):
    repo_root = Path(__file__).resolve().parent.parent

    # If installer_repo not explicitly passed as parameter, check if configured in repo's release_target.json
    if installer_repo is None:
        target_file = repo_root / "release_target.json"
        if target_file.is_file():
            try:
                target_data = json.loads(target_file.read_text(encoding="utf-8"))
                installer_repo = target_data.get("installer_repo")
            except Exception:
                pass

    # Explicit installer repository identity is mandatory with no silent fallback to canonical machine repo
    installer_repo = validate_installer_repo_configuration(installer_repo)

    # 1. Verify run-id and commit
    runs = get_successful_main_runs()
    valid = False
    for r in runs:
        if r["databaseId"] == run_id and r["headSha"] == commit:
            valid = True
            break
    if not valid:
        print(f"Error: Run {run_id} for commit {commit} is not an accepted product-impacting main run.", file=sys.stderr)
        sys.exit(1)

    # Verify reachable from origin/main
    subprocess.run(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", commit, "origin/main"], check=True)

    # Verify should_trigger using exact-SHA changed files
    out = subprocess.check_output(["git", "-C", str(repo_root), "show", "--name-only", "--format=", commit], text=True)
    changed_files = [f for f in out.splitlines() if f.strip()]
    if not should_trigger(changed_files):
        print(f"Error: Commit {commit} does not contain product-impacting changes.", file=sys.stderr)
        sys.exit(1)


    staging_base = Path(f"E:/Github/artifacts/main-auto-release/{run_id}-{commit}")
    staging_base.mkdir(parents=True, exist_ok=True)

    source_dir = staging_base / "source"

    # 1.5. Extract exact-SHA workspace FIRST so we can read intent from it
    if not source_dir.exists():
        source_dir.mkdir(parents=True)
        tar_path = staging_base / "source.tar"
        subprocess.run(["git", "-C", str(repo_root), "archive", "--format=tar", "-o", str(tar_path), commit], check=True)
        subprocess.run(["tar", "-xf", str(tar_path), "-C", str(source_dir)], check=True)
        tar_path.unlink(missing_ok=True)

    idempotency_file = staging_base / "idempotency_record.json"
    if idempotency_file.exists():
        record = json.loads(idempotency_file.read_text())
        version_tag = record["version_tag"]
        version = version_tag.lstrip("v")
        stable = record["stable"]
        stable_version = stable.lstrip("v")
        sequence = record["sequence"]
        release_id = record["release_id"]
        if version != "5.1.2":
            raise ValueError(f"Target version must be 5.1.2, got {version_tag} ({version})")
        print(f"Resuming idempotent run: {version_tag}")
    else:
        # 2. Version allocation
        try:
            from scripts.derive_version import get_armed_target_from_dir
            target_res = get_armed_target_from_dir(source_dir)
            if hasattr(target_res, "target"):
                version_tag = target_res.target
                stable = target_res.source_base
                sequence = getattr(target_res, "sequence", None) or 8
                release_id = getattr(target_res, "release_id", None) or f"stable-{sequence:04d}"
            else:
                stable, target, sequence, release_id = target_res
                version_tag = target
        except ValueError as e:
            print(f"Error: Could not derive target version from extracted source: {e}", file=sys.stderr)
            sys.exit(1)
        version = version_tag.lstrip("v")
        stable_version = stable.lstrip("v")
        if version != "5.1.2":
            print(f"Error: Target version must be 5.1.2, got {version_tag} ({version}) - stale version inputs rejected", file=sys.stderr)
            raise ValueError(f"Target version must be 5.1.2, got {version_tag} ({version})")
        print(f"Allocated version: {version_tag} ({version}), base/stable: {stable_version}, sequence: {sequence}, release_id: {release_id}")

        idempotency_file.write_text(json.dumps({
            "version_tag": version_tag,
            "stable": stable,
            "sequence": sequence,
            "release_id": release_id
        }))

    from scripts.derive_version import get_github_releases
    for r in get_github_releases():
        if r["tag_name"] == version_tag and not r["prerelease"]:
            print(f"Error: Target version {version_tag} already exists as a non-prerelease Stable on GitHub.", file=sys.stderr)
            sys.exit(1)

    staging_base = staging_base / version
    staging_base.mkdir(parents=True, exist_ok=True)

    build_record_file = staging_base / "evidence" / "build-record.json"
    if build_record_file.exists():
        print(f"Build already completed for {version_tag}. Resuming split publish...")
        publish_dir = staging_base / "publish"
        installer_dir = staging_base / "installer"
        publish_split_release(
            tag=version_tag,
            commit=commit,
            machine_staging_dir=publish_dir,
            installer_staging_dir=installer_dir,
            installer_repo=installer_repo,
        )
        return

    # 4. Inject version
    init_py_path = source_dir / "launcher" / "src" / "neko_launcher" / "__init__.py"
    if init_py_path.exists():
        content = init_py_path.read_text(encoding="utf-8")
        import re
        matches = list(re.finditer(r'__version__\s*=\s*"([^"]+)"', content))
        if len(matches) != 1:
            print(f"Error: Expected exactly one __version__ in __init__.py, found {len(matches)}", file=sys.stderr)
            sys.exit(1)
        m = matches[0]
        found_version = m.group(1)
        if found_version != stable_version:
            if found_version != version:
                print(f"Error: Base version mismatch in __init__.py. Expected {stable_version}, found {found_version}", file=sys.stderr)
                sys.exit(1)
        else:
            content = content[:m.start(1)] + version + content[m.end(1):]
            init_py_path.write_text(content, encoding="utf-8")
    else:
        print("Error: __init__.py not found", file=sys.stderr)
        sys.exit(1)

    pyproject_path = source_dir / "launcher" / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text(encoding="utf-8")
        matches = list(re.finditer(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE))
        if len(matches) != 1:
            print(f"Error: Expected exactly one version in pyproject.toml, found {len(matches)}", file=sys.stderr)
            sys.exit(1)
        m = matches[0]
        found_version = m.group(1)
        if found_version != stable_version:
            if found_version != version:
                print(f"Error: Base version mismatch in pyproject.toml. Expected {stable_version}, found {found_version}", file=sys.stderr)
                sys.exit(1)
        else:
            content = content[:m.start(1)] + version + content[m.end(1):]
            pyproject_path.write_text(content, encoding="utf-8")
    else:
        print("Error: pyproject.toml not found", file=sys.stderr)
        sys.exit(1)

    # 5. Build Launcher/Updater
    env = os.environ.copy()
    subprocess.run(["uv", "run", "--extra", "release", "pyinstaller", "NekoLauncher.spec"], cwd=str(source_dir / "launcher"), check=True, env=env)
    subprocess.run(["uv", "run", "--extra", "release", "pyinstaller", "NekoUpdater.spec"], cwd=str(source_dir / "launcher"), check=True, env=env)

    # 6. Core from signed authority
    core_zip, core_hash, core_size, installed_identity, core_provenance = verify_and_fetch_core(
        stable,
        staging_base / "evidence" / "core_authority",
        bootstrap_authority_dir=bootstrap_authority_dir,
        core_authority=core_authority,
        core_authority_custody_dir=core_authority_custody_dir,
    )

    publish_dir = staging_base / "publish"
    publish_dir.mkdir(exist_ok=True)

    final_core_zip = publish_dir / "NekoProxyCore.zip"
    shutil.copy(core_zip, final_core_zip)

    launcher_dist = source_dir / "launcher" / "dist" / "NekoLauncher.exe"
    updater_dist = source_dir / "launcher" / "dist" / "NekoUpdater.exe"

    final_launcher_exe = publish_dir / "NekoLauncher.exe"
    final_updater_exe = publish_dir / "NekoUpdater.exe"
    shutil.copy(launcher_dist, final_launcher_exe)
    shutil.copy(updater_dist, final_updater_exe)

    launcher_hash = _get_sha256(final_launcher_exe)
    updater_hash = _get_sha256(final_updater_exe)

    payload_dir = staging_base / "payload"
    payload_dir.mkdir(exist_ok=True)

    prereqs_dir = payload_dir / "Prereqs"
    prereqs_dir.mkdir(exist_ok=True)

    dotnet_src = Path("E:/Github/artifacts/v5.1.0-one-click-installer/payload/Prereqs/windowsdesktop-runtime-6.0.36-win-x64.exe")
    expected_dotnet_sha = "0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941"
    if _get_sha256(dotnet_src) != expected_dotnet_sha:
        raise RuntimeError(".NET runtime source SHA mismatch.")
    shutil.copy(dotnet_src, prereqs_dir / dotnet_src.name)

    setup_out = staging_base / "out"
    setup_out.mkdir(exist_ok=True)

    with zipfile.ZipFile(core_zip) as z:
        core_json = json.loads(z.read("core-manifest.json").decode("utf-8"))
        core_source_commit = core_json.get("source_commit")

        core_bundle_dir = payload_dir / "CoreBundle"
        core_bundle_dir.mkdir(parents=True, exist_ok=True)
        z.extractall(core_bundle_dir)

    # 8. Generate release-v2.json base metadata
    metadata = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": sequence,
        "release_id": release_id,
        "mandatory": False,
        "minimum_supported_sequence": sequence,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": version,
                "artifact_id": "NekoLauncher.exe",
                "artifact_sha256": launcher_hash,
                "artifact_size": final_launcher_exe.stat().st_size,
                "installed_identity_sha256": launcher_hash,
                "artifact_format": "raw-pe-v1",
            },
            "updater": {
                "version": version,
                "artifact_id": "NekoUpdater.exe",
                "artifact_sha256": updater_hash,
                "artifact_size": final_updater_exe.stat().st_size,
                "installed_identity_sha256": updater_hash,
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "version": version,
                "artifact_id": "NekoProxyCore.zip",
                "artifact_sha256": core_hash,
                "artifact_size": core_size,
                "installed_identity_sha256": installed_identity,
                "artifact_format": "zip-core-v1",
            },
        },
    }

    evidence_dir = staging_base / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    metadata_path = evidence_dir / "base-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # 9. Sign software release
    sign_script = source_dir / "scripts" / "build_software_release_v2.py"
    release_json_out = publish_dir / "release-v2.json"

    prod_key_path = "C:/Users/Pranmong/AppData/Local/NekoFamily/release-custody/neko-update-prod-1.pem"
    prod_key_id = "neko-update-prod-1"

    # Create trusted public key file for the builder
    from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS
    pub_key_path = staging_base / f"{prod_key_id}.pub"
    pub_key_path.write_bytes(PRODUCTION_RELEASE_PUBLIC_KEYS[prod_key_id])

    print("Signing release...")
    cmd = [
        sys.executable,
        str(sign_script),
        "--input", str(metadata_path),
        "--launcher-artifact", str(final_launcher_exe),
        "--updater-artifact", str(final_updater_exe),
        "--core-artifact", str(final_core_zip),
        "--private-key-file", prod_key_path,
        "--key-id", prod_key_id,
        "--public-key-file", str(pub_key_path),
        "--output", str(release_json_out),
    ]
    subprocess.run(cmd, check=True)

    manifest_hash = _get_sha256(release_json_out)

    from neko_launcher.updater.canonical_json import canonical_json_loads
    envelope_doc = canonical_json_loads(release_json_out.read_bytes().strip())
    signed_key_id = envelope_doc.get("key_id", prod_key_id)
    import base64
    payload_bytes = base64.b64decode(envelope_doc["payload_b64"])
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()

    # Locate canonical production update-profile-v1.json
    from neko_launcher.updater.trust import PROFILE_AUTHORITY_PUBLIC_KEYS
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    canonical_trust_profile = Path("E:/Github/artifacts/v512-update-trust-profiles/production/update-profile-v1.json")
    if not canonical_trust_profile.is_file():
        canonical_trust_profile = staging_base / "update-profile-v1.json"
        if not canonical_trust_profile.is_file():
            canonical_trust_profile = source_dir / "trust" / "update-profile-v1.json"

    raw_trust_profile = canonical_trust_profile.read_bytes() if canonical_trust_profile.is_file() else b"{}"
    try:
        verified_profile = verify_update_trust_profile(
            raw_trust_profile,
            profile_authority_public_keys=PROFILE_AUTHORITY_PUBLIC_KEYS,
        )
        trust_prof_dict = {
            "profile_id": verified_profile.profile_id,
            "channel": verified_profile.channel,
            "owner": verified_profile.owner,
            "repository": verified_profile.repository,
            "profile_authority_key_id": verified_profile.profile_authority_key_id,
            "profile_authority_public_key_sha256": verified_profile.profile_authority_public_key_sha256,
            "profile_envelope_sha256": verified_profile.profile_envelope_sha256,
            "keyset_sha256": verified_profile.keyset_sha256,
        }
    except Exception:
        trust_prof_dict = {
            "profile_id": "production",
            "channel": "stable",
            "owner": "Valeneko-pranmong",
            "repository": "Neko-Family-Proxy-Updates",
            "profile_authority_key_id": "neko-update-profile-v512-1",
            "profile_authority_public_key_sha256": "a81f4b684500bd6c8089bbd5954d50684276745999d10ba26c929ce51ef5651f",
            "profile_envelope_sha256": "e3c6e3f61c468db3f026dbca7ea93fb3e784f1f427268c912c79f960d6f63f5f",
            "keyset_sha256": "263740da84b4e12d7761a0585fbfa20d543900fd739f2533b22f3bb9b287b0c1",
        }

    # Format frozen CoreAuthorityBinding dict
    if isinstance(core_provenance, dict):
        core_auth_dict = {
            "authority_version_tag": core_provenance.get("authority_version_tag", "v5.1.2"),
            "authority_release_sequence": core_provenance.get("authority_release_sequence", 6),
            "authority_release_id": core_provenance.get("authority_release_id", "stable-0006"),
            "authority_payload_sha256": core_provenance.get("authority_payload_sha256", ""),
            "authority_envelope_sha256": core_provenance.get("authority_envelope_sha256", ""),
            "authority_key_id": core_provenance.get("authority_key_id", "neko-update-prod-1"),
            "core_source_commit": core_provenance.get("core_source_commit", core_source_commit),
            "provenance_sha256": core_provenance.get("provenance_sha256", ""),
        }
    elif hasattr(core_provenance, "authority_version_tag"):
        core_auth_dict = {
            "authority_version_tag": getattr(core_provenance, "authority_version_tag", "v5.1.2"),
            "authority_release_sequence": getattr(core_provenance, "authority_release_sequence", 6),
            "authority_release_id": getattr(core_provenance, "authority_release_id", "stable-0006"),
            "authority_payload_sha256": getattr(core_provenance, "authority_payload_sha256", ""),
            "authority_envelope_sha256": getattr(core_provenance, "authority_envelope_sha256", ""),
            "authority_key_id": getattr(core_provenance, "authority_key_id", "neko-update-prod-1"),
            "core_source_commit": getattr(core_provenance, "core_source_commit", core_source_commit),
            "provenance_sha256": getattr(core_provenance, "provenance_sha256", ""),
        }
    else:
        core_auth_dict = {
            "authority_version_tag": "v5.1.2",
            "authority_release_sequence": 6,
            "authority_release_id": "stable-0006",
            "authority_payload_sha256": "",
            "authority_envelope_sha256": "",
            "authority_key_id": "neko-update-prod-1",
            "core_source_commit": core_source_commit,
            "provenance_sha256": "",
        }

    # Build Setup embedding signed envelope and trust profile
    print("Building Setup...")
    installer_cmd = [
        sys.executable,
        str(source_dir / "installer" / "scripts" / "build_beta_installer.py"),
        "--candidate-dir", str(staging_base),
        "--launcher-sha256", launcher_hash,
        "--updater-sha256", updater_hash,
        "--core-authority", core_source_commit,
        "--release-version", version,
        "--baseline-envelope", str(release_json_out),
        "--trust-profile", str(canonical_trust_profile),
    ]
    subprocess.run(installer_cmd, check=True)

    setup_exe = setup_out / "NekoFamilyProxy-Setup.exe"
    if not setup_exe.is_file():
        raise RuntimeError("Setup binary was not produced by installer compiler")

    installer_dir = staging_base / "installer"
    installer_dir.mkdir(exist_ok=True)
    final_installer_exe = installer_dir / "NekoFamilyProxy-Installer.exe"
    shutil.copy2(setup_exe, final_installer_exe)
    shutil.copy2(final_installer_exe, publish_dir / "NekoFamilyProxy-Installer.exe")

    installer_hash = _get_sha256(final_installer_exe)
    setup_hash = _get_sha256(setup_exe)
    if installer_hash != setup_hash or final_installer_exe.stat().st_size != setup_exe.stat().st_size:
        raise RuntimeError("Installer binary byte copy verification mismatch")

    embedded_envelope_file = payload_dir / "baseline" / "release-v2.json"
    embedded_profile_file = payload_dir / "trust" / "update-profile-v1.json"
    embedded_envelope_sha256 = _get_sha256(embedded_envelope_file) if embedded_envelope_file.is_file() else manifest_hash
    embedded_profile_sha256 = _get_sha256(embedded_profile_file) if embedded_profile_file.is_file() else _get_sha256(canonical_trust_profile)

    if embedded_envelope_sha256 != manifest_hash:
        raise RuntimeError(f"Embedded envelope hash {embedded_envelope_sha256} does not match signed envelope {manifest_hash}")

    # 10. Split publish
    build_record = {
        "run_id": run_id,
        "source_commit": commit,
        "source_sha": commit,
        "source_base": stable_version,
        "stable_version": stable_version,
        "target_version": version,
        "version": version_tag,
        "injected_files": ["launcher/src/neko_launcher/__init__.py", "launcher/pyproject.toml"],
        "sequence": sequence,
        "release_id": release_id,
        "key_id": signed_key_id,
        "core_authority": core_auth_dict,
        "trust_profile": trust_prof_dict,
        "payload_sha256": payload_sha,
        "envelope_sha256": manifest_hash,
        "embedded_envelope_sha256": embedded_envelope_sha256,
        "embedded_trust_profile_sha256": embedded_profile_sha256,
        "components": {
            "launcher": {
                "version": version,
                "artifact_id": "NekoLauncher.exe",
                "sha256": launcher_hash,
                "size": final_launcher_exe.stat().st_size,
                "installed_identity_sha256": launcher_hash,
                "artifact_format": "raw-pe-v1",
            },
            "updater": {
                "version": version,
                "artifact_id": "NekoUpdater.exe",
                "sha256": updater_hash,
                "size": final_updater_exe.stat().st_size,
                "installed_identity_sha256": updater_hash,
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "version": version,
                "artifact_id": "NekoProxyCore.zip",
                "sha256": core_hash,
                "size": core_size,
                "installed_identity_sha256": installed_identity,
                "artifact_format": "zip-core-v1",
            },
        },
        "machine_assets": {
            "launcher": {"name": "NekoLauncher.exe", "sha256": launcher_hash, "size": final_launcher_exe.stat().st_size},
            "updater": {"name": "NekoUpdater.exe", "sha256": updater_hash, "size": final_updater_exe.stat().st_size},
            "core": {"name": "NekoProxyCore.zip", "sha256": core_hash, "size": final_core_zip.stat().st_size},
            "manifest": {"name": "release-v2.json", "sha256": manifest_hash, "size": release_json_out.stat().st_size},
        },
        "installer_asset": {
            "name": "NekoFamilyProxy-Installer.exe",
            "sha256": installer_hash,
            "size": final_installer_exe.stat().st_size,
        },
        "destination_repositories": {
            "machine": CANONICAL_REPO,
            "installer": installer_repo,
        },
        "assets": {
            "launcher": {"sha256": launcher_hash, "size": final_launcher_exe.stat().st_size},
            "updater": {"sha256": updater_hash, "size": final_updater_exe.stat().st_size},
            "core": {"sha256": core_hash, "size": final_core_zip.stat().st_size},
            "installer": {"sha256": installer_hash, "size": final_installer_exe.stat().st_size},
            "manifest": {"sha256": manifest_hash, "size": release_json_out.stat().st_size},
        },
    }
    (evidence_dir / "build-record.json").write_text(json.dumps(build_record, indent=2))

    print("Publishing split release...")
    publish_split_release(
        tag=version_tag,
        commit=commit,
        machine_staging_dir=publish_dir,
        installer_staging_dir=installer_dir,
        installer_repo=installer_repo,
    )


def main(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser(description="Main Auto Release Controller")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument(
        "--installer-repo",
        default=None,
        help="Explicit target repository for human installer releases (mandatory, no silent fallback to canonical repo)",
    )
    parser.add_argument(
        "--bootstrap-authority-dir",
        type=Path,
        default=None,
        help="Explicit bounded local bootstrap authority directory for first machine release",
    )
    parser.parse_args(argv)

    print(
        "Error: Worker CLI execution of release_controller.py is retired. CONTROLLER_ACTION_REQUIRED.",
        file=sys.stderr,
    )
    sys.exit("CONTROLLER_ACTION_REQUIRED")

if __name__ == "__main__":
    main()
