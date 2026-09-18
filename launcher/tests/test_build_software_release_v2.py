from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from neko_launcher.updater.canonical_json import canonical_json_loads
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_software_release_v2.py"
LAUNCHER_SRC = REPO_ROOT / "launcher" / "src"
KEY_ID = "ephemeral-release-test-1"


def load_builder() -> ModuleType:
    """Load the future tool lazily so a missing script is an assertion-level RED."""
    assert SCRIPT.is_file(), f"missing required release-v2 builder: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("build_software_release_v2", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_software_release_v2"] = module
    spec.loader.exec_module(module)
    assert callable(getattr(module, "build_release_v2", None))
    assert callable(getattr(module, "main", None))
    return module


@pytest.fixture
def release_inputs(tmp_path: Path) -> dict[str, Any]:
    launcher_bytes = b"MZ\x00ephemeral launcher artifact\xff"
    updater_bytes = b"MZ\x00ephemeral updater artifact\xee"
    core_bytes = b"PK\x03\x04ephemeral core bundle\x00"
    launcher = tmp_path / "NekoLauncher.exe"
    updater = tmp_path / "NekoUpdater.exe"
    core = tmp_path / "NekoProxyCore.zip"
    launcher.write_bytes(launcher_bytes)
    updater.write_bytes(updater_bytes)
    core.write_bytes(core_bytes)

    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    private_path = tmp_path / "ephemeral-private.key"
    public_path = tmp_path / "ephemeral-public.key"
    private_path.write_bytes(private_raw)
    public_path.write_bytes(public_raw)

    metadata: dict[str, Any] = {
        "schema_version": 2,
        "channel": "stable",
        "release_sequence": 41,
        "release_id": "phase3-test-41",
        "mandatory": False,
        "minimum_supported_sequence": 39,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": "5.1.0a3",
                "artifact_id": "launcher-5.1.0a3-win-x64",
                "artifact_sha256": hashlib.sha256(launcher_bytes).hexdigest(),
                "artifact_size": len(launcher_bytes),
                "installed_identity_sha256": hashlib.sha256(launcher_bytes).hexdigest(),
                "artifact_format": "raw-pe-v1",
            },
            "updater": {
                "version": "5.1.0a3",
                "artifact_id": "updater-5.1.0a3-win-x64",
                "artifact_sha256": hashlib.sha256(updater_bytes).hexdigest(),
                "artifact_size": len(updater_bytes),
                "installed_identity_sha256": hashlib.sha256(updater_bytes).hexdigest(),
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "version": "1.0.0",
                "artifact_id": "core-1.0.0-win-x64",
                "artifact_sha256": hashlib.sha256(core_bytes).hexdigest(),
                "artifact_size": len(core_bytes),
                "installed_identity_sha256": "ab" * 32,
                "artifact_format": "zip-core-v1",
            },
        },
    }
    metadata_path = tmp_path / "release-metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return {
        "metadata": metadata,
        "metadata_path": metadata_path,
        "launcher": launcher,
        "updater": updater,
        "core": core,
        "private_path": private_path,
        "private_raw": private_raw,
        "public_path": public_path,
        "public_raw": public_raw,
        "output": tmp_path / "release-envelope-v2.json",
    }


def build(module: ModuleType, data: dict[str, Any], **changes: object) -> object:
    arguments = {
        "metadata_path": data["metadata_path"],
        "launcher_artifact": data["launcher"],
        "updater_artifact": data["updater"],
        "core_artifact": data["core"],
        "private_key_file": data["private_path"],
        "key_id": KEY_ID,
        "public_key_file": data["public_path"],
        "output": data["output"],
    }
    arguments.update(changes)
    return module.build_release_v2(**arguments)


def write_metadata(data: dict[str, Any], document: object) -> None:
    data["metadata_path"].write_text(json.dumps(document), encoding="utf-8")


def cli_command(data: dict[str, Any], *extra: str) -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(data["metadata_path"]),
        "--launcher-artifact",
        str(data["launcher"]),
        "--updater-artifact",
        str(data["updater"]),
        "--core-artifact",
        str(data["core"]),
        "--private-key-file",
        str(data["private_path"]),
        "--key-id",
        KEY_ID,
        "--public-key-file",
        str(data["public_path"]),
        "--output",
        str(data["output"]),
        *extra,
    ]


