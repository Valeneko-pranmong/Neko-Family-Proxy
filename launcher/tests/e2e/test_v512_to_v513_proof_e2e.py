from __future__ import annotations

import base64
import hashlib
import shutil
import sys
import types
import zipfile
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_LAUNCHER_DIR = _REPO_ROOT / "launcher"
_LAUNCHER_SRC = _LAUNCHER_DIR / "src"

for p in (str(_REPO_ROOT), str(_SCRIPTS_DIR), str(_LAUNCHER_SRC), str(_LAUNCHER_DIR)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)

import tests  # noqa: E402
_launcher_tests = str(_LAUNCHER_DIR / "tests")
if hasattr(tests, "__path__") and _launcher_tests not in tests.__path__:
    tests.__path__.append(_launcher_tests)

from neko_launcher.application.software_update_activity import (  # noqa: E402
    UpdateApplyBlocker,
    evaluate_update_apply_safety,
)
from neko_launcher.application.software_update_models import (  # noqa: E402
    AuthenticatedReleaseBinding,
    ComponentRelease,
    LocalReleaseIdentity,
    ReleaseSet,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.application.software_update_pending import (  # noqa: E402
    UpdateLifecycleState,
)
from neko_launcher.application.software_update_policy import evaluate_release  # noqa: E402
from neko_launcher.bootstrap.baseline_enrollment import (  # noqa: E402
    BaselineEnrollmentResult,
    enroll_baseline_from_signed_envelope,
)
from neko_launcher.bootstrap.pending_update_bootstrap import (  # noqa: E402
    PendingUpdateBootstrapResult,
    try_apply_pending_on_launch,
)
from neko_launcher.domain.models import AppState, GameStatus, ProxyStatus  # noqa: E402
from neko_launcher.infrastructure.authenticated_release_identity import (  # noqa: E402
    AuthenticatedReleaseIdentityReader,
)
from neko_launcher.infrastructure.github_asset_downloader import (  # noqa: E402
    GitHubAssetDownloadError,
)
from neko_launcher.infrastructure.software_update_apply import (  # noqa: E402
    SoftwareUpdateApplyError,
    SoftwareUpdateApplyService,
)
from neko_launcher.infrastructure.update_channel_profile import (  # noqa: E402
    UpdateChannelProfile,
)
from neko_launcher.updater.binary_frame import (  # noqa: E402
    SlotFrame,
    pack_slot_frame,
)
from neko_launcher.updater.canonical_json import (  # noqa: E402
    canonical_json_dumps,
)
from neko_launcher.updater.core_manifest_verifier import (  # noqa: E402
    verify_canonical_core_bundle,
)
from neko_launcher.updater.enrollment import (  # noqa: E402
    load_selected_state,
    validate_enrollment_trust_binding,
)
from neko_launcher.updater.recovery_engine import (  # noqa: E402
    RecoveryEngine,
)
from neko_launcher.updater.state_models import (  # noqa: E402
    Binding,
    Cleanup,
    DirectoryIdentity,
    Generation,
    Mutation,
    Rollback,
    State,
    Transaction,
    serialize_state,
)
from neko_launcher.updater.trust_profile import (  # noqa: E402
    load_installed_update_trust_profile,
    verify_update_trust_profile,
)
from tests.e2e.test_deferred_pending_update_e2e import (  # noqa: E402
    ReusableFakeTransportOpener,
    _create_admission_runner,
    _create_helper_runner,
    _setup_coordinator_pipeline,
)
from tests.e2e.test_github_release_update_e2e import (  # noqa: E402
    _assert_public_unauthenticated_requests,
    _build_proof_channel_routes,
)
from verify_build_equivalence import (  # noqa: E402
    compare_builds,
)

RA8_PACKAGE_SOURCE_SHA = "3348d1f7eb324aab34860c103a888223be01e805"


def _make_keypair() -> tuple[Ed25519PrivateKey, bytes]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_bytes = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub_bytes


def _build_core_bundle(
    core_dir: Path,
    zip_path: Path,
    *,
    version: str = "5.1.2",
    source_commit: str = "3348d1f",
) -> tuple[bytes, str, int, str]:
    core_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "NekoProxyCore.exe": f"core-exe-{version}\n".encode("utf-8"),
        "NekoProxyCore.dll": f"core-dll-{version}\n".encode("utf-8"),
        "runtime-settings.nkps": f"runtime-settings-{version}\n".encode("utf-8"),
        "bin/Redirector.bin": f"redirector-{version}\n".encode("utf-8"),
        "bin/nfapi.dll": f"nfapi-{version}\n".encode("utf-8"),
        "bin/v2ray-sn.exe": f"v2ray-sn-{version}\n".encode("utf-8"),
    }
    manifest_entries = []
    for rel_path, data in sorted(files.items()):
        fpath = core_dir / rel_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_bytes(data)
        manifest_entries.append({
            "path": rel_path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })

    manifest_obj = {
        "executable": "NekoProxyCore.exe",
        "files": manifest_entries,
        "rid": "win-x64",
        "source_commit": source_commit,
    }
    manifest_bytes = canonical_json_dumps(manifest_obj)
    (core_dir / "core-manifest.json").write_bytes(manifest_bytes)

    res = verify_canonical_core_bundle(core_dir)
    assert res.valid is True, f"Core bundle invalid: {res.error}"

    all_entries = dict(files)
    all_entries["core-manifest.json"] = manifest_bytes

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name in sorted(all_entries.keys()):
            zinfo = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            zinfo.compress_type = zipfile.ZIP_STORED
            zinfo.external_attr = 0o644 << 16
            zf.writestr(zinfo, all_entries[name])

    zip_bytes = zip_path.read_bytes()
    return (
        zip_bytes,
        hashlib.sha256(zip_bytes).hexdigest(),
        len(zip_bytes),
        res.manifest_sha256,
    )


def _make_signed_profile_envelope(
    *,
    auth_priv: Ed25519PrivateKey,
    auth_key_id: str = "authority-profile-key-1",
    profile_id: str = "proof-v512",
    channel: str = "stable",
    owner: str = "Valeneko-pranmong",
    repository: str = "Neko-Family-Proxy-Updates-Proof",
    release_keys: list[dict[str, str]],
) -> bytes:
    payload = {
        "channel": channel,
        "owner": owner,
        "profile_id": profile_id,
        "release_keys": release_keys,
        "repository": repository,
    }
    payload_bytes = canonical_json_dumps(payload)
    sig_bytes = auth_priv.sign(payload_bytes)
    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")
    envelope = {
        "key_id": auth_key_id,
        "payload": payload,
        "schema_version": 1,
        "signature_b64": sig_b64,
    }
    return canonical_json_dumps(envelope) + b"\n"


