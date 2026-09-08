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