def invoke(data: dict[str, Any], *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.is_file(), f"missing required release-v2 builder: {SCRIPT}"
    environment = dict(os.environ if env is None else env)
    environment["PYTHONPATH"] = str(LAUNCHER_SRC)
    environment.pop("TCL_LIBRARY", None)
    environment.pop("TK_LIBRARY", None)
    return subprocess.run(
        cli_command(data, *extra),
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def assert_no_private_material(text: str, private_raw: bytes) -> None:
    markers = (
        private_raw.hex(),
        base64.b64encode(private_raw).decode("ascii"),
        private_raw.decode("latin1"),
    )
    assert all(marker not in text for marker in markers)


def test_build_derives_all_three_artifacts_and_verifies_with_separate_public_key(
    release_inputs: dict[str, Any],
) -> None:
    module = load_builder()
    build(module, release_inputs)

    raw_envelope = release_inputs["output"].read_bytes()
    envelope = canonical_json_loads(raw_envelope)
    release, _payload_hash = verify_release_envelope_v2(
        envelope, {KEY_ID: release_inputs["public_raw"]}
    )
    assert release.channel == "stable"
    for component, artifact in (
        ("launcher", release_inputs["launcher"]),
        ("updater", release_inputs["updater"]),
        ("core", release_inputs["core"]),
    ):
        expected = artifact.read_bytes()
        actual = release.components[component]
        assert actual.artifact_sha256 == hashlib.sha256(expected).hexdigest()
        assert actual.artifact_size == len(expected)
    assert set(envelope) == {
        "envelope_version", "key_id", "payload_b64", "signature_b64"
    }
    assert envelope["envelope_version"] == 1
    assert envelope["key_id"] == KEY_ID


def test_build_is_canonical_and_deterministic(release_inputs: dict[str, Any]) -> None:
    module = load_builder()
    first = release_inputs["output"]
    second = first.with_name("second-envelope.json")
    build(module, release_inputs, output=first)
    build(module, release_inputs, output=second)

    assert first.read_bytes() == second.read_bytes()
    assert canonical_json_loads(first.read_bytes()) == json.loads(first.read_bytes())
    envelope = json.loads(first.read_bytes())
    payload = base64.b64decode(envelope["payload_b64"], validate=True)
    assert canonical_json_loads(payload) == json.loads(payload)


@pytest.mark.parametrize(
    ("component", "field", "bad_value"),
    [
        ("launcher", "artifact_sha256", "0" * 64),
        ("launcher", "artifact_size", 999),
        ("updater", "artifact_sha256", "0" * 64),
        ("updater", "artifact_size", 999),
        ("core", "artifact_sha256", "0" * 64),
        ("core", "artifact_size", 999),
    ],
    ids=["launcher-sha", "launcher-size", "updater-sha", "updater-size", "core-sha", "core-size"],
)
def test_claimed_artifact_metadata_disagreement_is_rejected(
    release_inputs: dict[str, Any], component: str, field: str, bad_value: object
) -> None:
    module = load_builder()
    metadata = copy.deepcopy(release_inputs["metadata"])
    metadata["components"][component][field] = bad_value
    write_metadata(release_inputs, metadata)

    with pytest.raises((ValueError, OSError)):
        build(module, release_inputs)
    assert not release_inputs["output"].exists()


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.update(extra="forbidden"), id="top-level-extra"),
        pytest.param(lambda d: d.update(channel="beta"), id="beta-channel-rejected"),
        pytest.param(lambda d: d["components"]["core"].update(extra="forbidden"), id="component-extra"),
        pytest.param(lambda d: d.pop("release_id"), id="missing-field"),
        pytest.param(lambda d: d.update(updater_protocol={"minimum": 2, "maximum": 1}), id="unknown-protocol"),
        pytest.param(lambda d: d["components"]["launcher"].update(artifact_format="msi-v1"), id="launcher-format"),
        pytest.param(lambda d: d["components"]["updater"].update(artifact_format="msi-v1"), id="updater-format"),
        pytest.param(lambda d: d["components"]["core"].update(artifact_format="tar-core-v1"), id="core-format"),
        pytest.param(lambda d: d["components"]["core"].update(distribution="public"), id="unknown-distribution"),
        pytest.param(lambda d: d["components"].pop("updater"), id="missing-updater-component"),
        pytest.param(lambda d: d["components"].update(agent=d["components"]["core"]), id="unknown-component"),
    ],
)
def test_closed_release_v2_metadata_is_enforced(
    release_inputs: dict[str, Any], mutate: Any
) -> None:
    module = load_builder()
    metadata = copy.deepcopy(release_inputs["metadata"])
    mutate(metadata)
    write_metadata(release_inputs, metadata)

    with pytest.raises((ValueError, TypeError)):
        build(module, release_inputs)
    assert not release_inputs["output"].exists()