def _make_signed_release_envelope(
    *,
    release_priv: Ed25519PrivateKey,
    key_id: str = "neko-update-proof-v512-1",
    sequence: int = 1,
    release_id: str = "proof-k1-0001",
    channel: str = "stable",
    mandatory: bool = False,
    minimum_supported_sequence: int = 1,
    launcher_sha: str,
    launcher_size: int,
    launcher_version: str = "5.1.2",
    updater_sha: str,
    updater_size: int,
    updater_version: str = "5.1.2",
    core_sha: str,
    core_size: int,
    core_installed_sha: str,
    core_version: str = "5.1.2",
) -> tuple[bytes, dict[str, Any], AuthenticatedReleaseBinding]:
    payload = {
        "channel": channel,
        "components": {
            "core": {
                "artifact_format": "zip-core-v1",
                "artifact_id": "NekoProxyCore.zip",
                "artifact_sha256": core_sha,
                "artifact_size": core_size,
                "installed_identity_sha256": core_installed_sha,
                "version": core_version,
            },
            "launcher": {
                "artifact_format": "raw-pe-v1",
                "artifact_id": "NekoLauncher.exe",
                "artifact_sha256": launcher_sha,
                "artifact_size": launcher_size,
                "installed_identity_sha256": launcher_sha,
                "version": launcher_version,
            },
            "updater": {
                "artifact_format": "raw-pe-v1",
                "artifact_id": "NekoUpdater.exe",
                "artifact_sha256": updater_sha,
                "artifact_size": updater_size,
                "installed_identity_sha256": updater_sha,
                "version": updater_version,
            },
        },
        "mandatory": mandatory,
        "minimum_supported_sequence": minimum_supported_sequence,
        "release_id": release_id,
        "release_sequence": sequence,
        "schema_version": 2,
        "updater_protocol": {"maximum": 1, "minimum": 1},
    }
    payload_bytes = canonical_json_dumps(payload)
    sig_bytes = release_priv.sign(payload_bytes)
    envelope = {
        "envelope_version": 1,
        "key_id": key_id,
        "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(sig_bytes).decode("ascii"),
    }
    envelope_bytes = canonical_json_dumps(envelope)
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    binding = AuthenticatedReleaseBinding(
        release_sequence=sequence,
        release_id=release_id,
        payload_sha256=payload_sha,
    )
    return envelope_bytes, envelope, binding


