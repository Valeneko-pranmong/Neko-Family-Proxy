from __future__ import annotations

import base64
import dataclasses
import hashlib
from pathlib import Path

import pytest

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    DevelopmentReleaseIdentity,
    LocalReleaseIdentity,
)
from neko_launcher.infrastructure.software_release_identity import (
    load_development_release_identity,
    sha256_file,
)
from neko_launcher.infrastructure.authenticated_release_identity import (
    AuthenticatedReleaseIdentityError,
    AuthenticatedReleaseIdentityReader,
)
from neko_launcher.updater.binary_frame import (
    MarkerFrame,
    SlotFrame,
    pack_marker_frame,
    pack_slot_frame,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.state_models import (
    Binding,
    EnrollmentMarker,
    Generation,
    RootIdentity,
    State,
    serialize_marker,
    serialize_state,
)
from neko_launcher.updater.trust_profile import VerifiedUpdateTrustProfile
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    canonical_payload_bytes,
    signed_envelope,
    valid_v2_release_document,
)

H_1 = "1" * 64
H_2 = "2" * 64
H_3 = "3" * 64
H_4 = "4" * 64
H_5 = "5" * 64
H_6 = "6" * 64


def test_local_identity_keeps_full_committed_and_high_water_bindings() -> None:
    committed = AuthenticatedReleaseBinding(8, "stable-0008", H_1)
    high_water = AuthenticatedReleaseBinding(9, "stable-0009", H_2)
    failed = high_water
    local = LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=failed,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_3,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_4,
        core_version="5.1.2",
        core_installed_identity_sha256=H_5,
    )
    assert local.release_sequence == 8
    assert local.release_id == "stable-0008"
    assert local.high_water.release_sequence == 9
    assert local.high_water.release_id == "stable-0009"
    assert local.high_water.payload_sha256 == H_2
    assert local.failed == high_water
    assert isinstance(local.high_water, AuthenticatedReleaseBinding)
    assert isinstance(local.committed, AuthenticatedReleaseBinding)
    assert isinstance(local.observed, AuthenticatedReleaseBinding)


@pytest.mark.parametrize(
    "invalid_sequence",
    [0, -1, -100],
)
def test_authenticated_release_binding_rejects_non_positive_sequence(
    invalid_sequence: int,
) -> None:
    with pytest.raises(ValueError, match="release_sequence must be positive"):
        AuthenticatedReleaseBinding(invalid_sequence, "release-1", H_1)


def test_authenticated_release_binding_rejects_bool_sequence() -> None:
    with pytest.raises(ValueError, match="release_sequence must be an int"):
        AuthenticatedReleaseBinding(True, "release-1", H_1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "invalid_hash",
    [
        "1" * 63,
        "1" * 65,
        "G" * 64,
        "A" * 64,  # uppercase
        "not-a-hash",
        "",
    ],
)
def test_authenticated_release_binding_rejects_invalid_payload_sha(
    invalid_hash: str,
) -> None:
    with pytest.raises(ValueError, match="payload_sha256 must be lowercase 64-hex"):
        AuthenticatedReleaseBinding(1, "release-1", invalid_hash)


@pytest.mark.parametrize(
    "invalid_id",
    ["", "   "],
)
def test_authenticated_release_binding_rejects_invalid_release_id(
    invalid_id: str,
) -> None:
    with pytest.raises(ValueError, match="release_id must be a non-empty string"):
        AuthenticatedReleaseBinding(1, invalid_id, H_1)