@pytest.mark.parametrize("changed_component", ["launcher", "updater", "core"])
def test_artifact_changed_during_build_is_rejected_for_each_component(
    release_inputs: dict[str, Any], changed_component: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_builder()
    original_load = module._load_private_key

    def load_and_tamper(path: Path) -> Any:
        key = original_load(path)

        class WrappedKey:
            def sign(self, data: bytes) -> bytes:
                sig = key.sign(data)
                # Modify the artifact on disk right after signing to simulate change during build
                release_inputs[changed_component].write_bytes(b"tampered-after-sign")
                return sig

        return WrappedKey()

    monkeypatch.setattr(module, "_load_private_key", load_and_tamper)

    with pytest.raises(ValueError, match="ARTIFACT_CHANGED_DURING_BUILD"):
        build(module, release_inputs)

    assert not release_inputs["output"].exists()


def test_existing_output_is_not_overwritten(release_inputs: dict[str, Any]) -> None:
    module = load_builder()
    original = b"immutable existing release output"
    release_inputs["output"].write_bytes(original)

    with pytest.raises((FileExistsError, OSError, ValueError)):
        build(module, release_inputs)
    assert release_inputs["output"].read_bytes() == original


@pytest.mark.parametrize("key_id", ["", "contains space", "x" * 65, None], ids=["empty", "space", "long", "implicit"])
def test_invalid_or_implicit_key_id_is_rejected(
    release_inputs: dict[str, Any], key_id: object
) -> None:
    module = load_builder()
    with pytest.raises((TypeError, ValueError)):
        build(module, release_inputs, key_id=key_id)
    assert not release_inputs["output"].exists()


@pytest.mark.parametrize("which", ["private", "public"])
def test_malformed_key_material_is_rejected_without_leak(
    release_inputs: dict[str, Any], which: str
) -> None:
    module = load_builder()
    malformed = b"SENTINEL_MALFORMED_EPHEMERAL_KEY_MATERIAL"
    release_inputs[f"{which}_path"].write_bytes(malformed)

    with pytest.raises(Exception) as caught:
        build(module, release_inputs)
    assert malformed.decode() not in str(caught.value)
    assert not release_inputs["output"].exists()


def test_non_ed25519_private_key_is_rejected(release_inputs: dict[str, Any]) -> None:
    module = load_builder()
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

    pem = generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    release_inputs["private_path"].write_bytes(pem)
    with pytest.raises((TypeError, ValueError)):
        build(module, release_inputs)
    assert not release_inputs["output"].exists()


def test_wrong_separately_supplied_public_key_is_rejected(
    release_inputs: dict[str, Any],
) -> None:
    module = load_builder()
    wrong_public = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    release_inputs["public_path"].write_bytes(wrong_public)

    with pytest.raises((ValueError, TypeError)):
        build(module, release_inputs)
    assert not release_inputs["output"].exists()


def test_pure_builder_is_offline_only(
    release_inputs: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_builder()

    def network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("release builder attempted network access")

    monkeypatch.setattr("socket.create_connection", network_forbidden)
    monkeypatch.setattr("urllib.request.urlopen", network_forbidden)
    build(module, release_inputs)
    assert release_inputs["output"].is_file()


def test_cli_requires_all_explicit_paths_and_produces_verified_output(
    release_inputs: dict[str, Any],
) -> None:
    completed = invoke(release_inputs)
    combined = completed.stdout + completed.stderr

    assert completed.returncode == 0, combined
    assert_no_private_material(combined, release_inputs["private_raw"])
    envelope = canonical_json_loads(release_inputs["output"].read_bytes())
    verify_release_envelope_v2(envelope, {KEY_ID: release_inputs["public_raw"]})


def test_cli_fails_when_updater_artifact_missing(
    release_inputs: dict[str, Any],
) -> None:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(release_inputs["metadata_path"]),
        "--launcher-artifact",
        str(release_inputs["launcher"]),
        # omitting --updater-artifact
        "--core-artifact",
        str(release_inputs["core"]),
        "--private-key-file",
        str(release_inputs["private_path"]),
        "--key-id",
        KEY_ID,
        "--public-key-file",
        str(release_inputs["public_path"]),
        "--output",
        str(release_inputs["output"]),
    ]
    completed = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert not release_inputs["output"].exists()


@pytest.mark.parametrize("option", ["--private-key", "--private-key-env"])
def test_cli_rejects_inline_and_environment_key_modes_without_echo(
    release_inputs: dict[str, Any], option: str
) -> None:
    sentinel = "SENTINEL_INLINE_PRIVATE_KEY_DO_NOT_ECHO"
    environment = dict(os.environ)
    environment["NEKO_RELEASE_PRIVATE_KEY"] = sentinel
    completed = invoke(release_inputs, option, sentinel, env=environment)
    combined = completed.stdout + completed.stderr

    assert completed.returncode != 0
    assert sentinel not in combined
    assert_no_private_material(combined, release_inputs["private_raw"])
    assert not release_inputs["output"].exists()


def test_cli_failure_is_secret_safe_and_creates_no_output(
    release_inputs: dict[str, Any]
) -> None:
    secret = "SENTINEL_METADATA_SECRET_DO_NOT_ECHO"
    write_metadata(release_inputs, {"unexpected_secret": secret})
    completed = invoke(release_inputs)
    combined = completed.stdout + completed.stderr

    assert completed.returncode != 0
    assert secret not in combined
    assert_no_private_material(combined, release_inputs["private_raw"])
    assert not release_inputs["output"].exists()


def _make_trust_profile_file(
    tmp_path: Path,
    *,
    profile_id: str = "production",
    channel: str = "stable",
    owner: str = "Valeneko-pranmong",
    repository: str = "Neko-Family-Proxy-Updates",
    rel_key_id: str = "neko-update-prod-1",
    auth_key_id: str = "test-auth-key-1",
    auth_priv: Ed25519PrivateKey | None = None,
) -> tuple[Path, bytes, dict[str, bytes]]:
    if auth_priv is None:
        auth_priv = Ed25519PrivateKey.generate()
    auth_pub = auth_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    rel_priv = Ed25519PrivateKey.generate()
    rel_pub = rel_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    payload = {
        "channel": channel,
        "owner": owner,
        "profile_id": profile_id,
        "release_keys": [{"key_id": rel_key_id, "public_key_hex": rel_pub.hex()}],
        "repository": repository,
    }
    from neko_launcher.updater.canonical_json import canonical_json_dumps
    payload_bytes = canonical_json_dumps(payload)
    sig_b64 = base64.b64encode(auth_priv.sign(payload_bytes)).decode("ascii")
    envelope = {
        "key_id": auth_key_id,
        "payload": payload,
        "schema_version": 1,
        "signature_b64": sig_b64,
    }
    raw = canonical_json_dumps(envelope) + b"\n"
    path = tmp_path / f"profile-{profile_id}.json"
    path.write_bytes(raw)
    return path, raw, {auth_key_id: auth_pub}


def test_collect_final_component_set_happy_path(tmp_path: Path):
    from scripts.build_software_release_v2 import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        FinalComponentSet,
        collect_final_component_set,
    )
    from scripts.core_authority_custody import VerifiedCoreAuthority

    launcher_file = tmp_path / "NekoLauncher.exe"
    launcher_file.write_bytes(b"launcher-bytes-456")
    updater_file = tmp_path / "NekoUpdater.exe"
    updater_file.write_bytes(b"updater-bytes-789")
    core_file = tmp_path / "NekoProxyCore.zip"
    core_file.write_bytes(b"core-bytes-012")

    core_identity = ArtifactIdentity(
        artifact_id="NekoProxyCore.zip",
        version="5.1.2",
        sha256=hashlib.sha256(b"core-bytes-012").hexdigest(),
        size=len(b"core-bytes-012"),
        installed_identity_sha256="c" * 64,
        artifact_format="zip-core-v1",
    )
    core_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="e" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    core_authority = VerifiedCoreAuthority(
        binding=core_binding,
        core_zip_path=core_file,
        core=core_identity,
    )

    prof_path, _, auth_keys = _make_trust_profile_file(tmp_path, profile_id="production")

    comp_set = collect_final_component_set(
        source_commit="a" * 40,
        launcher_path=launcher_file,
        launcher_version="5.1.2",
        updater_path=updater_file,
        updater_version="5.1.2",
        core_authority=core_authority,
        trust_profile_path=prof_path,
        profile_authority_public_keys=auth_keys,
    )

    assert isinstance(comp_set, FinalComponentSet)
    assert comp_set.source_commit == "a" * 40
    assert comp_set.launcher.artifact_id == "NekoLauncher.exe"
    assert comp_set.launcher.version == "5.1.2"
    assert comp_set.launcher.sha256 == hashlib.sha256(b"launcher-bytes-456").hexdigest()
    assert comp_set.updater.artifact_id == "NekoUpdater.exe"
    assert comp_set.core.artifact_id == "NekoProxyCore.zip"
    assert comp_set.core_authority == core_binding
    assert comp_set.trust_profile.profile_id == "production"
    assert len(comp_set.component_set_sha256) == 64


