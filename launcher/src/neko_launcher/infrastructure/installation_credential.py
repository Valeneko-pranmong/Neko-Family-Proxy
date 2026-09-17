"""Installer-provisioned, machine-bound installation credentials.

Only the public identity and a hash of its public key are persisted in the
installed tree.  The signing seed is kept behind a machine-scoped protector
and is never returned by the application-level interface.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class InstallationCredentialError(RuntimeError):
    """Base class for fail-closed installation credential errors."""


class InstallationBindingRequired(InstallationCredentialError):
    """The process was not provisioned by the Installer."""


class InstallationBindingInvalid(InstallationCredentialError):
    """Persisted installation identity cannot be validated on this machine."""


class InstallationCredentialUnavailable(InstallationCredentialError):
    """The operating system credential facility is unavailable."""


@dataclass(frozen=True)
class InstallationPublicIdentity:
    """Public material safe to send to the authorization service."""

    credential_id: str
    algorithm: str
    public_key_b64: str
    key_hash: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported installation identity schema")
        if not self.credential_id or len(self.credential_id) > 128:
            raise ValueError("invalid installation credential id")
        if self.algorithm != "ed25519":
            raise ValueError("unsupported installation credential algorithm")
        public_key = _decode_b64(self.public_key_b64)
        if len(public_key) != 32:
            raise ValueError("invalid installation public key")
        expected_hash = hashlib.sha256(public_key).hexdigest()
        if not hmac.compare_digest(self.key_hash, expected_hash):
            raise ValueError("installation public key hash mismatch")
        if len(self.key_hash) != 64 or any(c not in "0123456789abcdef" for c in self.key_hash):
            raise ValueError("invalid installation key hash")

    @property
    def public_key_bytes(self) -> bytes:
        """Return public bytes; no private material is represented by this type."""
        return _decode_b64(self.public_key_b64)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "credential_id": self.credential_id,
            "algorithm": self.algorithm,
            "public_key_b64": self.public_key_b64,
            "key_hash": self.key_hash,
        }

    @classmethod
    def from_public_dict(cls, value: object) -> "InstallationPublicIdentity":
        if not isinstance(value, dict):
            raise ValueError("installation identity must be an object")
        allowed = {"schema_version", "credential_id", "algorithm", "public_key_b64", "key_hash"}
        if set(value) != allowed:
            raise ValueError("installation identity fields are invalid")
        return cls(
            schema_version=value["schema_version"] if type(value["schema_version"]) is int else -1,
            credential_id=value["credential_id"] if isinstance(value["credential_id"], str) else "",
            algorithm=value["algorithm"] if isinstance(value["algorithm"], str) else "",
            public_key_b64=value["public_key_b64"] if isinstance(value["public_key_b64"], str) else "",
            key_hash=value["key_hash"] if isinstance(value["key_hash"], str) else "",
        )


@dataclass(frozen=True)
class InstallationProof:
    """A detached signature over one server/Core challenge."""

    credential_id: str
    key_hash: str
    algorithm: str
    signature_b64: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.algorithm != "ed25519":
            raise ValueError("unsupported installation proof")
        if not self.credential_id or len(self.key_hash) != 64:
            raise ValueError("invalid installation proof identity")
        if len(_decode_b64(self.signature_b64)) != 64:
            raise ValueError("invalid installation proof signature")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "credential_id": self.credential_id,
            "key_hash": self.key_hash,
            "algorithm": self.algorithm,
            "signature_b64": self.signature_b64,
        }


@runtime_checkable
class InstallationCredentialProvider(Protocol):
    """Non-exporting application boundary for machine-bound credentials."""

    def provision(self) -> InstallationPublicIdentity:
        ...

    def load_public_identity(self) -> InstallationPublicIdentity:
        ...

    def prove(self, challenge: bytes) -> InstallationProof:
        ...


class MachineSecretProtector(Protocol):
    """OS-backed protector used by the concrete provider."""

    def protect(self, plaintext: bytes) -> bytes:
        ...

    def unprotect(self, protected: bytes) -> bytes:
        ...


class _DpapiMachineProtector:
    """Windows DPAPI machine-scope fallback.

    CNG key handles are not exposed by the pinned Python runtime.  DPAPI with
    CRYPTPROTECT_LOCAL_MACHINE keeps the generated Ed25519 seed unusable when
    an installed directory is copied to another Windows machine.
    """

    _LOCAL_MACHINE = 0x4

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise InstallationCredentialUnavailable("Windows machine protection is unavailable")
        try:
            self._crypt32 = ctypes.windll.crypt32
            self._kernel32 = ctypes.windll.kernel32
        except AttributeError as exc:
            raise InstallationCredentialUnavailable("Windows machine protection is unavailable") from exc

    def protect(self, plaintext: bytes) -> bytes:
        return self._call("CryptProtectData", plaintext, self._LOCAL_MACHINE)

    def unprotect(self, protected: bytes) -> bytes:
        return self._call("CryptUnprotectData", protected, 0)

    def _call(self, name: str, data: bytes, flags: int) -> bytes:
        source = ctypes.create_string_buffer(data)
        input_blob = self._Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
        output_blob = self._Blob()
        function = getattr(self._crypt32, name)
        function.argtypes = [
            ctypes.POINTER(self._Blob),
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(self._Blob),
        ]
        function.restype = wintypes.BOOL
        ok = function(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
        if not ok or not output_blob.pbData:
            raise InstallationBindingInvalid("machine-protected installation state is unavailable")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(output_blob.pbData)


class WindowsDpapiInstallationCredentialProvider:
    """Ed25519 identity whose private seed is protected by Windows DPAPI.

    ``protector`` and the factories are injectable solely for deterministic
    tests.  Production construction uses DPAPI machine scope and random IDs.
    """

    _PUBLIC_STATE_NAME = "installation-credential.json"
    _PROTECTED_STATE_NAME = "installation-credential.bin"
    _PROTECTED_MAGIC = b"NEKOIC1\x00"

    def __init__(
        self,
        install_root: Path,
        *,
        machine_state_root: Path | None = None,
        protector: MachineSecretProtector | None = None,
        private_key_factory: Callable[[], bytes] | None = None,
        credential_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._install_root = Path(install_root)
        self._public_state_path = self._install_root / "state" / self._PUBLIC_STATE_NAME
        self._machine_state_root = Path(machine_state_root) if machine_state_root else self._install_root / "state"
        self._protected_state_path = self._machine_state_root / self._PROTECTED_STATE_NAME
        self._protector = protector if protector is not None else _DpapiMachineProtector()
        self._private_key_factory = private_key_factory or (lambda: secrets.token_bytes(32))
        self._credential_id_factory = credential_id_factory or (lambda: str(uuid4()))

    def provision(self) -> InstallationPublicIdentity:
        """Create the identity once; repeated Installer runs are idempotent."""
        if self._public_state_path.exists() or self._protected_state_path.exists():
            return self.load_public_identity()
        if not self._install_root.is_dir():
            raise InstallationBindingRequired("installation root is not present")

        seed = self._private_key_factory()
        if not isinstance(seed, bytes) or len(seed) != 32:
            raise InstallationCredentialError("installation key generation failed")
        private_key = Ed25519PrivateKey.from_private_bytes(seed)
        public_key = private_key.public_key().public_bytes_raw()
        identity = InstallationPublicIdentity(
            credential_id=str(self._credential_id_factory()),
            algorithm="ed25519",
            public_key_b64=_encode_b64(public_key),
            key_hash=hashlib.sha256(public_key).hexdigest(),
        )
        protected_payload = _canonical_json(
            {
                "identity": identity.to_public_dict(),
                "private_seed_b64": _encode_b64(seed),
            }
        )
        protected = self._PROTECTED_MAGIC + self._protector.protect(protected_payload)
        self._atomic_write(self._protected_state_path, protected)
        try:
            self._atomic_write(
                self._public_state_path,
                _canonical_json(identity.to_public_dict()) + b"\n",
            )
        except Exception:
            try:
                self._protected_state_path.unlink()
            except OSError:
                pass
            raise
        return identity

    def load_public_identity(self) -> InstallationPublicIdentity:
        """Validate both public metadata and machine-bound private state."""
        if not self._public_state_path.is_file():
            raise InstallationBindingRequired("Installer-provisioned installation identity is missing")
        if not self._protected_state_path.is_file():
            raise InstallationBindingRequired("Installer-provisioned machine credential is missing")
        try:
            raw = json.loads(self._public_state_path.read_bytes().decode("utf-8"))
            identity = InstallationPublicIdentity.from_public_dict(raw)
            loaded_identity, _ = self._load_private_material()
        except InstallationCredentialError:
            raise
        except Exception as exc:
            raise InstallationBindingInvalid("installation credential state is corrupt") from exc
        if loaded_identity != identity:
            raise InstallationBindingInvalid("installation credential identity does not match")
        return identity

    def prove(self, challenge: bytes) -> InstallationProof:
        """Sign a bounded challenge without exposing the private seed."""
        if not isinstance(challenge, bytes) or not 1 <= len(challenge) <= 4096:
            raise ValueError("installation challenge must be non-empty bytes")
        identity = self.load_public_identity()
        loaded_identity, seed = self._load_private_material()
        if loaded_identity != identity:
            raise InstallationBindingInvalid("installation credential identity does not match")
        signature = Ed25519PrivateKey.from_private_bytes(seed).sign(challenge)
        return InstallationProof(
            credential_id=identity.credential_id,
            key_hash=identity.key_hash,
            algorithm=identity.algorithm,
            signature_b64=_encode_b64(signature),
        )

    def _load_private_material(self) -> tuple[InstallationPublicIdentity, bytes]:
        try:
            protected = self._protected_state_path.read_bytes()
            if not protected.startswith(self._PROTECTED_MAGIC):
                raise ValueError("invalid protected state")
            payload = self._protector.unprotect(protected[len(self._PROTECTED_MAGIC) :])
            document = json.loads(payload.decode("utf-8"))
            if not isinstance(document, dict) or set(document) != {"identity", "private_seed_b64"}:
                raise ValueError("invalid protected state")
            identity = InstallationPublicIdentity.from_public_dict(document["identity"])
            seed = _decode_b64(document["private_seed_b64"])
            if len(seed) != 32:
                raise ValueError("invalid protected key material")
            derived = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()
            if not hmac.compare_digest(identity.public_key_b64, _encode_b64(derived)):
                raise ValueError("protected key does not match identity")
            return identity, seed
        except InstallationCredentialError:
            raise
        except Exception as exc:
            raise InstallationBindingInvalid("machine-protected installation state is invalid") from exc

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass


def create_installation_credential_provider(install_root: Path) -> WindowsDpapiInstallationCredentialProvider:
    """Construct the production provider without provisioning it."""
    return WindowsDpapiInstallationCredentialProvider(install_root)


def _encode_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_b64(value: str) -> bytes:
    if not isinstance(value, str) or not value or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in value):
        raise ValueError("invalid base64url value")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
