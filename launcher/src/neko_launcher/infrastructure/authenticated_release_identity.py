from __future__ import annotations

import base64
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    LocalReleaseIdentity,
)
from neko_launcher.infrastructure.software_release_identity import sha256_file
from neko_launcher.updater.canonical_json import canonical_json_loads
from neko_launcher.updater.enrollment import validate_enrollment_trust_binding
from neko_launcher.updater.manifest_v2 import ReleaseSetV2, verify_release_envelope_v2
from neko_launcher.updater.slot_selector import SelectionStatus
from neko_launcher.updater.slot_store import SlotStore
from neko_launcher.updater.state_models import Binding
from neko_launcher.updater.trust_profile import VerifiedUpdateTrustProfile


class AuthenticatedReleaseIdentityError(ValueError):
    """Raised when authenticated local release identity cannot be read or verified fail-closed."""


class AuthenticatedReleaseIdentityReader:
    """Reads authenticated local release identity from durable updater state."""

    def __init__(self, trust_profile: VerifiedUpdateTrustProfile) -> None:
        if not isinstance(trust_profile, VerifiedUpdateTrustProfile):
            raise AuthenticatedReleaseIdentityError(
                f"trust_profile must be VerifiedUpdateTrustProfile, got {type(trust_profile).__name__}"
            )
        self._profile_id: str = trust_profile.profile_id
        self._profile_envelope_sha256: str = trust_profile.profile_envelope_sha256
        self._keyset_sha256: str = trust_profile.keyset_sha256
        self._trust_profile: VerifiedUpdateTrustProfile = trust_profile
        # Copy and freeze-map only release public keys; no authority keys or network seams
        raw_keys = dict(trust_profile.release_public_keys)
        self._keys: Mapping[str, bytes] = MappingProxyType(raw_keys)

    def _verify_envelope_evidence(
        self,
        binding: Binding,
        evidence: Mapping[str, str],
        label: str,
    ) -> ReleaseSetV2:
        payload_sha = binding.payload_sha256
        if payload_sha not in evidence:
            raise AuthenticatedReleaseIdentityError(
                f"Missing signed envelope evidence for {label} payload {payload_sha}"
            )

        envelope_b64 = evidence[payload_sha]
        try:
            envelope_bytes = base64.b64decode(envelope_b64, validate=True)
            envelope_doc = canonical_json_loads(envelope_bytes)
            if not isinstance(envelope_doc, dict):
                raise ValueError("Envelope document must be a JSON object")
            release_set_v2, verified_payload_sha = verify_release_envelope_v2(
                envelope_doc,
                self._keys,
            )
        except Exception as exc:
            raise AuthenticatedReleaseIdentityError(
                f"Envelope verification failed for {label} binding: {exc}"
            ) from exc

        if verified_payload_sha != payload_sha:
            raise AuthenticatedReleaseIdentityError(
                f"Payload SHA mismatch for {label}: expected {payload_sha}, got {verified_payload_sha}"
            )
        if release_set_v2.release_sequence != binding.release_sequence:
            raise AuthenticatedReleaseIdentityError(
                f"Release sequence mismatch for {label}: expected {binding.release_sequence}, "
                f"got {release_set_v2.release_sequence}"
            )
        if release_set_v2.release_id != binding.release_id:
            raise AuthenticatedReleaseIdentityError(
                f"Release ID mismatch for {label}: expected {binding.release_id!r}, "
                f"got {release_set_v2.release_id!r}"
            )

        return release_set_v2

    def read(self, install_root: Path) -> LocalReleaseIdentity:
        """Read and verify the durable state identity fail-closed."""
        if not isinstance(install_root, Path):
            install_root = Path(install_root)

        # 1. Require fixed enrollment marker to match the exact profile pins
        try:
            marker = validate_enrollment_trust_binding(
                install_root,
                self._trust_profile,
            )
        except Exception as exc:
            raise AuthenticatedReleaseIdentityError(
                f"Enrollment trust binding validation failed: {exc}"
            ) from exc

        if (
            marker.profile_id != self._profile_id
            or marker.profile_envelope_sha256 != self._profile_envelope_sha256
            or marker.keyset_sha256 != self._keyset_sha256
        ):
            raise AuthenticatedReleaseIdentityError(
                "Enrollment marker trust pins do not match trust profile"
            )

        # 2. Select authoritative state from slots using profile release keys
        state_dir = install_root / "state"
        slot_a_path = state_dir / "slot-a.bin"
        slot_b_path = state_dir / "slot-b.bin"

        store: SlotStore | None = None
        try:
            store = SlotStore(slot_a_path, slot_b_path, self._keys)
            selection = store.load()
        except Exception as exc:
            raise AuthenticatedReleaseIdentityError(
                f"Failed to load slot store: {exc}"
            ) from exc
        finally:
            if store is not None:
                store.close()

        # 3. Require SELECTED status, non-null state, enrollment complete, and committed + highwater
        if selection.status != SelectionStatus.SELECTED or selection.state is None:
            raise AuthenticatedReleaseIdentityError(
                f"Slot selection status is {selection.status}: {selection.reason}"
            )

        state = selection.state
        if not state.enrollment_complete:
            raise AuthenticatedReleaseIdentityError(
                "Durable state has enrollment_complete=False"
            )

        if state.committed is None or state.highwater is None:
            raise AuthenticatedReleaseIdentityError(
                "Authoritative state must contain committed generation and highwater binding"
            )

        # 4. Resolve and verify committed payload evidence
        committed_gen = state.committed
        committed_release_set = self._verify_envelope_evidence(
            committed_gen.binding,
            state.evidence,
            label="committed",
        )

        # 5. Require signed Launcher/Core identities to match committed Generation, and hash NekoUpdater.exe
        launcher_comp = committed_release_set.components.get("launcher")
        if launcher_comp is None:
            raise AuthenticatedReleaseIdentityError("Committed envelope missing launcher component")

        core_comp = committed_release_set.components.get("core")
        if core_comp is None:
            raise AuthenticatedReleaseIdentityError("Committed envelope missing core component")

        updater_comp = committed_release_set.components.get("updater")
        if updater_comp is None:
            raise AuthenticatedReleaseIdentityError("Committed envelope missing updater component")

        if launcher_comp.installed_identity_sha256 != committed_gen.launcher_identity_sha256:
            raise AuthenticatedReleaseIdentityError(
                f"Launcher installed identity mismatch: committed generation has "
                f"{committed_gen.launcher_identity_sha256}, signed envelope has "
                f"{launcher_comp.installed_identity_sha256}"
            )

        if core_comp.installed_identity_sha256 != committed_gen.core_identity_sha256:
            raise AuthenticatedReleaseIdentityError(
                f"Core installed identity mismatch: committed generation has "
                f"{committed_gen.core_identity_sha256}, signed envelope has "
                f"{core_comp.installed_identity_sha256}"
            )

        updater_exe_path = install_root / "NekoUpdater.exe"
        if not updater_exe_path.is_file():
            raise AuthenticatedReleaseIdentityError(
                f"Installed NekoUpdater.exe not found at {updater_exe_path}"
            )

        try:
            actual_updater_sha = sha256_file(updater_exe_path)
        except Exception as exc:
            raise AuthenticatedReleaseIdentityError(
                f"Failed to hash installed NekoUpdater.exe: {exc}"
            ) from exc

        if actual_updater_sha != updater_comp.installed_identity_sha256:
            raise AuthenticatedReleaseIdentityError(
                f"NekoUpdater.exe hash mismatch: disk has {actual_updater_sha}, "
                f"signed envelope has {updater_comp.installed_identity_sha256}"
            )

        # 6. Require non-null observed, observed == highwater, and verify highwater/failed evidence
        if state.observed is None:
            raise AuthenticatedReleaseIdentityError("State observed binding is missing")

        if state.observed != state.highwater:
            raise AuthenticatedReleaseIdentityError(
                f"State observed binding ({state.observed}) does not match highwater binding ({state.highwater})"
            )

        if state.highwater != committed_gen.binding:
            self._verify_envelope_evidence(
                state.highwater,
                state.evidence,
                label="high_water",
            )

        if state.failed is not None:
            if state.failed != committed_gen.binding and state.failed != state.highwater:
                self._verify_envelope_evidence(
                    state.failed,
                    state.evidence,
                    label="failed",
                )

        # 7. Construct and return LocalReleaseIdentity
        committed_binding = AuthenticatedReleaseBinding(
            release_sequence=committed_gen.binding.release_sequence,
            release_id=committed_gen.binding.release_id,
            payload_sha256=committed_gen.binding.payload_sha256,
        )
        high_water_binding = AuthenticatedReleaseBinding(
            release_sequence=state.highwater.release_sequence,
            release_id=state.highwater.release_id,
            payload_sha256=state.highwater.payload_sha256,
        )
        observed_binding = AuthenticatedReleaseBinding(
            release_sequence=state.observed.release_sequence,
            release_id=state.observed.release_id,
            payload_sha256=state.observed.payload_sha256,
        )
        failed_binding = (
            AuthenticatedReleaseBinding(
                release_sequence=state.failed.release_sequence,
                release_id=state.failed.release_id,
                payload_sha256=state.failed.payload_sha256,
            )
            if state.failed is not None
            else None
        )

        try:
            return LocalReleaseIdentity(
                committed=committed_binding,
                high_water=high_water_binding,
                observed=observed_binding,
                failed=failed_binding,
                launcher_version=launcher_comp.version,
                launcher_installed_identity_sha256=launcher_comp.installed_identity_sha256,
                updater_version=updater_comp.version,
                updater_installed_identity_sha256=updater_comp.installed_identity_sha256,
                core_version=core_comp.version,
                core_installed_identity_sha256=core_comp.installed_identity_sha256,
            )
        except ValueError as exc:
            raise AuthenticatedReleaseIdentityError(
                f"LocalReleaseIdentity validation failed: {exc}"
            ) from exc
