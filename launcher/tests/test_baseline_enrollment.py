from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from neko_launcher.bootstrap.baseline_enrollment import (
    BaselineEnrollmentResult,
    enroll_baseline_from_signed_envelope,
)
from neko_launcher.infrastructure.authenticated_release_identity import (
    AuthenticatedReleaseIdentityReader,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.enrollment import (
    load_selected_state,
    validate_enrollment_trust_binding,
)
from neko_launcher.updater.trust_profile import VerifiedUpdateTrustProfile
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_v2_release_document,
)


def make_matching_install_and_envelope(
    tmp_path: Path,
    sequence: int = 8,
    release_id: str = "rel-0008",
    channel: str = "stable",
    key_id: str = TEST_KEY_ID,
    signing_key: Ed25519PrivateKey | None = None,
    tamper_sig: bool = False,
    tamper_launcher: bool = False,
    tamper_updater: bool = False,
    tamper_core: bool = False,
    proto_min: int = 1,
    proto_max: int = 1,
    malformed_json: bool = False,
    missing_launcher: bool = False,
    missing_updater: bool = False,
    missing_core: bool = False,
) -> tuple[Path, Path, VerifiedUpdateTrustProfile]:
    install = tmp_path / "install"
    install.mkdir(parents=True, exist_ok=True)

    launcher_bytes = b"launcher-binary-content-for-baseline-512"
    updater_bytes = b"updater-binary-content-for-baseline-512"
    core_manifest_bytes = (
        b'{"rid":"win-x64","executable":"NekoProxyCore.exe","source_commit":"c512","files":[]}'
    )

    if not missing_launcher:
        l_content = b"corrupted-launcher" if tamper_launcher else launcher_bytes
        (install / "NekoLauncher.exe").write_bytes(l_content)

    if not missing_updater:
        u_content = b"corrupted-updater" if tamper_updater else updater_bytes
        (install / "NekoUpdater.exe").write_bytes(u_content)

    if not missing_core:
        proxy_core_dir = install / "ProxyCore"
        proxy_core_dir.mkdir(parents=True, exist_ok=True)
        c_content = b"corrupted-core-manifest" if tamper_core else core_manifest_bytes
        (proxy_core_dir / "core-manifest.json").write_bytes(c_content)

    launcher_sha = hashlib.sha256(launcher_bytes).hexdigest()
    updater_sha = hashlib.sha256(updater_bytes).hexdigest()
    core_installed_sha = hashlib.sha256(core_manifest_bytes).hexdigest()

    doc = valid_v2_release_document(
        sequence=sequence,
        release_id=release_id,
        channel=channel,
        proto_min=proto_min,
        proto_max=proto_max,
        launcher_sha=launcher_sha,
        launcher_size=len(launcher_bytes),
        updater_sha=updater_sha,
        updater_size=len(updater_bytes),
        core_installed_sha=core_installed_sha,
        core_sha=hashlib.sha256(b"dummy-core-zip").hexdigest(),
        core_size=1024,
    )

    envelope_dict = signed_envelope(doc, key_id=key_id, private_key=signing_key)
    if tamper_sig:
        envelope_dict["signature_b64"] = base64.standard_b64encode(b"\x00" * 64).decode("ascii")

    envelope_path = tmp_path / "release-v2.json"
    if malformed_json:
        envelope_path.write_bytes(b"not-json-content-<<<[[[")
    else:
        envelope_path.write_bytes(canonical_json_dumps(envelope_dict) + b"\n")

    verified_profile = VerifiedUpdateTrustProfile(
        profile_id="proof-v512",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy",
        release_public_keys={TEST_KEY_ID: TEST_PUBLIC_KEY},
        keyset_sha256=hashlib.sha256(TEST_PUBLIC_KEY).hexdigest(),
        profile_envelope_sha256="5" * 64,
        profile_authority_key_id="authority-key-1",
        profile_authority_public_key_sha256="6" * 64,
    )

    return install, envelope_path, verified_profile


