"""Offline fresh baseline enrollment from exact embedded signed release envelope."""
from __future__ import annotations

import base64
from ctypes import wintypes
import dataclasses
from dataclasses import dataclass
from pathlib import Path
import secrets
import shutil
from typing import Any

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
)
from neko_launcher.infrastructure.software_release_identity import sha256_file
from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads
from neko_launcher.updater.enrollment import (
    enroll_state_directory,
    load_selected_state,
    validate_enrollment_trust_binding,
    write_enrollment_marker,
)
from neko_launcher.updater.manifest_v2 import (
    UPDATER_PROTOCOL_VERSION,
    verify_release_envelope_v2,
)
from neko_launcher.updater.slot_selector import SelectionStatus
from neko_launcher.updater.slot_store import SlotStore
from neko_launcher.updater.state_models import (
    Binding,
    EnrollmentMarker,
    Generation,
    RootIdentity,
    State,
)
from neko_launcher.updater.trust_profile import VerifiedUpdateTrustProfile
from neko_launcher.updater.win32_directory import (
    _CloseHandle,
    get_directory_identity,
    open_directory_guarded,
)


@dataclass(frozen=True)
class BaselineEnrollmentResult:
    enrolled: bool
    binding: AuthenticatedReleaseBinding | None = None
    error: str | None = None


def _resolve_root_identity(install_root: Path) -> RootIdentity:
    """Resolve filesystem volume serial and file id into RootIdentity."""
    try:
        handle = open_directory_guarded(install_root)
        try:
            dir_id = get_directory_identity(handle)
            return RootIdentity(
                volume_serial=dir_id.volume_serial,
                file_id=dir_id.file_id,
            )
        finally:
            _CloseHandle(wintypes.HANDLE(handle))
    except Exception:
        st = install_root.stat()
        vol_hex = f"{(getattr(st, 'st_dev', 0) & 0xFFFFFFFFFFFFFFFF):016x}"
        ino_hex = f"{(getattr(st, 'st_ino', 0) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF):032x}"
        return RootIdentity(volume_serial=vol_hex, file_id=ino_hex)


