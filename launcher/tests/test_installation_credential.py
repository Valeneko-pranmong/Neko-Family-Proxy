from __future__ import annotations

import base64
import hashlib
import hmac
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from neko_launcher.infrastructure.installation_credential import (
    InstallationCredentialProvider,
    WindowsDpapiInstallationCredentialProvider,
)


class FakeMachineProtector:
    """Deterministic machine boundary for provider contract tests."""

    def __init__(self, machine_name: str) -> None:
        self._key = hashlib.sha256(machine_name.encode("ascii")).digest()

    def protect(self, plaintext: bytes) -> bytes:
        ciphertext = bytes(
            value ^ self._key[index % len(self._key)]
            for index, value in enumerate(plaintext)
        )
        return hmac.digest(self._key, ciphertext, "sha256") + ciphertext

    def unprotect(self, protected: bytes) -> bytes:
        if len(protected) < 32:
            raise ValueError("invalid protected state")
        tag, ciphertext = protected[:32], protected[32:]
        if not hmac.compare_digest(tag, hmac.digest(self._key, ciphertext, "sha256")):
            raise ValueError("different machine")
        return bytes(
            value ^ self._key[index % len(self._key)]
            for index, value in enumerate(ciphertext)
        )


def _provider(
    root: Path,
    machine_state: Path,
    *,
    machine_name: str = "machine-a",
    credential_id: str = "11111111-1111-4111-8111-111111111111",
) -> WindowsDpapiInstallationCredentialProvider:
    root.mkdir(parents=True, exist_ok=True)
    return WindowsDpapiInstallationCredentialProvider(
        install_root=root,
        machine_state_root=machine_state,
        protector=FakeMachineProtector(machine_name),
        private_key_factory=lambda: b"k" * 32,
        credential_id_factory=lambda: credential_id,
    )


def test_provider_provisions_loads_and_proves_without_exporting_private_material(
    tmp_path: Path,
) -> None:
    provider = _provider(tmp_path / "install", tmp_path / "machine-state")

    identity = provider.provision()
    loaded = provider.load_public_identity()
    proof = provider.prove(b"server-challenge")

    assert isinstance(provider, InstallationCredentialProvider)
    assert loaded == identity
    assert identity.algorithm == "ed25519"
    assert identity.key_hash == hashlib.sha256(
        base64.urlsafe_b64decode(identity.public_key_b64 + "=")
    ).hexdigest()
    Ed25519PublicKey.from_public_bytes(
        base64.urlsafe_b64decode(identity.public_key_b64 + "=")
    ).verify(
        base64.urlsafe_b64decode(proof.signature_b64 + "=="),
        b"server-challenge",
    )
    assert set(InstallationCredentialProvider.__dict__) >= {
        "provision",
        "load_public_identity",
        "prove",
    }
    assert not any(
        name in InstallationCredentialProvider.__dict__
        for name in ("export", "export_private_key", "read_secret", "protected_blob")
    )


def test_copied_public_and_protected_state_cannot_prove_on_second_machine(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_state = tmp_path / "source-state"
    source = _provider(source_root, source_state)
    identity = source.provision()

    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    destination_state = tmp_path / "destination-state"
    destination_state.mkdir()
    (destination_root / "state").mkdir()
    (destination_root / "state" / "installation-credential.json").write_bytes(
        (source_root / "state" / "installation-credential.json").read_bytes()
    )
    (destination_state / "installation-credential.bin").write_bytes(
        (source_state / "installation-credential.bin").read_bytes()
    )
    destination = _provider(
        destination_root,
        destination_state,
        machine_name="machine-b",
    )

    with pytest.raises(Exception, match="credential|machine|state|invalid|missing"):
        destination.prove(b"server-challenge")
    assert identity.key_hash != ""


def test_missing_or_corrupt_protected_state_fails_closed(tmp_path: Path) -> None:
    provider = _provider(tmp_path / "install", tmp_path / "machine-state")
    provider.provision()
    protected = tmp_path / "machine-state" / "installation-credential.bin"
    protected.write_bytes(b"corrupt")

    with pytest.raises(Exception, match="credential|machine|state|invalid"):
        provider.load_public_identity()


def test_reinstall_after_state_removal_provisions_a_new_identity(tmp_path: Path) -> None:
    root = tmp_path / "install"
    machine_state = tmp_path / "machine-state"
    first = _provider(root, machine_state, credential_id="first")
    first_identity = first.provision()

    (root / "state" / "installation-credential.json").unlink()
    (machine_state / "installation-credential.bin").unlink()
    second = _provider(root, machine_state, credential_id="second")
    second_identity = second.provision()

    assert second_identity.credential_id == "second"
    assert second_identity.credential_id != first_identity.credential_id