def test_offline_baseline_enrollment_commits_signed_identity(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(tmp_path, sequence=8)
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert isinstance(result, BaselineEnrollmentResult)
    assert result.enrolled is True
    assert result.error is None
    assert result.binding is not None
    assert result.binding.release_sequence == 8
    assert result.binding.release_id == "rel-0008"

    selected = load_selected_state(install / "state", verified_profile.release_public_keys)
    assert selected.enrollment_complete is True
    assert selected.committed is not None
    assert selected.committed.binding.release_sequence == 8
    assert selected.committed.binding.release_id == "rel-0008"
    assert selected.highwater == selected.committed.binding
    assert selected.observed == selected.committed.binding
    assert selected.failed is None

    marker = validate_enrollment_trust_binding(install, verified_profile)
    assert marker.profile_id == verified_profile.profile_id
    assert marker.profile_envelope_sha256 == verified_profile.profile_envelope_sha256
    assert marker.keyset_sha256 == verified_profile.keyset_sha256
    assert marker.bootstrap_payload_sha256 == result.binding.payload_sha256

    local = AuthenticatedReleaseIdentityReader(verified_profile).read(install)
    assert local.committed == result.binding
    assert local.high_water == result.binding
    assert local.observed == result.binding
    assert local.failed is None


def test_baseline_enrollment_exact_rerun_idempotent(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(tmp_path, sequence=8)
    result1 = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result1.enrolled is True

    selected1 = load_selected_state(install / "state", verified_profile.release_public_keys)

    result2 = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result2.enrolled is True
    assert result2.binding == result1.binding
    assert result2.error is None

    selected2 = load_selected_state(install / "state", verified_profile.release_public_keys)
    assert selected2 == selected1


def test_baseline_enrollment_rejects_bad_signature(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, tamper_sig=True
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_unknown_key(tmp_path: Path) -> None:
    unknown_priv = Ed25519PrivateKey.generate()
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, key_id="unknown-key-999", signing_key=unknown_priv
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_wrong_channel(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, channel="beta"
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_unsupported_protocol(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, proto_min=2, proto_max=2
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_wrong_launcher_identity(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, tamper_launcher=True
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_wrong_updater_identity(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, tamper_updater=True
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_wrong_core_identity(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, tamper_core=True
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_malformed_envelope(tmp_path: Path) -> None:
    install, envelope, verified_profile = make_matching_install_and_envelope(
        tmp_path, sequence=8, malformed_json=True
    )
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled is False
    assert result.binding is None
    assert result.error is not None
    assert not (install / "state" / "slot-a.bin").exists()


def test_baseline_enrollment_rejects_conflicting_preexisting_same_sequence_binding(
    tmp_path: Path,
) -> None:
    install, envelope1, verified_profile = make_matching_install_and_envelope(
        tmp_path / "c1", sequence=8, release_id="rel-0008-a"
    )
    result1 = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope1,
        trust_profile=verified_profile,
    )
    assert result1.enrolled is True

    # Same sequence 8, but different release_id and payload
    _, envelope2, _ = make_matching_install_and_envelope(
        tmp_path / "c2", sequence=8, release_id="rel-0008-b"
    )
    result2 = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope2,
        trust_profile=verified_profile,
    )
    assert result2.enrolled is False
    assert result2.binding is None
    assert result2.error is not None

    selected = load_selected_state(install / "state", verified_profile.release_public_keys)
    assert selected.committed.binding.release_sequence == result1.binding.release_sequence
    assert selected.committed.binding.release_id == result1.binding.release_id
    assert selected.committed.binding.payload_sha256 == result1.binding.payload_sha256
    local = AuthenticatedReleaseIdentityReader(verified_profile).read(install)
    assert local.committed == result1.binding


def test_baseline_enrollment_rejects_missing_component_files(tmp_path: Path) -> None:
    # Missing launcher
    install_nl, envelope_nl, profile = make_matching_install_and_envelope(
        tmp_path / "nl", missing_launcher=True
    )
    res_nl = enroll_baseline_from_signed_envelope(
        install_root=install_nl, envelope_path=envelope_nl, trust_profile=profile
    )
    assert res_nl.enrolled is False

    # Missing updater
    install_nu, envelope_nu, _ = make_matching_install_and_envelope(
        tmp_path / "nu", missing_updater=True
    )
    res_nu = enroll_baseline_from_signed_envelope(
        install_root=install_nu, envelope_path=envelope_nu, trust_profile=profile
    )
    assert res_nu.enrolled is False

    # Missing core manifest
    install_nc, envelope_nc, _ = make_matching_install_and_envelope(
        tmp_path / "nc", missing_core=True
    )
    res_nc = enroll_baseline_from_signed_envelope(
        install_root=install_nc, envelope_path=envelope_nc, trust_profile=profile
    )
    assert res_nc.enrolled is False


def test_baseline_enrollment_rejects_invalid_trust_profile_type(tmp_path: Path) -> None:
    install, envelope, _ = make_matching_install_and_envelope(tmp_path, sequence=8)
    with pytest.raises(TypeError, match="VerifiedUpdateTrustProfile"):
        enroll_baseline_from_signed_envelope(
            install_root=install,
            envelope_path=envelope,
            trust_profile="not-a-profile",  # type: ignore[arg-type]
        )