def test_collect_final_component_set_rejects_proof_profile(tmp_path: Path):
    from scripts.build_software_release_v2 import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        collect_final_component_set,
    )
    from scripts.core_authority_custody import VerifiedCoreAuthority

    launcher_file = tmp_path / "NekoLauncher.exe"
    launcher_file.write_bytes(b"launcher")
    updater_file = tmp_path / "NekoUpdater.exe"
    updater_file.write_bytes(b"updater")
    core_file = tmp_path / "NekoProxyCore.zip"
    core_file.write_bytes(b"core")

    core_identity = ArtifactIdentity(
        artifact_id="NekoProxyCore.zip",
        version="5.1.2",
        sha256=hashlib.sha256(b"core").hexdigest(),
        size=len(b"core"),
        installed_identity_sha256="c" * 64,
        artifact_format="zip-core-v1",
    )
    core_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="e" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    core_authority = VerifiedCoreAuthority(
        binding=core_binding,
        core_zip_path=core_file,
        core=core_identity,
    )

    prof_path, _, auth_keys = _make_trust_profile_file(tmp_path, profile_id="proof-v512")

    with pytest.raises(ValueError, match="(?i)(production|proof)"):
        collect_final_component_set(
            source_commit="a" * 40,
            launcher_path=launcher_file,
            launcher_version="5.1.2",
            updater_path=updater_file,
            updater_version="5.1.2",
            core_authority=core_authority,
            trust_profile_path=prof_path,
            profile_authority_public_keys=auth_keys,
        )