class ProofHarnessFixture:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path = tmp_path
        self.auth_priv, self.auth_pub = _make_keypair()
        self.auth_key_id = "test-profile-authority-1"
        self.profile_keys = {self.auth_key_id: self.auth_pub}

        # Monkeypatch authority root for test-isolated ephemeral signing
        monkeypatch.setattr(
            "neko_launcher.updater.trust.PROFILE_AUTHORITY_PUBLIC_KEYS",
            self.profile_keys,
        )
        monkeypatch.setattr(
            "neko_launcher.updater.trust_profile.PROFILE_AUTHORITY_PUBLIC_KEYS",
            self.profile_keys,
        )
        monkeypatch.setattr(
            "verify_build_equivalence.PROFILE_AUTHORITY_PUBLIC_KEYS",
            self.profile_keys,
        )

        self.proof_priv, self.proof_pub = _make_keypair()
        self.proof_key_id = "neko-update-proof-v512-1"

        self.prod_priv, self.prod_pub = _make_keypair()
        self.prod_key_id = "neko-update-prod-1"

        # Trust profiles
        self.proof_profile_raw = _make_signed_profile_envelope(
            auth_priv=self.auth_priv,
            auth_key_id=self.auth_key_id,
            profile_id="proof-v512",
            channel="stable",
            owner="Valeneko-pranmong",
            repository="Neko-Family-Proxy-Updates-Proof",
            release_keys=[{
                "key_id": self.proof_key_id,
                "public_key_hex": self.proof_pub.hex(),
            }],
        )
        self.prod_profile_raw = _make_signed_profile_envelope(
            auth_priv=self.auth_priv,
            auth_key_id=self.auth_key_id,
            profile_id="production",
            channel="stable",
            owner="Valeneko-pranmong",
            repository="Neko-Family-Proxy-Updates",
            release_keys=[{
                "key_id": self.prod_key_id,
                "public_key_hex": self.prod_pub.hex(),
            }],
        )

        self.verified_proof_profile = verify_update_trust_profile(
            self.proof_profile_raw,
            profile_authority_public_keys=self.profile_keys,
        )
        self.verified_prod_profile = verify_update_trust_profile(
            self.prod_profile_raw,
            profile_authority_public_keys=self.profile_keys,
        )
        self.channel_profile = UpdateChannelProfile.from_verified(
            self.verified_proof_profile
        )

        # Baseline artifact payloads
        self.launcher_bytes = b"MZ_NEKO_LAUNCHER_PROOF_BASELINE_V512"
        self.updater_bytes = b"MZ_NEKO_UPDATER_BYTE_EXACT_V512"
        self.launcher_sha = hashlib.sha256(self.launcher_bytes).hexdigest()
        self.updater_sha = hashlib.sha256(self.updater_bytes).hexdigest()

        self.core_dir = tmp_path / "baseline_core_bundle"
        self.core_zip_path = tmp_path / "baseline_core.zip"
        (
            self.core_zip_bytes,
            self.core_zip_sha,
            self.core_zip_size,
            self.core_installed_sha,
        ) = _build_core_bundle(
            self.core_dir,
            self.core_zip_path,
            version="5.1.2",
            source_commit="3348d1f",
        )

        # Baseline release envelope (seq 1)
        (
            self.baseline_envelope_bytes,
            self.baseline_envelope_doc,
            self.baseline_binding,
        ) = _make_signed_release_envelope(
            release_priv=self.proof_priv,
            key_id=self.proof_key_id,
            sequence=1,
            release_id="proof-k1-0001",
            channel="stable",
            mandatory=False,
            minimum_supported_sequence=1,
            launcher_sha=self.launcher_sha,
            launcher_size=len(self.launcher_bytes),
            launcher_version="5.1.2",
            updater_sha=self.updater_sha,
            updater_size=len(self.updater_bytes),
            updater_version="5.1.2",
            core_sha=self.core_zip_sha,
            core_size=self.core_zip_size,
            core_installed_sha=self.core_installed_sha,
            core_version="5.1.2",
        )

        # Build package trees
        self.prod_tree = tmp_path / "production_package"
        self.proof_tree = tmp_path / "proof_package"
        self._populate_package_tree(self.prod_tree, self.prod_profile_raw)
        self._populate_package_tree(self.proof_tree, self.proof_profile_raw)

        # Proof install root
        self.install_root = tmp_path / "proof_install"
        self._populate_install_root(self.install_root)

        # Candidate (seq 2, mandatory)
        self.candidate_launcher_bytes = b"MZ_NEKO_LAUNCHER_PROOF_CANDIDATE_V513"
        self.candidate_launcher_sha = hashlib.sha256(
            self.candidate_launcher_bytes
        ).hexdigest()

        self.candidate_core_dir = tmp_path / "candidate_core_bundle"
        self.candidate_core_zip_path = tmp_path / "candidate_core.zip"
        (
            self.candidate_core_zip_bytes,
            self.candidate_core_zip_sha,
            self.candidate_core_zip_size,
            self.candidate_core_installed_sha,
        ) = _build_core_bundle(
            self.candidate_core_dir,
            self.candidate_core_zip_path,
            version="5.1.3",
            source_commit="cand513",
        )

        (
            self.candidate_envelope_bytes,
            self.candidate_envelope_doc,
            self.candidate_binding,
        ) = _make_signed_release_envelope(
            release_priv=self.proof_priv,
            key_id=self.proof_key_id,
            sequence=2,
            release_id="proof-k1-0002",
            channel="stable",
            mandatory=True,
            minimum_supported_sequence=2,
            launcher_sha=self.candidate_launcher_sha,
            launcher_size=len(self.candidate_launcher_bytes),
            launcher_version="5.1.3",
            updater_sha=self.updater_sha,
            updater_size=len(self.updater_bytes),
            updater_version="5.1.2",
            core_sha=self.candidate_core_zip_sha,
            core_size=self.candidate_core_zip_size,
            core_installed_sha=self.candidate_core_installed_sha,
            core_version="5.1.3",
        )

        self.routes = _build_proof_channel_routes(
            owner="Valeneko-pranmong",
            repo="Neko-Family-Proxy-Updates-Proof",
            tag="v5.1.3",
            manifest_bytes=self.candidate_envelope_bytes,
            launcher_bytes=self.candidate_launcher_bytes,
            updater_bytes=self.updater_bytes,
            core_bytes=self.candidate_core_zip_bytes,
        )

    def make_release(
        self,
        *,
        sequence: int,
        release_id: str,
        channel: str = "stable",
        mandatory: bool = False,
        minimum_supported_sequence: int = 1,
        launcher_sha: str | None = None,
        launcher_size: int | None = None,
        launcher_version: str = "5.1.2",
        updater_sha: str | None = None,
        updater_size: int | None = None,
        updater_version: str = "5.1.2",
        core_sha: str | None = None,
        core_size: int | None = None,
        core_installed_sha: str | None = None,
        core_version: str = "5.1.2",
        key_id: str | None = None,
        release_priv: Ed25519PrivateKey | None = None,
    ) -> tuple[bytes, dict[str, Any], AuthenticatedReleaseBinding]:
        return _make_signed_release_envelope(
            release_priv=release_priv or self.proof_priv,
            key_id=key_id or self.proof_key_id,
            sequence=sequence,
            release_id=release_id,
            channel=channel,
            mandatory=mandatory,
            minimum_supported_sequence=minimum_supported_sequence,
            launcher_sha=launcher_sha or self.launcher_sha,
            launcher_size=launcher_size if launcher_size is not None else len(self.launcher_bytes),
            launcher_version=launcher_version,
            updater_sha=updater_sha or self.updater_sha,
            updater_size=updater_size if updater_size is not None else len(self.updater_bytes),
            updater_version=updater_version,
            core_sha=core_sha or self.core_zip_sha,
            core_size=core_size if core_size is not None else self.core_zip_size,
            core_installed_sha=core_installed_sha or self.core_installed_sha,
            core_version=core_version,
        )

    def _populate_package_tree(self, tree: Path, profile_raw: bytes) -> None:
        tree.mkdir(parents=True, exist_ok=True)
        (tree / "NekoLauncher.exe").write_bytes(self.launcher_bytes)
        (tree / "NekoUpdater.exe").write_bytes(self.updater_bytes)
        proxy_core = tree / "ProxyCore"
        if proxy_core.exists():
            shutil.rmtree(proxy_core)
        shutil.copytree(self.core_dir, proxy_core)
        trust_dir = tree / "trust"
        trust_dir.mkdir(parents=True, exist_ok=True)
        (trust_dir / "update-profile-v1.json").write_bytes(profile_raw)

    def _populate_install_root(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "NekoLauncher.exe").write_bytes(self.launcher_bytes)
        (root / "NekoUpdater.exe").write_bytes(self.updater_bytes)
        proxy_core = root / "ProxyCore"
        if proxy_core.exists():
            shutil.rmtree(proxy_core)
        shutil.copytree(self.core_dir, proxy_core)
        trust_dir = root / "trust"
        trust_dir.mkdir(parents=True, exist_ok=True)
        (trust_dir / "update-profile-v1.json").write_bytes(self.proof_profile_raw)
        baseline_dir = root / "baseline"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        (baseline_dir / "release-v2.json").write_bytes(
            self.baseline_envelope_bytes
        )

        old_id = (
            f"g-{self.baseline_binding.release_sequence:020d}-"
            f"{self.baseline_binding.payload_sha256}"
        )
        old_dir = root / "releases" / old_id
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "NekoLauncher.exe").write_bytes(self.launcher_bytes)
        old_proxy_core = old_dir / "ProxyCore"
        if old_proxy_core.exists():
            shutil.rmtree(old_proxy_core)
        shutil.copytree(self.core_dir, old_proxy_core)
        (old_dir / "release-envelope.json").write_bytes(
            self.baseline_envelope_bytes
        )