def test_local_identity_requires_committed_sequence_le_high_water() -> None:
    committed = AuthenticatedReleaseBinding(10, "rel-10", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    with pytest.raises(
        ValueError,
        match="committed release_sequence cannot exceed high_water release_sequence",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=None,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_local_identity_requires_observed_equals_high_water() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    mismatched_observed = AuthenticatedReleaseBinding(10, "rel-10", H_3)
    with pytest.raises(
        ValueError,
        match="observed binding must equal high_water binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=mismatched_observed,
            failed=None,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_local_identity_requires_failed_sequence_le_high_water() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    excess_failed = AuthenticatedReleaseBinding(10, "rel-10", H_3)
    with pytest.raises(
        ValueError,
        match="failed release_sequence cannot exceed high_water release_sequence",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=excess_failed,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_pairwise_conflict_committed_and_high_water_same_sequence_different_binding() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8-a", H_1)
    high_water = AuthenticatedReleaseBinding(8, "rel-8-b", H_2)
    with pytest.raises(
        ValueError,
        match="Pairwise binding conflict: same sequence with different binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=None,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_3,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_4,
            core_version="5.1.2",
            core_installed_identity_sha256=H_5,
        )


def test_pairwise_conflict_high_water_and_failed_same_sequence_different_binding() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9-a", H_2)
    failed = AuthenticatedReleaseBinding(9, "rel-9-b", H_3)
    with pytest.raises(
        ValueError,
        match="Pairwise binding conflict: same sequence with different binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=failed,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_4,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_5,
            core_version="5.1.2",
            core_installed_identity_sha256=H_6,
        )


def test_pairwise_conflict_committed_and_failed_same_sequence_different_binding() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8-a", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    failed = AuthenticatedReleaseBinding(8, "rel-8-b", H_3)
    with pytest.raises(
        ValueError,
        match="Pairwise binding conflict: same sequence with different binding",
    ):
        LocalReleaseIdentity(
            committed=committed,
            high_water=high_water,
            observed=high_water,
            failed=failed,
            launcher_version="5.1.2",
            launcher_installed_identity_sha256=H_4,
            updater_version="5.1.2",
            updater_installed_identity_sha256=H_5,
            core_version="5.1.2",
            core_installed_identity_sha256=H_6,
        )


def test_valid_pairwise_same_sequence_matches_exactly() -> None:
    binding_8 = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    local = LocalReleaseIdentity(
        committed=binding_8,
        high_water=binding_8,
        observed=binding_8,
        failed=None,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_2,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_3,
        core_version="5.1.2",
        core_installed_identity_sha256=H_4,
    )
    assert local.release_sequence == 8
    assert local.high_water == binding_8


def test_valid_enrolled_state_resumable_incomplete_authority() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    local = LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=None,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_3,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_4,
        core_version="5.1.2",
        core_installed_identity_sha256=H_5,
    )
    assert local.committed != local.high_water
    assert local.failed is None


def test_valid_enrolled_state_failed_matching_committed() -> None:
    committed = AuthenticatedReleaseBinding(8, "rel-8", H_1)
    high_water = AuthenticatedReleaseBinding(9, "rel-9", H_2)
    local = LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=committed,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=H_3,
        updater_version="5.1.2",
        updater_installed_identity_sha256=H_4,
        core_version="5.1.2",
        core_installed_identity_sha256=H_5,
    )
    assert local.failed == committed


@pytest.mark.parametrize(
    "field_name,invalid_hash",
    [
        ("launcher_installed_identity_sha256", "not-hex" * 8),
        ("launcher_installed_identity_sha256", "A" * 64),
        ("updater_installed_identity_sha256", "B" * 64),
        ("updater_installed_identity_sha256", "1" * 63),
        ("core_installed_identity_sha256", "C" * 64),
        ("core_installed_identity_sha256", "1" * 65),
    ],
)
def test_local_identity_rejects_invalid_installed_identity_hashes(
    field_name: str,
    invalid_hash: str,
) -> None:
    binding = AuthenticatedReleaseBinding(1, "rel-1", H_1)
    kwargs = {
        "committed": binding,
        "high_water": binding,
        "observed": binding,
        "failed": None,
        "launcher_version": "5.1.2",
        "launcher_installed_identity_sha256": H_2,
        "updater_version": "5.1.2",
        "updater_installed_identity_sha256": H_3,
        "core_version": "5.1.2",
        "core_installed_identity_sha256": H_4,
    }
    kwargs[field_name] = invalid_hash
    with pytest.raises(ValueError, match="must be lowercase 64-hex"):
        LocalReleaseIdentity(**kwargs)  # type: ignore[arg-type]


def test_development_release_identity_contract() -> None:
    dev = DevelopmentReleaseIdentity(
        release_sequence=0,
        release_id="dev-unpublished",
        launcher_version="5.1.0-dev",
        launcher_installed_identity_sha256=H_1,
        core_version="1.0.0-dev",
        core_installed_identity_sha256=H_2,
    )
    assert dev.release_sequence == 0
    assert dev.release_id == "dev-unpublished"
    assert dev.launcher_version == "5.1.0-dev"
    assert dev.core_version == "1.0.0-dev"
    assert dev.launcher_installed_identity_sha256 == H_1
    assert dev.core_installed_identity_sha256 == H_2


def test_development_release_identity_rejects_nonzero_sequence() -> None:
    with pytest.raises(ValueError, match="release_sequence must be 0"):
        DevelopmentReleaseIdentity(
            release_sequence=1,  # type: ignore[arg-type]
            release_id="dev-unpublished",
            launcher_version="5.1.0-dev",
            launcher_installed_identity_sha256=H_1,
            core_version="1.0.0-dev",
            core_installed_identity_sha256=H_2,
        )


def test_development_release_identity_rejects_wrong_release_id() -> None:
    with pytest.raises(ValueError, match="release_id must be 'dev-unpublished'"):
        DevelopmentReleaseIdentity(
            release_sequence=0,
            release_id="prod-1",  # type: ignore[arg-type]
            launcher_version="5.1.0-dev",
            launcher_installed_identity_sha256=H_1,
            core_version="1.0.0-dev",
            core_installed_identity_sha256=H_2,
        )


def test_development_release_identity_rejects_invalid_hash() -> None:
    with pytest.raises(ValueError, match="must be lowercase 64-hex"):
        DevelopmentReleaseIdentity(
            release_sequence=0,
            release_id="dev-unpublished",
            launcher_version="5.1.0-dev",
            launcher_installed_identity_sha256="A" * 64,
            core_version="1.0.0-dev",
            core_installed_identity_sha256=H_2,
        )


def test_load_development_release_identity_returns_development_type(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "launcher.exe"
    core = tmp_path / "core-manifest.json"
    launcher.write_bytes(b"launcher")
    core.write_bytes(b"core")

    result = load_development_release_identity(
        launcher_version="5.1.0-dev",
        launcher_executable=launcher,
        core_version="1.0.0-dev",
        core_manifest=core,
    )
    assert isinstance(result, DevelopmentReleaseIdentity)
    assert not isinstance(result, LocalReleaseIdentity)
    assert result.release_sequence == 0
    assert result.release_id == "dev-unpublished"


@pytest.fixture
def verified_profile() -> VerifiedUpdateTrustProfile:
    return VerifiedUpdateTrustProfile(
        profile_id="test-profile-v512",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates-Proof",
        release_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
        keyset_sha256="4" * 64,
        profile_envelope_sha256="5" * 64,
        profile_authority_key_id="auth-key-1",
        profile_authority_public_key_sha256="6" * 64,
    )


def make_enrolled_install(
    install_root: Path,
    *,
    committed: tuple[int, str] = (8, "stable-0008"),
    high_water: tuple[int, str] = (8, "stable-0008"),
    observed: tuple[int, str] | None = None,
    failed: tuple[int, str] | None = None,
    trust_profile: VerifiedUpdateTrustProfile,
    enrollment_complete: bool = True,
    write_updater_exe: bool = True,
    updater_content: bytes = b"updater-binary-content-v512",
    tamper_updater_content: bytes | None = None,
    tamper_launcher_identity: str | None = None,
    tamper_core_identity: str | None = None,
    tamper_committed_binding: Binding | None = None,
    tamper_highwater_binding: Binding | None = None,
    tamper_observed_binding: Binding | None = None,
    tamper_failed_binding: Binding | None = None,
    tamper_evidence: dict[str, str] | None = None,
    tamper_envelope_signature: bool = False,
    tamper_marker_profile_id: str | None = None,
    tamper_marker_keyset_sha: str | None = None,
    tamper_marker_envelope_sha: str | None = None,
    corrupt_slot_a: bool = False,
    corrupt_slot_b: bool = False,
    skip_marker: bool = False,
    skip_slots: bool = False,
) -> Path:
    install_root.mkdir(parents=True, exist_ok=True)
    state_dir = install_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    committed_seq, committed_id = committed
    hw_seq, hw_id = high_water
    obs_seq, obs_id = observed if observed is not None else high_water

    needed: set[tuple[int, str]] = {committed, high_water}
    if observed is not None:
        needed.add(observed)
    if failed is not None:
        needed.add(failed)

    evidence: dict[str, str] = {}
    docs: dict[tuple[int, str], dict[str, object]] = {}
    payload_shas: dict[tuple[int, str], str] = {}

    for seq, rel_id in sorted(needed):
        if seq == committed_seq:
            updater_sha = hashlib.sha256(updater_content).hexdigest()
            doc = valid_v2_release_document(
                sequence=seq,
                release_id=rel_id,
                updater_sha=updater_sha,
            )
        else:
            doc = valid_v2_release_document(
                sequence=seq,
                release_id=rel_id,
            )
        envelope = signed_envelope(doc, key_id=TEST_KEY_ID)
        if tamper_envelope_signature:
            envelope["signature_b64"] = base64.standard_b64encode(b"\x00" * 64).decode("ascii")

        envelope_bytes = canonical_json_dumps(envelope)
        envelope_b64 = base64.b64encode(envelope_bytes).decode("ascii")
        p_sha = hashlib.sha256(canonical_payload_bytes(doc)).hexdigest()

        docs[(seq, rel_id)] = doc
        payload_shas[(seq, rel_id)] = p_sha
        evidence[p_sha] = envelope_b64

    if write_updater_exe:
        updater_bytes = (
            tamper_updater_content if tamper_updater_content is not None else updater_content
        )
        (install_root / "NekoUpdater.exe").write_bytes(updater_bytes)

    committed_doc = docs[committed]
    committed_p_sha = payload_shas[committed]
    committed_binding = Binding(committed_seq, committed_id, committed_p_sha)
    if tamper_committed_binding is not None:
        committed_binding = tamper_committed_binding

    launcher_id = (
        tamper_launcher_identity
        if tamper_launcher_identity is not None
        else str(committed_doc["components"]["launcher"]["installed_identity_sha256"])  # type: ignore[index]
    )
    core_id = (
        tamper_core_identity
        if tamper_core_identity is not None
        else str(committed_doc["components"]["core"]["installed_identity_sha256"])  # type: ignore[index]
    )
    committed_gen = Generation(
        binding=committed_binding,
        launcher_identity_sha256=launcher_id,
        core_identity_sha256=core_id,
    )

    hw_p_sha = payload_shas[high_water]
    hw_binding = Binding(hw_seq, hw_id, hw_p_sha)
    if tamper_highwater_binding is not None:
        hw_binding = tamper_highwater_binding

    obs_p_sha = payload_shas[observed] if observed is not None else hw_p_sha
    obs_binding = Binding(obs_seq, obs_id, obs_p_sha)
    if tamper_observed_binding is not None:
        obs_binding = tamper_observed_binding

    failed_binding: Binding | None = None
    if failed is not None:
        failed_seq, failed_id = failed
        failed_p_sha = payload_shas[failed]
        failed_binding = Binding(failed_seq, failed_id, failed_p_sha)
        if tamper_failed_binding is not None:
            failed_binding = tamper_failed_binding

    final_evidence = tamper_evidence if tamper_evidence is not None else evidence

    state_rev2 = State(
        schema_version=1,
        revision=2,
        installation_id="0" * 32,
        helper_protocol=1,
        enrollment_complete=False,
        phase="IDLE",
        committed=committed_gen,
        previous=None,
        highwater=hw_binding,
        observed=obs_binding,
        failed=failed_binding,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence=final_evidence,
    )
    state_rev3 = dataclasses.replace(
        state_rev2,
        revision=3,
        enrollment_complete=enrollment_complete,
    )

    if not skip_marker:
        marker = EnrollmentMarker(
            schema_version=1,
            installation_id=state_rev2.installation_id,
            root=RootIdentity(volume_serial="1" * 16, file_id="2" * 32),
            helper_sha256="3" * 64,
            helper_protocol=1,
            keyset_sha256=tamper_marker_keyset_sha or trust_profile.keyset_sha256,
            bootstrap_payload_sha256=committed_p_sha,
            enrollment_status="PREPARED",
            profile_id=tamper_marker_profile_id or trust_profile.profile_id,
            profile_envelope_sha256=tamper_marker_envelope_sha
            or trust_profile.profile_envelope_sha256,
        )
        marker_bytes = pack_marker_frame(
            MarkerFrame(format_version=1, body_bytes=serialize_marker(marker))
        )
        (state_dir / "enrollment.bin").write_bytes(marker_bytes)

    if not skip_slots:
        slot_a_bytes = (
            b"corrupted-slot-a-bytes"
            if corrupt_slot_a
            else pack_slot_frame(
                SlotFrame(
                    revision=state_rev2.revision,
                    format_version=1,
                    body_bytes=serialize_state(state_rev2),
                )
            )
        )
        slot_b_bytes = (
            b"corrupted-slot-b-bytes"
            if corrupt_slot_b
            else pack_slot_frame(
                SlotFrame(
                    revision=state_rev3.revision,
                    format_version=1,
                    body_bytes=serialize_state(state_rev3),
                )
            )
        )
        (state_dir / "slot-a.bin").write_bytes(slot_a_bytes)
        (state_dir / "slot-b.bin").write_bytes(slot_b_bytes)

    return install_root


def test_reader_returns_authenticated_committed_and_high_water(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
    )
    local = AuthenticatedReleaseIdentityReader(verified_profile).read(install)
    assert local.committed.release_sequence == 8
    assert local.committed.release_id == "stable-0008"
    assert local.high_water == local.committed
    assert local.observed == local.committed
    assert local.failed is None
    assert local.launcher_version == "5.1.0"
    assert local.updater_version == "5.1.0"
    assert local.core_version == "1.0.0"
    assert local.updater_installed_identity_sha256 == sha256_file(install / "NekoUpdater.exe")


def test_reader_returns_rollback_history(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(9, "stable-0009"),
        observed=(9, "stable-0009"),
        failed=(9, "stable-0009"),
        trust_profile=verified_profile,
    )
    local = AuthenticatedReleaseIdentityReader(verified_profile).read(install)
    assert local.committed.release_sequence == 8
    assert local.committed.release_id == "stable-0008"
    assert local.high_water.release_sequence == 9
    assert local.high_water.release_id == "stable-0009"
    assert local.observed == local.high_water
    assert local.failed == local.high_water


def test_reader_returns_retryable_admitted_state(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(9, "stable-0009"),
        observed=(9, "stable-0009"),
        failed=None,
        trust_profile=verified_profile,
    )
    local = AuthenticatedReleaseIdentityReader(verified_profile).read(install)
    assert local.committed.release_sequence == 8
    assert local.high_water.release_sequence == 9
    assert local.observed == local.high_water
    assert local.failed is None


def test_reader_rejects_high_water_observed_mismatch(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(9, "stable-0009"),
        observed=(8, "stable-0008"),
        trust_profile=verified_profile,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError, match="observed"):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_missing_committed_evidence(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_evidence={},
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_missing_high_water_evidence(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    # Generate install where highwater is 9, but evidence only retains 8
    doc_8 = valid_v2_release_document(
        sequence=8,
        release_id="stable-0008",
        updater_sha=hashlib.sha256(b"updater-binary-content-v512").hexdigest(),
    )
    env_8 = signed_envelope(doc_8, key_id=TEST_KEY_ID)
    p_sha_8 = hashlib.sha256(canonical_payload_bytes(doc_8)).hexdigest()
    env_8_b64 = base64.b64encode(canonical_json_dumps(env_8)).decode("ascii")

    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(9, "stable-0009"),
        trust_profile=verified_profile,
        tamper_evidence={p_sha_8: env_8_b64},
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_invalid_signature(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_envelope_signature=True,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_payload_release_id_mismatch(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    tampered_binding = Binding(8, "mismatched-id", "a" * 64)
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_committed_binding=tampered_binding,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_launcher_identity_mismatch(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_launcher_identity="f" * 64,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_core_identity_mismatch(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_core_identity="f" * 64,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_updater_file_missing(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        write_updater_exe=False,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError, match="NekoUpdater.exe"):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_updater_file_content_mismatched(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_updater_content=b"tampered-updater-content",
    )
    with pytest.raises(AuthenticatedReleaseIdentityError, match="NekoUpdater.exe"):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_enrollment_incomplete_state(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        enrollment_complete=False,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError, match="[Ee]nrollment"):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_missing_enrollment_marker(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        skip_marker=True,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_corrupt_slots(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        corrupt_slot_a=True,
        corrupt_slot_b=True,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_missing_slots(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        skip_slots=True,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_mismatched_profile_id(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_marker_profile_id="mismatched-profile",
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_mismatched_profile_envelope_sha(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_marker_envelope_sha="9" * 64,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_rejects_mismatched_keyset_sha(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
        tamper_marker_keyset_sha="9" * 64,
    )
    with pytest.raises(AuthenticatedReleaseIdentityError):
        AuthenticatedReleaseIdentityReader(verified_profile).read(install)


def test_reader_copies_and_freezes_release_public_keys(
    tmp_path: Path,
    verified_profile: VerifiedUpdateTrustProfile,
) -> None:
    mutable_keys = dict(verified_profile.release_public_keys)
    profile = dataclasses.replace(verified_profile, release_public_keys=mutable_keys)
    reader = AuthenticatedReleaseIdentityReader(profile)
    mutable_keys[TEST_KEY_ID] = b"\x00" * 32
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
    )
    local = reader.read(install)
    assert local.committed.release_sequence == 8