def test_collect_final_component_set_digest_sensitivity(tmp_path: Path):
    from scripts.build_software_release_v2 import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        collect_final_component_set,
    )
    from scripts.core_authority_custody import VerifiedCoreAuthority

    launcher_file = tmp_path / "NekoLauncher.exe"
    launcher_file.write_bytes(b"launcher")
    updater_file = tmp_path / "NekoUpdater.exe"
    updater_file.write_bytes(b"updater")
    core_file = tmp_path / "NekoProxyCore.zip"
    core_file.write_bytes(b"core")

    core_identity = ArtifactIdentity(
        artifact_id="NekoProxyCore.zip",
        version="5.1.2",
        sha256=hashlib.sha256(b"core").hexdigest(),
        size=len(b"core"),
        installed_identity_sha256="c" * 64,
        artifact_format="zip-core-v1",
    )
    core_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="e" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    core_authority = VerifiedCoreAuthority(
        binding=core_binding,
        core_zip_path=core_file,
        core=core_identity,
    )

    prof_path, _, auth_keys = _make_trust_profile_file(tmp_path, profile_id="production")

    base_set = collect_final_component_set(
        source_commit="a" * 40,
        launcher_path=launcher_file,
        launcher_version="5.1.2",
        updater_path=updater_file,
        updater_version="5.1.2",
        core_authority=core_authority,
        trust_profile_path=prof_path,
        profile_authority_public_keys=auth_keys,
    )

    # Change source_commit
    diff_commit = collect_final_component_set(
        source_commit="b" * 40,
        launcher_path=launcher_file,
        launcher_version="5.1.2",
        updater_path=updater_file,
        updater_version="5.1.2",
        core_authority=core_authority,
        trust_profile_path=prof_path,
        profile_authority_public_keys=auth_keys,
    )
    assert diff_commit.component_set_sha256 != base_set.component_set_sha256

    # Change launcher bytes
    launcher_file2 = tmp_path / "NekoLauncher2.exe"
    launcher_file2.write_bytes(b"launcher-different")
    diff_launcher = collect_final_component_set(
        source_commit="a" * 40,
        launcher_path=launcher_file2,
        launcher_version="5.1.2",
        updater_path=updater_file,
        updater_version="5.1.2",
        core_authority=core_authority,
        trust_profile_path=prof_path,
        profile_authority_public_keys=auth_keys,
    )
    assert diff_launcher.component_set_sha256 != base_set.component_set_sha256