def test_v512_packaged_baseline_equivalence_and_offline_enrollment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 1: Fresh proof/production baseline equivalence and offline enrollment."""
    assert RA8_PACKAGE_SOURCE_SHA == "3348d1f7eb324aab34860c103a888223be01e805"

    harness = ProofHarnessFixture(tmp_path, monkeypatch)

    # 1. Mechanical build equivalence
    res = compare_builds(
        harness.prod_tree,
        harness.proof_tree,
        profile_authority_public_keys=harness.profile_keys,
    )
    assert res.equivalent is True
    assert res.updater_byte_identical is True
    assert res.unexpected_differences == ()
    assert res.allowed_differences == ("trust/update-profile-v1.json",)

    # 2. Offline enrollment of proof-equivalent 5.1.2
    envelope_path = harness.install_root / "baseline" / "release-v2.json"
    enroll_result = enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=envelope_path,
        trust_profile=harness.verified_proof_profile,
    )
    assert isinstance(enroll_result, BaselineEnrollmentResult)
    assert enroll_result.enrolled is True
    assert enroll_result.error is None
    assert enroll_result.binding == harness.baseline_binding

    # 3. Re-check RT1/K1 Invariants A–G
    # Invariant A: Separate proof/production release keys
    prod_keys = set(harness.verified_prod_profile.release_public_keys.keys())
    proof_keys = set(harness.verified_proof_profile.release_public_keys.keys())
    assert prod_keys.isdisjoint(proof_keys)

    # Invariant B: Common Profile Authority root
    assert (
        harness.verified_prod_profile.profile_authority_public_key_sha256
        == harness.verified_proof_profile.profile_authority_public_key_sha256
    )

    # Invariant C: Production profile contains no proof release key/fallback
    assert harness.proof_key_id not in prod_keys

    # Invariant D: Proof profile contains exactly proof release key and no production fallback
    assert list(proof_keys) == [harness.proof_key_id]

    # Invariant E: No runtime profile/key switch
    loaded = load_installed_update_trust_profile(harness.install_root)
    assert loaded.profile_id == "proof-v512"

    # Invariant F: Exact enrollment profile/keyset pins
    marker = validate_enrollment_trust_binding(
        harness.install_root, harness.verified_proof_profile
    )
    assert (
        marker.profile_envelope_sha256
        == harness.verified_proof_profile.profile_envelope_sha256
    )
    assert marker.keyset_sha256 == harness.verified_proof_profile.keyset_sha256

    # Invariant G: Byte-identical baseline Updater
    prod_updater_sha = hashlib.sha256(
        (harness.prod_tree / "NekoUpdater.exe").read_bytes()
    ).hexdigest()
    proof_updater_sha = hashlib.sha256(
        (harness.install_root / "NekoUpdater.exe").read_bytes()
    ).hexdigest()
    assert proof_updater_sha == prod_updater_sha


def test_v512_proof_self_resolution_returns_latest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 2: Proof baseline querying proof channel returns LATEST / NO UPDATE."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    local_identity = reader.read(harness.install_root)
    assert local_identity.committed == harness.baseline_binding

    # Setup proof channel serving exact same baseline envelope
    routes = _build_proof_channel_routes(
        owner="Valeneko-pranmong",
        repo="Neko-Family-Proxy-Updates-Proof",
        tag="v5.1.2",
        manifest_bytes=harness.baseline_envelope_bytes,
        launcher_bytes=harness.launcher_bytes,
        updater_bytes=harness.updater_bytes,
        core_bytes=harness.core_zip_bytes,
    )
    opener = ReusableFakeTransportOpener(routes)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )

    coordinator, _, _, resolver = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        local_identity,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    check_result, resolved = coordinator._check_service.check_startup_with_resolved()
    assert check_result.state == UpdateState.LATEST
    assert check_result.release_sequence == 1
    assert check_result.release_id == "proof-k1-0001"
    assert check_result.changed_components == ()

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.IDLE
    assert snapshot.pending is None

    _assert_public_unauthenticated_requests(opener)


def test_v512_to_v513_proof_newer_candidate_mandatory_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 3: Proof seq N+1 with mandatory=true or minimum_supported_sequence=N+1 is mandatory."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    local_identity = reader.read(harness.install_root)

    components = (
        ComponentRelease(
            name="launcher",
            version="5.1.3",
            artifact_id="NekoLauncher.exe",
            artifact_sha256=harness.candidate_launcher_sha,
            artifact_size=len(harness.candidate_launcher_bytes),
            installed_identity_sha256=harness.candidate_launcher_sha,
        ),
        ComponentRelease(
            name="core",
            version="5.1.3",
            artifact_id="NekoProxyCore.zip",
            artifact_sha256=harness.candidate_core_zip_sha,
            artifact_size=harness.candidate_core_zip_size,
            installed_identity_sha256=harness.candidate_core_installed_sha,
        ),
    )

    # Case A: mandatory=True
    auth_release_mandatory = ReleaseSet(
        schema_version=1,
        channel="stable",
        release_sequence=2,
        release_id="proof-k1-0002",
        mandatory=True,
        minimum_supported_sequence=1,
        components=components,
        payload_sha256=harness.candidate_binding.payload_sha256,
    )
    check_mandatory = evaluate_release(
        local_identity,
        auth_release_mandatory,
        UpdateInvocationReason.STARTUP,
    )
    assert check_mandatory.state == UpdateState.MANDATORY

    # Case B: mandatory=False, but minimum_supported_sequence=2 (committed=1)
    auth_release_min_seq = ReleaseSet(
        schema_version=1,
        channel="stable",
        release_sequence=2,
        release_id="proof-k1-0002-non-mand",
        mandatory=False,
        minimum_supported_sequence=2,
        components=components,
        payload_sha256="a" * 64,
    )
    check_min_seq = evaluate_release(
        local_identity,
        auth_release_min_seq,
        UpdateInvocationReason.STARTUP,
    )
    assert check_min_seq.state == UpdateState.MANDATORY


def test_v512_to_v513_proof_authenticated_incomplete_mandatory_staging_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 4: Authenticated-but-incomplete mandatory admission, crash/network failure, and staging recovery."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    local_identity = reader.read(harness.install_root)

    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )
    opener = ReusableFakeTransportOpener(harness.routes)

    admission_service, adm_procs, adm_codes, adm_chans = (
        _create_admission_runner(
            harness.install_root,
            dict(harness.verified_proof_profile.release_public_keys),
            None,
        )
    )

    coordinator, stage_service, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        local_identity,
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    # Simulate network failure midway during artifact download
    original_download = stage_service._asset_downloader.download

    def failing_download(*args: Any, **kwargs: Any) -> Any:
        raise GitHubAssetDownloadError("CONNECTION_RESET")

    stage_service._asset_downloader.download = failing_download  # type: ignore[assignment]

    fail_snapshot = coordinator.startup()
    assert fail_snapshot.state == UpdateLifecycleState.IDLE
    assert fail_snapshot.pending is None

    # Verify admission helper process executed ADMIT_AUTHORITY and exited 0 without activation
    assert len(adm_codes) == 1
    assert adm_codes[0] == 0

    # Verify updater state on disk after failed download
    state = load_selected_state(
        harness.install_root / "state",
        harness.verified_proof_profile.release_public_keys,
    )
    assert state is not None
    assert state.phase == "IDLE"
    assert state.transaction is None
    assert state.failed is None
    assert state.committed.binding.release_sequence == 1
    assert (
        state.highwater.release_sequence
        == harness.candidate_binding.release_sequence
    )
    assert (
        state.highwater.release_id == harness.candidate_binding.release_id
    )
    assert (
        state.highwater.payload_sha256
        == harness.candidate_binding.payload_sha256
    )
    assert (
        state.observed.release_sequence
        == harness.candidate_binding.release_sequence
    )
    assert (
        state.observed.release_id == harness.candidate_binding.release_id
    )
    assert (
        state.observed.payload_sha256
        == harness.candidate_binding.payload_sha256
    )

    # Discovery unavailable (offline): prove non-bricking runtime
    offline_opener = ReusableFakeTransportOpener({})
    offline_coordinator, _, _, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        offline_opener,
        reader.read(harness.install_root),
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )
    assert offline_coordinator.current().state == UpdateLifecycleState.IDLE
    assert offline_coordinator.startup().state == UpdateLifecycleState.IDLE

    # Restore network and verify idempotent admission + successful staging retry
    stage_service._asset_downloader.download = original_download  # type: ignore[assignment]
    retry_admit = admission_service.admit(harness.candidate_envelope_bytes)
    assert retry_admit.accepted is True
    assert retry_admit.changed is False  # Idempotent re-admission

    retry_coordinator, _, _, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        reader.read(harness.install_root),
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )
    recovered_snapshot = retry_coordinator.startup()
    assert recovered_snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert recovered_snapshot.pending is not None
    assert recovered_snapshot.pending.release_sequence == 2
    assert recovered_snapshot.pending.release_id == "proof-k1-0002"

    # Assert legacy direct-online prepare() path is fail-closed and unused
    legacy_apply = SoftwareUpdateApplyService(root_dir=harness.install_root)
    with pytest.raises(
        SoftwareUpdateApplyError, match="PENDING_UPDATE_REQUIRED"
    ):
        legacy_apply.prepare()


def test_v512_to_v513_proof_active_game_defers_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 5: When session/game is active, apply of pending update is deferred."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )
    opener = ReusableFakeTransportOpener(harness.routes)

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        reader.read(harness.install_root),
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.UPDATE_PENDING
    assert snapshot.pending is not None

    # Simulate active game session
    active_state = AppState(
        game_status=GameStatus.RUNNING,
        proxy_status=ProxyStatus.RUNNING,
        game_process_running=True,
    )
    safety = evaluate_update_apply_safety(active_state)
    assert safety.safe is False
    assert safety.blocker == UpdateApplyBlocker.GAME_ACTIVE

    apply_service = SoftwareUpdateApplyService(root_dir=harness.install_root)
    deferred_res = try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=apply_service,
        game_active=lambda: True,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )
    assert deferred_res == PendingUpdateBootstrapResult.DEFERRED
    # Game session remains intact
    assert active_state.game_status == GameStatus.RUNNING


def test_v512_to_v513_proof_safe_state_apply_consumes_pending_with_exact_updater(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 6: Safe-state apply consumes durable pending using exact proof-baseline NekoUpdater.exe."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )
    opener = ReusableFakeTransportOpener(harness.routes)

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        reader.read(harness.install_root),
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    coordinator.startup()

    # Assert exact proof-baseline NekoUpdater.exe SHA equals production helper evidence before apply
    prod_updater_sha = hashlib.sha256(
        (harness.prod_tree / "NekoUpdater.exe").read_bytes()
    ).hexdigest()
    proof_updater_sha = hashlib.sha256(
        (harness.install_root / "NekoUpdater.exe").read_bytes()
    ).hexdigest()
    assert proof_updater_sha == prod_updater_sha

    # Safe-state apply with game_active=False
    apply_service, proc_refs, exit_codes, _ = _create_helper_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
        self_test_pass=True,
    )

    apply_result = try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=apply_service,
        game_active=lambda: False,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )
    assert apply_result == PendingUpdateBootstrapResult.HANDOFF_STARTED

    assert proc_refs
    proc_refs[0].thread.join(timeout=10.0)
    assert not proc_refs[0].thread.is_alive()
    assert exit_codes[0] == 0


def test_v512_to_v513_proof_restart_probation_commits_n_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 7: Relaunch, probation, and committed binding advances to N+1."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )
    opener = ReusableFakeTransportOpener(harness.routes)

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        reader.read(harness.install_root),
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    coordinator.startup()

    apply_service, proc_refs, exit_codes, _ = _create_helper_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
        self_test_pass=True,
    )
    try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=apply_service,
        game_active=lambda: False,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )
    proc_refs[0].thread.join(timeout=10.0)

    # Verify committed binding advanced in SlotStore
    state = load_selected_state(
        harness.install_root / "state",
        harness.verified_proof_profile.release_public_keys,
    )
    assert state is not None
    assert (
        state.committed.binding.release_sequence
        == harness.candidate_binding.release_sequence
    )
    assert (
        state.committed.binding.release_id
        == harness.candidate_binding.release_id
    )
    assert (
        state.committed.binding.payload_sha256
        == harness.candidate_binding.payload_sha256
    )
    assert (
        state.highwater.release_sequence
        == harness.candidate_binding.release_sequence
    )
    assert state.failed is None
    assert state.transaction is None

    # Published generation directory exists
    published_dir = (
        harness.install_root
        / "releases"
        / f"g-{harness.candidate_binding.release_sequence:020d}-{harness.candidate_binding.payload_sha256}"
    )
    assert published_dir.is_dir()
    assert (published_dir / "NekoLauncher.exe").is_file()
    assert (published_dir / "ProxyCore").is_dir()

    # Local release identity advances to N+1
    local2 = reader.read(harness.install_root)
    assert local2.committed == harness.candidate_binding


def test_v512_to_v513_proof_offline_pending_apply_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 8: After verified pending is durable, completely offline apply still succeeds."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )
    opener = ReusableFakeTransportOpener(harness.routes)

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        reader.read(harness.install_root),
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    # Stage candidate to durable pending
    coordinator.startup()
    assert pending_store.load_verified(reader.read(harness.install_root)) is not None

    # Disable network fixture completely (zero routes, zero requests allowed)
    harness.routes.clear()
    offline_opener = ReusableFakeTransportOpener({})

    apply_service, proc_refs, exit_codes, _ = _create_helper_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
        self_test_pass=True,
    )

    apply_res = try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=apply_service,
        game_active=lambda: False,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )
    assert apply_res == PendingUpdateBootstrapResult.HANDOFF_STARTED

    proc_refs[0].thread.join(timeout=10.0)
    assert exit_codes[0] == 0

    # Ensure zero network requests were made during offline apply
    assert len(offline_opener.captured_requests) == 0

    # Committed state advances to N+1
    state = load_selected_state(
        harness.install_root / "state",
        harness.verified_proof_profile.release_public_keys,
    )
    assert state is not None
    assert state.committed.binding.release_sequence == 2
    assert state.committed.binding.release_id == "proof-k1-0002"


def test_v512_to_v513_proof_same_sequence_exact_binding_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA9 Step 1: Same-sequence exact-binding is a no-op / LATEST and does not stage an update."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    local_identity = reader.read(harness.install_root)
    assert local_identity.committed == harness.baseline_binding

    # Setup proof channel serving exact same baseline envelope
    routes = _build_proof_channel_routes(
        owner="Valeneko-pranmong",
        repo="Neko-Family-Proxy-Updates-Proof",
        tag="v5.1.2",
        manifest_bytes=harness.baseline_envelope_bytes,
        launcher_bytes=harness.launcher_bytes,
        updater_bytes=harness.updater_bytes,
        core_bytes=harness.core_zip_bytes,
    )
    opener = ReusableFakeTransportOpener(routes)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        local_identity,
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    check_result, _ = coordinator._check_service.check_startup_with_resolved()
    assert check_result.state == UpdateState.LATEST
    assert check_result.diagnostic_code is None
    assert check_result.changed_components == ()
    assert check_result.retry_staging is False

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.IDLE
    assert snapshot.pending is None

    local_after = reader.read(harness.install_root)
    assert local_after.committed == harness.baseline_binding
    assert local_after.high_water == harness.baseline_binding
    assert local_after.failed is None


def test_v512_to_v513_proof_same_sequence_changed_identity_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA9 Step 2: Same-sequence changed payload/release_id requires fail-closed identity conflict."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    local_identity = reader.read(harness.install_root)
    assert local_identity.committed == harness.baseline_binding

    # Mint conflicting envelope at same sequence (seq 1) with different release_id and altered payload
    alt_bytes, alt_doc, alt_binding = harness.make_release(
        sequence=1,
        release_id="proof-k1-0001-conflict",
        launcher_version="5.1.2",
        core_version="5.1.2",
    )
    assert alt_binding.release_sequence == local_identity.committed.release_sequence
    assert alt_binding != local_identity.committed

    routes = _build_proof_channel_routes(
        owner="Valeneko-pranmong",
        repo="Neko-Family-Proxy-Updates-Proof",
        tag="v5.1.2",
        manifest_bytes=alt_bytes,
        launcher_bytes=harness.launcher_bytes,
        updater_bytes=harness.updater_bytes,
        core_bytes=harness.core_zip_bytes,
    )
    opener = ReusableFakeTransportOpener(routes)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        local_identity,
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    check_result, _ = coordinator._check_service.check_startup_with_resolved()
    assert check_result.state == UpdateState.VERIFY_FAILED
    assert (
        check_result.diagnostic_code
        == UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT
    )
    assert check_result.retry_staging is False

    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.IDLE
    assert snapshot.pending is None

    # Local identity remains unmutated
    local_after = reader.read(harness.install_root)
    assert local_after.committed == harness.baseline_binding
    assert local_after.high_water == harness.baseline_binding
    assert local_after.failed is None


def test_v512_to_v513_proof_lower_than_high_water_replay_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA9 Step 3: Lower-than-high-water replay is rejected fail-closed with DOWNGRADE_REJECTED."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    baseline_components = (
        ComponentRelease(
            name="launcher",
            version="5.1.2",
            artifact_id="NekoLauncher.exe",
            artifact_sha256=harness.launcher_sha,
            artifact_size=len(harness.launcher_bytes),
            installed_identity_sha256=harness.launcher_sha,
        ),
        ComponentRelease(
            name="core",
            version="5.1.2",
            artifact_id="NekoProxyCore.zip",
            artifact_sha256=harness.core_zip_sha,
            artifact_size=harness.core_zip_size,
            installed_identity_sha256=harness.core_installed_sha,
        ),
    )

    # Local identity with high-water at seq 2
    local_v2 = LocalReleaseIdentity(
        committed=harness.candidate_binding,
        high_water=harness.candidate_binding,
        observed=harness.candidate_binding,
        failed=None,
        launcher_version="5.1.3",
        launcher_installed_identity_sha256=harness.candidate_launcher_sha,
        updater_version="5.1.2",
        updater_installed_identity_sha256=harness.updater_sha,
        core_version="5.1.3",
        core_installed_identity_sha256=harness.candidate_core_installed_sha,
    )

    # Remote attempts to serve replayed seq 1 (baseline)
    replayed_release = ReleaseSet(
        schema_version=1,
        channel="stable",
        release_sequence=1,
        release_id="proof-k1-0001",
        mandatory=False,
        minimum_supported_sequence=1,
        components=baseline_components,
        payload_sha256=harness.baseline_binding.payload_sha256,
    )

    check_res = evaluate_release(
        local_v2,
        replayed_release,
        UpdateInvocationReason.STARTUP,
    )
    assert check_res.state == UpdateState.VERIFY_FAILED
    assert check_res.diagnostic_code == UpdateDiagnosticCode.DOWNGRADE_REJECTED
    assert check_res.retry_staging is False


def test_v512_to_v513_proof_probation_failure_rolls_back_to_n(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA9 Step 4: Broken candidate/probation failure rolls back to N; high-water & failed remain N+1."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )
    opener = ReusableFakeTransportOpener(harness.routes)

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        opener,
        reader.read(harness.install_root),
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    # Stage candidate N+1
    coordinator.startup()
    assert pending_store.load_verified(reader.read(harness.install_root)) is not None

    # Helper apply runs with broken candidate: self_test_pass=False
    apply_service, proc_refs, exit_codes, _ = _create_helper_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
        self_test_pass=False,
    )

    apply_result = try_apply_pending_on_launch(
        pending_store=pending_store,
        apply_service=apply_service,
        game_active=lambda: False,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )
    assert apply_result == PendingUpdateBootstrapResult.HANDOFF_STARTED

    proc_refs[0].thread.join(timeout=10.0)
    assert exit_codes[0] != 0

    # Verify state rolled back to baseline N, while high-water & failed record N+1
    state = load_selected_state(
        harness.install_root / "state",
        harness.verified_proof_profile.release_public_keys,
    )
    assert state is not None
    assert state.phase in ("CLEANING", "IDLE")
    assert (
        state.committed.binding.release_sequence
        == harness.baseline_binding.release_sequence
    )
    assert (
        state.committed.binding.release_id
        == harness.baseline_binding.release_id
    )
    assert (
        state.highwater.release_sequence
        == harness.candidate_binding.release_sequence
    )
    assert state.failed is not None
    assert (
        state.failed.release_sequence
        == harness.candidate_binding.release_sequence
    )
    assert state.last_error == "SELFTEST_FAILED"

    # Recovery converges to OLD_FULLY_RESTORED / baseline N
    rec = RecoveryEngine(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
    ).run_recovery()
    assert rec.converged is True
    assert rec.status == "OLD_FULLY_RESTORED"
    assert rec.final_state is not None
    assert rec.final_state.phase == "IDLE"
    assert (
        rec.selected_generation.binding.release_sequence
        == harness.baseline_binding.release_sequence
    )

    # Baseline N generation files remain intact and runnable
    baseline_dir = (
        harness.install_root
        / "releases"
        / f"g-{harness.baseline_binding.release_sequence:020d}-{harness.baseline_binding.payload_sha256}"
    )
    assert baseline_dir.is_dir()
    assert (baseline_dir / "NekoLauncher.exe").is_file()
    assert (baseline_dir / "ProxyCore").is_dir()

    # Identity reader reflects committed=N, high_water=N+1, failed=N+1
    local_after = reader.read(harness.install_root)
    assert local_after.committed == harness.baseline_binding
    assert local_after.high_water == harness.candidate_binding
    assert local_after.failed == harness.candidate_binding


def test_v512_to_v513_proof_rediscovery_after_failure_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA9 Step 5: Rediscovery matrix: exact failed N+1 is known/no-new-update; changed N+1 conflicts; N+2 is candidate."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)

    candidate_components = (
        ComponentRelease(
            name="launcher",
            version="5.1.3",
            artifact_id="NekoLauncher.exe",
            artifact_sha256=harness.candidate_launcher_sha,
            artifact_size=len(harness.candidate_launcher_bytes),
            installed_identity_sha256=harness.candidate_launcher_sha,
        ),
        ComponentRelease(
            name="core",
            version="5.1.3",
            artifact_id="NekoProxyCore.zip",
            artifact_sha256=harness.candidate_core_zip_sha,
            artifact_size=harness.candidate_core_zip_size,
            installed_identity_sha256=harness.candidate_core_installed_sha,
        ),
    )

    # Post-probation-failure identity: committed=seq 1, high_water=seq 2, failed=seq 2
    local_failed = LocalReleaseIdentity(
        committed=harness.baseline_binding,
        high_water=harness.candidate_binding,
        observed=harness.candidate_binding,
        failed=harness.candidate_binding,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256=harness.launcher_sha,
        updater_version="5.1.2",
        updater_installed_identity_sha256=harness.updater_sha,
        core_version="5.1.2",
        core_installed_identity_sha256=harness.core_installed_sha,
    )

    # Case A: Exact failed N+1 is re-offered
    exact_failed_release = ReleaseSet(
        schema_version=1,
        channel="stable",
        release_sequence=2,
        release_id="proof-k1-0002",
        mandatory=True,
        minimum_supported_sequence=1,
        components=candidate_components,
        payload_sha256=harness.candidate_binding.payload_sha256,
    )
    check_a = evaluate_release(
        local_failed,
        exact_failed_release,
        UpdateInvocationReason.STARTUP,
    )
    assert check_a.state == UpdateState.LATEST
    assert check_a.diagnostic_code is None
    assert check_a.changed_components == ()
    assert check_a.retry_staging is False

    # Case B: Changed N+1 is offered (same sequence 2, different payload / release_id)
    changed_n1_release = ReleaseSet(
        schema_version=1,
        channel="stable",
        release_sequence=2,
        release_id="proof-k1-0002-tampered",
        mandatory=True,
        minimum_supported_sequence=1,
        components=candidate_components,
        payload_sha256="f" * 64,
    )
    check_b = evaluate_release(
        local_failed,
        changed_n1_release,
        UpdateInvocationReason.STARTUP,
    )
    assert check_b.state == UpdateState.VERIFY_FAILED
    assert (
        check_b.diagnostic_code
        == UpdateDiagnosticCode.SAME_SEQUENCE_IDENTITY_CONFLICT
    )
    assert check_b.retry_staging is False

    # Case C: N+2 candidate is offered (seq 3 > high_water seq 2)
    n2_components = (
        ComponentRelease(
            name="launcher",
            version="5.1.4",
            artifact_id="NekoLauncher.exe",
            artifact_sha256="4" * 64,
            artifact_size=len(harness.candidate_launcher_bytes),
            installed_identity_sha256="4" * 64,
        ),
        ComponentRelease(
            name="core",
            version="5.1.4",
            artifact_id="NekoProxyCore.zip",
            artifact_sha256="5" * 64,
            artifact_size=harness.candidate_core_zip_size,
            installed_identity_sha256="5" * 64,
        ),
    )
    n2_release = ReleaseSet(
        schema_version=1,
        channel="stable",
        release_sequence=3,
        release_id="proof-k1-0003",
        mandatory=True,
        minimum_supported_sequence=1,
        components=n2_components,
        payload_sha256="6" * 64,
    )
    check_c = evaluate_release(
        local_failed,
        n2_release,
        UpdateInvocationReason.STARTUP,
    )
    assert check_c.state == UpdateState.MANDATORY
    assert check_c.diagnostic_code is None
    assert set(check_c.changed_components) == {"launcher", "core"}


def test_v512_to_v513_proof_restart_crash_recovery_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA9 Step 6: Restart/crash boundaries around PREPARING, QUIESCING, PROBATION, CLEANING, ROLLING_BACK; require only OLD_FULLY_RESTORED, NEW_FULLY_COMMITTED, or REPAIR_REQUIRED."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    b_gen1 = Binding(
        release_sequence=harness.baseline_binding.release_sequence,
        release_id=harness.baseline_binding.release_id,
        payload_sha256=harness.baseline_binding.payload_sha256,
    )
    b_gen2 = Binding(
        release_sequence=harness.candidate_binding.release_sequence,
        release_id=harness.candidate_binding.release_id,
        payload_sha256=harness.candidate_binding.payload_sha256,
    )

    gen1 = Generation(
        binding=b_gen1,
        launcher_identity_sha256=harness.launcher_sha,
        core_identity_sha256=harness.core_installed_sha,
    )
    gen2 = Generation(
        binding=b_gen2,
        launcher_identity_sha256=harness.candidate_launcher_sha,
        core_identity_sha256=harness.candidate_core_installed_sha,
    )

    keys = dict(harness.verified_proof_profile.release_public_keys)
    state_dir = harness.install_root / "state"

    def _write_slot(st: State) -> None:
        for s in (state_dir / "slot-a.bin", state_dir / "slot-b.bin"):
            s.unlink(missing_ok=True)
        packed = pack_slot_frame(
            SlotFrame(revision=st.revision, format_version=1, body_bytes=serialize_state(st))
        )
        (state_dir / "slot-a.bin").write_bytes(packed)

    evidence_dict = {
        harness.baseline_binding.payload_sha256: base64.b64encode(harness.baseline_envelope_bytes).decode("ascii"),
        harness.candidate_binding.payload_sha256: base64.b64encode(harness.candidate_envelope_bytes).decode("ascii"),
    }

    allowed_terminal_statuses = {"OLD_FULLY_RESTORED", "NEW_FULLY_COMMITTED", "REPAIR_REQUIRED"}

    # 1. PREPARING boundary
    tx_prep = Transaction(
        id="1" * 32,
        request_id="2" * 32,
        candidate=gen2,
        old=gen1,
        incoming=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        staging=None,
        stage="ADMITTED",
        mutation=None,
    )
    s_prep = State(
        schema_version=1,
        revision=10,
        installation_id="a" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PREPARING",
        committed=gen1,
        previous=None,
        highwater=b_gen1,
        observed=b_gen2,
        failed=None,
        transaction=tx_prep,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence=evidence_dict,
    )
    _write_slot(s_prep)
    rec = RecoveryEngine(harness.install_root, keys).run_recovery()
    assert rec.status in allowed_terminal_statuses
    assert rec.status == "OLD_FULLY_RESTORED"
    assert rec.converged is True
    assert rec.selected_generation == gen1

    # 2. QUIESCING boundary
    tx_quiesce = Transaction(
        id="3" * 32,
        request_id="4" * 32,
        candidate=gen2,
        old=gen1,
        incoming=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        staging=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="1" * 32, parent_file_id="0" * 32),
        stage="QUIESCING",
        mutation=Mutation(kind="STOP_OLD", target="old_process_family", status="INTENT"),
    )
    s_quiesce = State(
        schema_version=1,
        revision=20,
        installation_id="a" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="QUIESCING",
        committed=gen1,
        previous=None,
        highwater=b_gen1,
        observed=b_gen2,
        failed=None,
        transaction=tx_quiesce,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence=evidence_dict,
    )
    _write_slot(s_quiesce)
    rec = RecoveryEngine(harness.install_root, keys).run_recovery()
    assert rec.status in allowed_terminal_statuses
    assert rec.status == "OLD_FULLY_RESTORED"
    assert rec.converged is True
    assert rec.selected_generation == gen1
    assert rec.final_state is not None
    assert rec.final_state.failed == b_gen2

    # 3. PROBATION boundary
    tx_prob = Transaction(
        id="5" * 32,
        request_id="6" * 32,
        candidate=gen2,
        old=gen1,
        incoming=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        staging=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="1" * 32, parent_file_id="0" * 32),
        stage="PROBATION",
        mutation=Mutation(kind="START_PROBATION", target="candidate_process_family", status="INTENT"),
    )
    s_prob = State(
        schema_version=1,
        revision=30,
        installation_id="a" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="PROBATION",
        committed=gen1,
        previous=None,
        highwater=b_gen1,
        observed=b_gen2,
        failed=None,
        transaction=tx_prob,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence=evidence_dict,
    )
    _write_slot(s_prob)
    rec = RecoveryEngine(harness.install_root, keys).run_recovery()
    assert rec.status in allowed_terminal_statuses
    assert rec.status == "OLD_FULLY_RESTORED"
    assert rec.converged is True
    assert rec.selected_generation == gen1
    assert rec.final_state is not None
    assert rec.final_state.failed == b_gen2

    # 4. CLEANING boundary
    cleanup_item = Cleanup(
        transaction_id="8" * 32,
        request_id="9" * 32,
        directory=DirectoryIdentity(volume_serial="12345678abcdef01", file_id="0" * 32, parent_file_id="0" * 32),
        target="incoming",
        status="INTENT",
    )
    s_clean = State(
        schema_version=1,
        revision=40,
        installation_id="a" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="CLEANING",
        committed=gen1,
        previous=None,
        highwater=b_gen1,
        observed=b_gen2,
        failed=None,
        transaction=None,
        cleanup=[cleanup_item],
        rollback=None,
        last_error=None,
        evidence=evidence_dict,
    )
    _write_slot(s_clean)
    rec = RecoveryEngine(harness.install_root, keys).run_recovery()
    assert rec.status in allowed_terminal_statuses
    assert rec.status == "OLD_FULLY_RESTORED"
    assert rec.converged is True
    assert rec.selected_generation == gen1

    # 5. ROLLING_BACK boundary
    s_rb = State(
        schema_version=1,
        revision=50,
        installation_id="a" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="ROLLING_BACK",
        committed=gen1,
        previous=None,
        highwater=b_gen1,
        observed=b_gen2,
        failed=b_gen2,
        transaction=None,
        cleanup=None,
        rollback=Rollback(
            mode="precommit",
            target=gen1,
            probation_id="7" * 32,
            scratch=[],
            step="RESTORE_INTENT",
        ),
        last_error="PREVIOUS_FAILURE",
        evidence=evidence_dict,
    )
    _write_slot(s_rb)
    rec = RecoveryEngine(harness.install_root, keys).run_recovery()
    assert rec.status in allowed_terminal_statuses
    assert rec.status == "OLD_FULLY_RESTORED"
    assert rec.converged is True
    assert rec.selected_generation == gen1

    # 6. Explicit REPAIR_REQUIRED boundary (corrupt / missing committed on disk with no previous)
    missing_binding = Binding(
        release_sequence=99,
        release_id="proof-nonexistent",
        payload_sha256="0" * 64,
    )
    missing_gen = Generation(
        binding=missing_binding,
        launcher_identity_sha256="0" * 64,
        core_identity_sha256="0" * 64,
    )
    s_repair = State(
        schema_version=1,
        revision=60,
        installation_id="a" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=missing_gen,
        previous=None,
        highwater=missing_binding,
        observed=missing_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={missing_binding.payload_sha256: "bm9wZQ=="},
    )
    _write_slot(s_repair)
    rec = RecoveryEngine(harness.install_root, keys).run_recovery()
    assert rec.status in allowed_terminal_statuses
    assert rec.status == "REPAIR_REQUIRED"
    assert rec.converged is False
    assert rec.selected_generation is None


def test_v512_to_v513_proof_discovery_outage_non_blocking_when_no_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RA9 Step 7: Discovery-outage while no mandatory pending: committed app remains runnable & update check is non-blocking."""
    harness = ProofHarnessFixture(tmp_path, monkeypatch)
    enroll_baseline_from_signed_envelope(
        install_root=harness.install_root,
        envelope_path=harness.install_root / "baseline" / "release-v2.json",
        trust_profile=harness.verified_proof_profile,
    )

    reader = AuthenticatedReleaseIdentityReader(harness.verified_proof_profile)
    local_identity = reader.read(harness.install_root)

    # Completely dead network routes (outage)
    offline_opener = ReusableFakeTransportOpener({})
    env = types.SimpleNamespace(
        keys=dict(harness.verified_proof_profile.release_public_keys)
    )

    admission_service, _, _, _ = _create_admission_runner(
        harness.install_root,
        dict(harness.verified_proof_profile.release_public_keys),
        None,
    )
    coordinator, _, pending_store, _ = _setup_coordinator_pipeline(
        harness.install_root,
        env,
        None,
        offline_opener,
        local_identity,
        admission_service=admission_service,
        channel_profile=harness.channel_profile,
        local_identity_provider=lambda: reader.read(harness.install_root),
    )

    # Discovery check returns UNAVAILABLE
    check_result, resolved = coordinator._check_service.check_startup_with_resolved()
    assert check_result.state == UpdateState.UNAVAILABLE
    assert resolved is None

    # Coordinator startup succeeds without raising or hanging
    snapshot = coordinator.startup()
    assert snapshot.state == UpdateLifecycleState.IDLE
    assert snapshot.pending is None

    # App is runnable and local identity is uncorrupted
    local_after = reader.read(harness.install_root)
    assert local_after.committed == harness.baseline_binding
    assert local_after.high_water == harness.baseline_binding
    assert local_after.failed is None