def enroll_baseline_from_signed_envelope(
    *,
    install_root: Path,
    envelope_path: Path,
    trust_profile: VerifiedUpdateTrustProfile,
) -> BaselineEnrollmentResult:
    """Enroll an offline baseline from an exact embedded signed envelope."""
    if not isinstance(trust_profile, VerifiedUpdateTrustProfile):
        raise TypeError(
            f"trust_profile must be VerifiedUpdateTrustProfile, got {type(trust_profile).__name__}"
        )

    if not isinstance(install_root, Path):
        install_root = Path(install_root)
    if not isinstance(envelope_path, Path):
        envelope_path = Path(envelope_path)

    if not install_root.is_dir():
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=f"Install root directory not found: {install_root}",
        )

    if not envelope_path.is_file():
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=f"Baseline envelope file not found: {envelope_path}",
        )

    try:
        raw_envelope_bytes = envelope_path.read_bytes()
        envelope_doc: Any = canonical_json_loads(raw_envelope_bytes.strip())
        if not isinstance(envelope_doc, dict):
            return BaselineEnrollmentResult(
                enrolled=False,
                binding=None,
                error="Envelope document must be a JSON object",
            )
    except Exception as exc:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=f"Failed to parse envelope JSON: {exc}",
        )

    try:
        release_set, verified_payload_sha = verify_release_envelope_v2(
            envelope_doc,
            dict(trust_profile.release_public_keys),
        )
    except Exception as exc:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=f"Release envelope verification failed: {exc}",
        )

    if release_set.channel != trust_profile.channel:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=(
                f"Release channel {release_set.channel!r} does not match "
                f"trust profile channel {trust_profile.channel!r}"
            ),
        )

    if not (
        release_set.updater_protocol.minimum
        <= UPDATER_PROTOCOL_VERSION
        <= release_set.updater_protocol.maximum
    ):
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=(
                f"Unsupported updater protocol: current is {UPDATER_PROTOCOL_VERSION}, "
                f"release requires {release_set.updater_protocol.minimum}..{release_set.updater_protocol.maximum}"
            ),
        )

    launcher_comp = release_set.components.get("launcher")
    if launcher_comp is None:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error="Release envelope missing launcher component",
        )
    launcher_file = install_root / launcher_comp.artifact_id
    if not launcher_file.is_file():
        launcher_file = install_root / "NekoLauncher.exe"
    if not launcher_file.is_file():
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=f"Installed Launcher executable not found at {launcher_file}",
        )
    if sha256_file(launcher_file) != launcher_comp.installed_identity_sha256:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error="Launcher installed identity does not match signed release envelope",
        )

    updater_comp = release_set.components.get("updater")
    if updater_comp is None:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error="Release envelope missing updater component",
        )
    updater_file = install_root / updater_comp.artifact_id
    if not updater_file.is_file():
        updater_file = install_root / "NekoUpdater.exe"
    if not updater_file.is_file():
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=f"Installed Updater executable not found at {updater_file}",
        )
    if sha256_file(updater_file) != updater_comp.installed_identity_sha256:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error="Updater installed identity does not match signed release envelope",
        )

    core_comp = release_set.components.get("core")
    if core_comp is None:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error="Release envelope missing core component",
        )
    core_candidates = [
        install_root / "ProxyCore" / "core-manifest.json",
        install_root / "ProxyCore" / "canonical-core-manifest.json",
        install_root / "core-manifest.json",
        install_root / "CoreBundle" / "core-manifest.json",
    ]
    core_manifest_path = None
    for candidate in core_candidates:
        if candidate.is_file():
            core_manifest_path = candidate
            break
    if core_manifest_path is None:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error="Installed Core manifest not found",
        )
    if sha256_file(core_manifest_path) != core_comp.installed_identity_sha256:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error="Core installed identity does not match signed release envelope",
        )

    target_binding = AuthenticatedReleaseBinding(
        release_sequence=release_set.release_sequence,
        release_id=release_set.release_id,
        payload_sha256=verified_payload_sha,
    )

    state_dir = install_root / "state"
    if (
        state_dir.is_dir()
        and (state_dir / "slot-a.bin").is_file()
        and (state_dir / "slot-b.bin").is_file()
    ):
        try:
            existing_state = load_selected_state(state_dir, trust_profile.release_public_keys)
            if existing_state.committed is not None:
                ex_b = existing_state.committed.binding
                if ex_b.release_sequence == release_set.release_sequence:
                    if (
                        ex_b.payload_sha256 == verified_payload_sha
                        and ex_b.release_id == release_set.release_id
                    ):
                        if existing_state.enrollment_complete:
                            return BaselineEnrollmentResult(
                                enrolled=True,
                                binding=target_binding,
                                error=None,
                            )
                    else:
                        return BaselineEnrollmentResult(
                            enrolled=False,
                            binding=None,
                            error=(
                                f"Conflicting binding at sequence {release_set.release_sequence}: "
                                f"existing has payload {ex_b.payload_sha256} / {ex_b.release_id}, "
                                f"candidate has {verified_payload_sha} / {release_set.release_id}"
                            ),
                        )
                elif (
                    existing_state.highwater is not None
                    and existing_state.highwater.release_sequence > release_set.release_sequence
                ):
                    return BaselineEnrollmentResult(
                        enrolled=False,
                        binding=None,
                        error=(
                            f"Cannot enroll baseline at sequence {release_set.release_sequence}: "
                            f"existing highwater is {existing_state.highwater.release_sequence}"
                        ),
                    )
        except Exception:
            pass

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        root_identity = _resolve_root_identity(install_root)
        installation_id = secrets.token_hex(16)

        marker_path = state_dir / "enrollment.bin"
        if marker_path.is_file():
            try:
                existing_marker = validate_enrollment_trust_binding(install_root, trust_profile)
                installation_id = existing_marker.installation_id
            except Exception:
                pass

        marker = EnrollmentMarker(
            schema_version=1,
            installation_id=installation_id,
            root=root_identity,
            helper_sha256=updater_comp.installed_identity_sha256,
            helper_protocol=UPDATER_PROTOCOL_VERSION,
            keyset_sha256=trust_profile.keyset_sha256,
            bootstrap_payload_sha256=verified_payload_sha,
            enrollment_status="PREPARED",
            profile_id=trust_profile.profile_id,
            profile_envelope_sha256=trust_profile.profile_envelope_sha256,
        )

        write_enrollment_marker(state_dir, marker)

        envelope_canonical_bytes = canonical_json_dumps(envelope_doc)
        envelope_b64 = base64.b64encode(envelope_canonical_bytes).decode("ascii")
        evidence = {verified_payload_sha: envelope_b64}

        initial_state = State(
            schema_version=1,
            revision=1,
            installation_id=installation_id,
            helper_protocol=UPDATER_PROTOCOL_VERSION,
            enrollment_complete=False,
            phase="ENROLLING",
            committed=None,
            previous=None,
            highwater=None,
            observed=None,
            failed=None,
            transaction=None,
            cleanup=None,
            rollback=None,
            last_error=None,
            evidence=evidence,
        )

        enroll_state_directory(
            state_dir,
            marker,
            initial_state,
            trust_profile.release_public_keys,
        )

        state_binding = Binding(
            release_sequence=release_set.release_sequence,
            release_id=release_set.release_id,
            payload_sha256=verified_payload_sha,
        )
        generation = Generation(
            binding=state_binding,
            launcher_identity_sha256=launcher_comp.installed_identity_sha256,
            core_identity_sha256=core_comp.installed_identity_sha256,
        )

        store = SlotStore(
            state_dir / "slot-a.bin",
            state_dir / "slot-b.bin",
            dict(trust_profile.release_public_keys),
        )
        try:
            state_rev2 = State(
                schema_version=1,
                revision=2,
                installation_id=installation_id,
                helper_protocol=UPDATER_PROTOCOL_VERSION,
                enrollment_complete=False,
                phase="IDLE",
                committed=generation,
                previous=None,
                highwater=state_binding,
                observed=state_binding,
                failed=None,
                transaction=None,
                cleanup=None,
                rollback=None,
                last_error=None,
                evidence=evidence,
            )
            res2 = store.write_state(state_rev2)
            if res2.status != SelectionStatus.SELECTED:
                return BaselineEnrollmentResult(
                    enrolled=False,
                    binding=None,
                    error=f"Failed to transition state to rev 2: {res2.reason}",
                )

            state_rev3 = dataclasses.replace(
                state_rev2,
                revision=3,
                enrollment_complete=True,
            )
            res3 = store.write_state(state_rev3)
            if res3.status != SelectionStatus.SELECTED:
                return BaselineEnrollmentResult(
                    enrolled=False,
                    binding=None,
                    error=f"Failed to transition state to rev 3: {res3.reason}",
                )
        finally:
            store.close()

        # Populate initial releases generation folder so updater can find baseline generation
        try:
            old_id = f"g-{state_binding.release_sequence:020d}-{state_binding.payload_sha256}"
            gen_dir = install_root / "releases" / old_id
            gen_dir.mkdir(parents=True, exist_ok=True)
            gen_launcher = gen_dir / "NekoLauncher.exe"
            if launcher_file.is_file() and not gen_launcher.is_file():
                shutil.copy2(launcher_file, gen_launcher)
            gen_core = gen_dir / "ProxyCore"
            root_core = install_root / "ProxyCore"
            if root_core.is_dir() and not gen_core.is_dir():
                shutil.copytree(root_core, gen_core, dirs_exist_ok=True)
            env_target = gen_dir / "release-envelope.json"
            if not env_target.is_file():
                env_target.write_bytes(envelope_canonical_bytes)
        except Exception:
            pass

        return BaselineEnrollmentResult(
            enrolled=True,
            binding=target_binding,
            error=None,
        )
    except Exception as exc:
        return BaselineEnrollmentResult(
            enrolled=False,
            binding=None,
            error=f"Enrollment failed: {exc}",
        )