def test_baseline_metadata_uses_reserved_sequence_as_minimum(tmp_path: Path):
    from scripts.build_software_release_v2 import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        FinalComponentSet,
        TrustProfileBinding,
        build_unsigned_baseline,
        compute_component_set_sha256,
    )
    from scripts.derive_version import ReleaseAllocation

    launcher_id = ArtifactIdentity(
        artifact_id="NekoLauncher.exe",
        version="5.1.2",
        sha256="1" * 64,
        size=100,
        installed_identity_sha256="1" * 64,
        artifact_format="raw-pe-v1",
    )
    updater_id = ArtifactIdentity(
        artifact_id="NekoUpdater.exe",
        version="5.1.2",
        sha256="2" * 64,
        size=200,
        installed_identity_sha256="2" * 64,
        artifact_format="raw-pe-v1",
    )
    core_id = ArtifactIdentity(
        artifact_id="NekoProxyCore.zip",
        version="5.1.2",
        sha256="3" * 64,
        size=300,
        installed_identity_sha256="3" * 64,
        artifact_format="zip-core-v1",
    )
    core_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="e" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    trust_binding = TrustProfileBinding(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates",
        profile_authority_key_id="neko-update-profile-v512-1",
        profile_authority_public_key_sha256="a" * 64,
        profile_envelope_sha256="env" * 21 + "e",
        keyset_sha256="k" * 64,
    )
    comp_sha = compute_component_set_sha256(
        source_commit="c" * 40,
        launcher=launcher_id,
        updater=updater_id,
        core=core_id,
        core_authority=core_binding,
        trust_profile=trust_binding,
    )
    component_set = FinalComponentSet(
        source_commit="c" * 40,
        launcher=launcher_id,
        updater=updater_id,
        core=core_id,
        core_authority=core_binding,
        trust_profile=trust_binding,
        component_set_sha256=comp_sha,
    )

    allocation = ReleaseAllocation(
        sequence=8,
        release_id="stable-0008",
        ledger_entry_sha256="led" * 21 + "l",
        component_set_sha256=comp_sha,
        authenticated_bindings_sha256="b" * 64,
        history_snapshot_sha256="h" * 64,
    )

    unsigned = build_unsigned_baseline(
        allocation=allocation,
        component_set=component_set,
    )

    assert unsigned.sequence == 8
    assert unsigned.release_id == "stable-0008"
    assert unsigned.component_set_sha256 == comp_sha
    assert unsigned.payload_path.is_file()

    doc = json.loads(unsigned.payload_path.read_text(encoding="utf-8"))
    assert doc["release_sequence"] == 8
    assert doc["release_id"] == "stable-0008"
    assert doc["minimum_supported_sequence"] == 8
    assert doc["mandatory"] is False
    assert doc["channel"] == "stable"
    assert doc["components"]["core"]["artifact_id"] == "NekoProxyCore.zip"
    assert doc["components"]["launcher"]["artifact_id"] == "NekoLauncher.exe"
    assert doc["components"]["updater"]["artifact_id"] == "NekoUpdater.exe"


