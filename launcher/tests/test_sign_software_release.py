from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

import tests

_launcher_tests = str(Path(__file__).resolve().parent)
if _launcher_tests not in tests.__path__:
    tests.__path__.append(_launcher_tests)

from neko_launcher.infrastructure.software_update_manifest import (  # noqa: E402
    ReleaseManifestVerifier,
)
from tests.software_update_helpers import (  # noqa: E402
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    canonical_payload_bytes,
    valid_release_document,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sign_software_release.py"
LAUNCHER_SRC = REPO_ROOT / "launcher" / "src"
TEST_PRIVATE_SEED = b"test-only-deterministic-key-0000"


def invoke(
    tmp_path: Path,
    *extra_args: str,
    document: object | None = None,
    key_bytes: bytes = TEST_PRIVATE_SEED,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    input_path = tmp_path / "release.json"
    key_path = tmp_path / "test-private-key.bin"
    output_path = tmp_path / "envelope.json"
    input_path.write_text(
        json.dumps(
            valid_release_document() if document is None else document,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    key_path.write_bytes(key_bytes)

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(LAUNCHER_SRC)
    environment.pop("TCL_LIBRARY", None)
    environment.pop("TK_LIBRARY", None)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_path),
            "--private-key-file",
            str(key_path),
            "--key-id",
            TEST_KEY_ID,
            "--output",
            str(output_path),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, output_path


def private_markers() -> tuple[str, ...]:
    return (
        TEST_PRIVATE_SEED.hex(),
        base64.b64encode(TEST_PRIVATE_SEED).decode("ascii"),
        TEST_PRIVATE_SEED.decode("ascii"),
    )


def assert_private_markers_absent(
    completed: subprocess.CompletedProcess[str],
) -> None:
    combined = completed.stdout + completed.stderr
    for marker in private_markers():
        assert marker not in combined


def test_raw_private_key_signs_exact_canonical_payload_and_round_trips(
    tmp_path: Path,
) -> None:
    completed, output_path = invoke(tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert_private_markers_absent(completed)
    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(envelope) == {
        "envelope_version",
        "key_id",
        "payload_b64",
        "signature_b64",
    }
    assert envelope["envelope_version"] == 1
    assert envelope["key_id"] == TEST_KEY_ID
    assert base64.b64decode(envelope["payload_b64"], validate=True) == (
        canonical_payload_bytes(valid_release_document())
    )
    release = ReleaseManifestVerifier({TEST_KEY_ID: TEST_PUBLIC_KEY}).verify(
        envelope
    )
    assert release.release_id == "r2-beta-01"
    assert release.release_sequence == 2
    assert "r2-beta-01" in completed.stdout
    assert "sequence=2" in completed.stdout
    assert completed.stderr == ""


def test_pem_ed25519_private_key_is_accepted(tmp_path: Path) -> None:
    pem = Ed25519PrivateKey.from_private_bytes(TEST_PRIVATE_SEED).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    completed, output_path = invoke(tmp_path, key_bytes=pem)

    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    signature = base64.b64decode(envelope["signature_b64"], validate=True)
    Ed25519PublicKey.from_public_bytes(TEST_PUBLIC_KEY).verify(
        signature,
        canonical_payload_bytes(valid_release_document()),
    )
    assert_private_markers_absent(completed)


def test_invalid_release_input_fails_without_output_or_payload_leak(
    tmp_path: Path,
) -> None:
    sentinel = "SENTINEL_INVALID_RELEASE_SECRET_42"
    completed, output_path = invoke(
        tmp_path,
        document={"credential": sentinel},
    )

    assert completed.returncode != 0
    assert not output_path.exists()
    assert sentinel not in completed.stdout
    assert sentinel not in completed.stderr
    assert_private_markers_absent(completed)


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    output_path = tmp_path / "envelope.json"
    original = b"immutable-existing-output"
    output_path.write_bytes(original)

    completed, returned_output_path = invoke(tmp_path)

    assert returned_output_path == output_path
    assert completed.returncode != 0
    assert output_path.read_bytes() == original
    assert_private_markers_absent(completed)


def test_inline_private_key_argument_is_rejected_without_echoing_value(
    tmp_path: Path,
) -> None:
    sentinel = "SENTINEL_INLINE_PRIVATE_KEY_42"
    completed, output_path = invoke(
        tmp_path,
        "--private-key",
        sentinel,
    )

    assert completed.returncode != 0
    assert not output_path.exists()
    assert sentinel not in completed.stdout
    assert sentinel not in completed.stderr
    assert_private_markers_absent(completed)


@pytest.mark.parametrize("key_bytes", [b"short", b"x" * 33])
def test_invalid_raw_private_key_length_fails_safely(
    tmp_path: Path,
    key_bytes: bytes,
) -> None:
    completed, output_path = invoke(tmp_path, key_bytes=key_bytes)

    assert completed.returncode != 0
    assert not output_path.exists()
    assert key_bytes.hex() not in completed.stdout + completed.stderr
    assert_private_markers_absent(completed)


def test_signing_helper_error_reporting_never_dumps_traceback_or_environment_keys(
    tmp_path: Path,
) -> None:
    bad_input = tmp_path / "bad.json"
    bad_input.write_text("{not-valid-json", encoding="utf-8")
    key_path = tmp_path / "key.bin"
    key_path.write_bytes(TEST_PRIVATE_SEED)
    out_path = tmp_path / "out.json"

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(LAUNCHER_SRC)
    environment["SECRET_TOKEN_SENTINEL"] = "SUPER_SECRET_VALUE_12345"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(bad_input),
            "--private-key-file",
            str(key_path),
            "--key-id",
            TEST_KEY_ID,
            "--output",
            str(out_path),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "Traceback" not in completed.stderr
    assert "KEYS:" not in completed.stderr
    assert "SECRET_TOKEN_SENTINEL" not in completed.stderr
    assert "SUPER_SECRET_VALUE_12345" not in completed.stderr
    assert "software release signing failed" in completed.stderr


def test_private_key_release_signer_adapter_semantics(tmp_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from sign_software_release import (
        DetachedReleaseSignature,
        PrivateKeyReleaseSigner,
        ReleaseSigner,
    )

    key_path = tmp_path / "signer-key.bin"
    key_path.write_bytes(TEST_PRIVATE_SEED)

    signer = PrivateKeyReleaseSigner(key_path, TEST_KEY_ID)
    assert isinstance(signer, ReleaseSigner)
    assert repr(signer) == f"PrivateKeyReleaseSigner(key_id='{TEST_KEY_ID}')"

    payload = b'{"hello":"world"}'
    sig = signer.sign(payload)
    assert isinstance(sig, DetachedReleaseSignature)
    assert sig.key_id == TEST_KEY_ID
    assert len(sig.signature) == 64

    Ed25519PublicKey.from_public_bytes(TEST_PUBLIC_KEY).verify(
        sig.signature,
        payload,
    )

    # Rejection of forbidden key name
    with pytest.raises(ValueError, match="runtime-settings.key is forbidden"):
        PrivateKeyReleaseSigner("C:/keys/runtime-settings.key", TEST_KEY_ID)

    # Rejection of invalid key_id
    with pytest.raises(ValueError, match="KEY_ID_INVALID"):
        PrivateKeyReleaseSigner(key_path, "invalid key id with spaces!")