def test_build_unsigned_baseline_rejects_tampered_component_set():
    from scripts.build_software_release_v2 import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        FinalComponentSet,
        TrustProfileBinding,
        build_unsigned_baseline,
    )
    from scripts.derive_version import ReleaseAllocation

    launcher_id = ArtifactIdentity(
        artifact_id="NekoLauncher.exe",
        version="5.1.2",
        sha256="1" * 64,
        size=100,
        installed_identity_sha256="1" * 64,
        artifact_format="raw-pe-v1",
    )
    updater_id = ArtifactIdentity(
        artifact_id="NekoUpdater.exe",
        version="5.1.2",
        sha256="2" * 64,
        size=200,
        installed_identity_sha256="2" * 64,
        artifact_format="raw-pe-v1",
    )
    core_id = ArtifactIdentity(
        artifact_id="NekoProxyCore.zip",
        version="5.1.2",
        sha256="3" * 64,
        size=300,
        installed_identity_sha256="3" * 64,
        artifact_format="zip-core-v1",
    )
    core_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="p" * 64,
        authority_envelope_sha256="e" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="pr" * 32,
    )
    trust_binding = TrustProfileBinding(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy-Updates",
        profile_authority_key_id="neko-update-profile-v512-1",
        profile_authority_public_key_sha256="a" * 64,
        profile_envelope_sha256="env" * 21 + "e",
        keyset_sha256="k" * 64,
    )
    tampered_set = FinalComponentSet(
        source_commit="c" * 40,
        launcher=launcher_id,
        updater=updater_id,
        core=core_id,
        core_authority=core_binding,
        trust_profile=trust_binding,
        component_set_sha256="bad" * 21 + "b",
    )

    allocation = ReleaseAllocation(
        sequence=8,
        release_id="stable-0008",
        ledger_entry_sha256="led" * 21 + "l",
        component_set_sha256="bad" * 21 + "b",
        authenticated_bindings_sha256="b" * 64,
        history_snapshot_sha256="h" * 64,
    )

    with pytest.raises(ValueError, match="(?i)(digest|component_set|mismatch|tamper)"):
        build_unsigned_baseline(allocation=allocation, component_set=tampered_set)


def test_build_unsigned_successor_can_preserve_published_compatibility_floor():
    from scripts.build_software_release_v2 import (
        ArtifactIdentity,
        CoreAuthorityBinding,
        FinalComponentSet,
        TrustProfileBinding,
        build_unsigned_baseline,
        compute_component_set_sha256,
    )
    from scripts.derive_version import ReleaseAllocation

    launcher = ArtifactIdentity("NekoLauncher.exe", "5.1.3", "1" * 64, 101, "1" * 64, "raw-pe-v1")
    updater = ArtifactIdentity("NekoUpdater.exe", "5.1.3", "2" * 64, 202, "2" * 64, "raw-pe-v1")
    core = ArtifactIdentity("NekoProxyCore.zip", "5.1.3", "3" * 64, 303, "4" * 64, "zip-core-v1")
    core_binding = CoreAuthorityBinding(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="5" * 64,
        authority_envelope_sha256="6" * 64,
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
        provenance_sha256="7" * 64,
    )
    trust = TrustProfileBinding(
        profile_id="production",
        channel="stable",
        owner="Valeneko-pranmong",
        repository="Neko-Family-Proxy",
        profile_authority_key_id="neko-update-profile-v512-1",
        profile_authority_public_key_sha256="8" * 64,
        profile_envelope_sha256="9" * 64,
        keyset_sha256="a" * 64,
    )
    digest = compute_component_set_sha256(
        source_commit="b" * 40,
        launcher=launcher,
        updater=updater,
        core=core,
        core_authority=core_binding,
        trust_profile=trust,
    )
    component_set = FinalComponentSet(
        source_commit="b" * 40,
        launcher=launcher,
        updater=updater,
        core=core,
        core_authority=core_binding,
        trust_profile=trust,
        component_set_sha256=digest,
    )
    allocation = ReleaseAllocation(
        sequence=10,
        release_id="stable-0010",
        ledger_entry_sha256="c" * 64,
        component_set_sha256=digest,
        authenticated_bindings_sha256="d" * 64,
        history_snapshot_sha256="e" * 64,
    )

    unsigned = build_unsigned_baseline(
        allocation=allocation,
        component_set=component_set,
        minimum_supported_sequence=9,
    )
    doc = json.loads(unsigned.payload_path.read_text(encoding="utf-8"))
    assert doc["release_sequence"] == 10
    assert doc["minimum_supported_sequence"] == 9
    assert doc["mandatory"] is False


@pytest.mark.parametrize("minimum_supported_sequence", [0, 11])
def test_build_unsigned_rejects_invalid_compatibility_floor(minimum_supported_sequence: int):
    from scripts.build_software_release_v2 import build_unsigned_baseline

    class Allocation:
        sequence = 10
        release_id = "stable-0010"

    with pytest.raises(ValueError, match="minimum_supported_sequence"):
        build_unsigned_baseline(
            allocation=Allocation(),
            component_set=None,  # validation of the explicit floor must fail first
            minimum_supported_sequence=minimum_supported_sequence,
        )
