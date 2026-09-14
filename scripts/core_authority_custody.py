from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads
from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS
from neko_launcher.updater.zip_extractor import extract_core_bundle


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_id: str
    version: str
    sha256: str
    size: int
    installed_identity_sha256: str
    artifact_format: str


@dataclass(frozen=True)
class CoreAuthorityBinding:
    authority_version_tag: str
    authority_release_sequence: int
    authority_release_id: str
    authority_payload_sha256: str
    authority_envelope_sha256: str
    authority_key_id: str
    core_source_commit: str
    provenance_sha256: str


@dataclass(frozen=True)
class VerifiedCoreAuthority:
    binding: CoreAuthorityBinding
    core_zip_path: Path
    core: ArtifactIdentity


def compute_core_provenance_sha256(
    *,
    authority_version_tag: str,
    authority_release_sequence: int,
    authority_release_id: str,
    authority_payload_sha256: str,
    authority_envelope_sha256: str,
    authority_key_id: str,
    core_source_commit: str,
) -> str:
    payload = {
        "authority_envelope_sha256": authority_envelope_sha256,
        "authority_key_id": authority_key_id,
        "authority_payload_sha256": authority_payload_sha256,
        "authority_release_id": authority_release_id,
        "authority_release_sequence": authority_release_sequence,
        "authority_version_tag": authority_version_tag,
        "core_source_commit": core_source_commit,
    }
    return hashlib.sha256(canonical_json_dumps(payload)).hexdigest()


CANONICAL_V512_CORE_AUTHORITY_EXPECTED = CoreAuthorityBinding(
    authority_version_tag="v5.1.2",
    authority_release_sequence=6,
    authority_release_id="stable-0006",
    authority_payload_sha256="1ae606758302f485c8f31f324eafedeb9c182f8f0f9ab0b7bdd82bc4eab94c9f",
    authority_envelope_sha256="989b0469baaa819ff619b5a83a59df5a0cd5669a80d43285f2d36bd9bb392b38",
    authority_key_id="neko-update-prod-1",
    core_source_commit="6ab94bb",
    provenance_sha256=compute_core_provenance_sha256(
        authority_version_tag="v5.1.2",
        authority_release_sequence=6,
        authority_release_id="stable-0006",
        authority_payload_sha256="1ae606758302f485c8f31f324eafedeb9c182f8f0f9ab0b7bdd82bc4eab94c9f",
        authority_envelope_sha256="989b0469baaa819ff619b5a83a59df5a0cd5669a80d43285f2d36bd9bb392b38",
        authority_key_id="neko-update-prod-1",
        core_source_commit="6ab94bb",
    ),
)

_CORE_AUTHORITY_INDEX_KEYS = frozenset({
    "schema_version",
    "authority_version_tag",
    "authority_release_sequence",
    "authority_release_id",
    "authority_payload_sha256",
    "authority_envelope_sha256",
    "authority_key_id",
    "core_source_commit",
    "provenance_sha256",
})


def _get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower()


def _atomic_write_file(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_file = target.parent / f".tmp_{target.name}_{os.getpid()}_{int(hashlib.sha256(data).hexdigest()[:8], 16)}"
    try:
        with temp_file.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_file, target)
    except BaseException:
        if temp_file.is_file():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise


def load_verified_core_authority(
    custody_root: Path,
    trusted_public_keys: Mapping[str, bytes] | None = None,
) -> VerifiedCoreAuthority:
    custody_root = Path(custody_root)
    if ".." in custody_root.parts:
        raise ValueError(f"Custody path violates confinement: {custody_root}")
    if not custody_root.is_dir():
        raise FileNotFoundError(f"Custody root not found: {custody_root}")

    if trusted_public_keys is None:
        trusted_public_keys = PRODUCTION_RELEASE_PUBLIC_KEYS

    index_file = custody_root / "core-authority-v1.json"
    if not index_file.is_file():
        raise FileNotFoundError(f"core-authority-v1.json missing in {custody_root}")

    raw_index = index_file.read_bytes()
    if not raw_index.endswith(b"\n") or raw_index.endswith(b"\r\n") or raw_index.endswith(b"\n\n"):
        raise ValueError("core-authority-v1.json must end with single LF without CRLF")
    if raw_index.startswith(b"\xef\xbb\xbf"):
        raise ValueError("core-authority-v1.json must not have UTF-8 BOM")

    body = raw_index[:-1]
    if body != body.strip(b" \t\r\n"):
        raise ValueError("core-authority-v1.json is non-canonical: contains leading/trailing whitespace")

    try:
        index_doc = canonical_json_loads(body)
    except Exception as err:
        raise ValueError(f"core-authority-v1.json is not canonical JSON: {err}") from err

    if canonical_json_dumps(index_doc) != body:
        raise ValueError("core-authority-v1.json is non-canonical JSON")

    if not isinstance(index_doc, dict) or set(index_doc.keys()) != _CORE_AUTHORITY_INDEX_KEYS:
        raise ValueError("core-authority-v1.json violates closed schema")

    if index_doc["schema_version"] != 1:
        raise ValueError(f"Unsupported schema_version: {index_doc['schema_version']}")

    tag = index_doc["authority_version_tag"]
    seq = index_doc["authority_release_sequence"]
    rel_id = index_doc["authority_release_id"]
    pay_sha = index_doc["authority_payload_sha256"]
    env_sha = index_doc["authority_envelope_sha256"]
    key_id = index_doc["authority_key_id"]
    core_commit = index_doc["core_source_commit"]
    prov_sha = index_doc["provenance_sha256"]

    expected_prov = compute_core_provenance_sha256(
        authority_version_tag=tag,
        authority_release_sequence=seq,
        authority_release_id=rel_id,
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit=core_commit,
    )
    if prov_sha != expected_prov:
        raise ValueError(f"provenance_sha256 mismatch: expected {expected_prov}, got {prov_sha}")

    binding = CoreAuthorityBinding(
        authority_version_tag=tag,
        authority_release_sequence=seq,
        authority_release_id=rel_id,
        authority_payload_sha256=pay_sha,
        authority_envelope_sha256=env_sha,
        authority_key_id=key_id,
        core_source_commit=core_commit,
        provenance_sha256=prov_sha,
    )

    envelope_file = custody_root / "release-v2.json"
    if not envelope_file.is_file():
        raise FileNotFoundError(f"release-v2.json missing in custody {custody_root}")

    raw_envelope = envelope_file.read_bytes()
    actual_env_sha = hashlib.sha256(raw_envelope).hexdigest()
    if actual_env_sha != binding.authority_envelope_sha256:
        raise ValueError(f"Envelope SHA mismatch: expected {binding.authority_envelope_sha256}, got {actual_env_sha}")

    try:
        envelope_doc = canonical_json_loads(raw_envelope)
    except Exception as err:
        raise ValueError(f"Envelope JSON parse error: {err}") from err

    release_set, verified_payload_sha = verify_release_envelope_v2(envelope_doc, trusted_public_keys)

    if envelope_doc.get("key_id") != binding.authority_key_id:
        raise ValueError(f"Envelope key_id mismatch: {envelope_doc.get('key_id')} vs {binding.authority_key_id}")

    if verified_payload_sha != binding.authority_payload_sha256:
        raise ValueError(f"Payload SHA mismatch: expected {binding.authority_payload_sha256}, got {verified_payload_sha}")

    if release_set.release_sequence != binding.authority_release_sequence:
        raise ValueError(f"Release sequence mismatch: expected {binding.authority_release_sequence}, got {release_set.release_sequence}")

    if release_set.release_id != binding.authority_release_id:
        raise ValueError(f"Release id mismatch: expected {binding.authority_release_id}, got {release_set.release_id}")

    if release_set.channel != "stable":
        raise ValueError(f"Release channel must be 'stable', got {release_set.channel}")

    if "core" not in release_set.components:
        raise ValueError("Core component missing from release envelope")

    core_comp = release_set.components["core"]
    if core_comp.artifact_id != "NekoProxyCore.zip":
        raise ValueError(f"Invalid core artifact_id: {core_comp.artifact_id}")

    expected_version = binding.authority_version_tag.lstrip("v")
    if core_comp.version != expected_version:
        raise ValueError(f"Core component version mismatch: expected {expected_version}, got {core_comp.version}")

    core_zip_file = custody_root / "NekoProxyCore.zip"
    if not core_zip_file.is_file():
        raise FileNotFoundError(f"NekoProxyCore.zip missing in custody {custody_root}")

    actual_zip_size = core_zip_file.stat().st_size
    actual_zip_sha = _get_sha256(core_zip_file)
    if actual_zip_size != core_comp.artifact_size or actual_zip_sha != core_comp.artifact_sha256.lower():
        raise ValueError(
            f"Core zip sha/size mismatch: expected {core_comp.artifact_sha256}/{core_comp.artifact_size}, "
            f"got {actual_zip_sha}/{actual_zip_size}"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        extract_core_bundle(core_zip_file, tmp_path)
        verification = verify_canonical_core_bundle(tmp_path)
        if not verification.valid:
            raise ValueError(f"Core bundle verification failed: {verification.error}")
        if verification.manifest_sha256 != core_comp.installed_identity_sha256.lower():
            raise ValueError(
                f"Core bundle installed identity mismatch: expected {core_comp.installed_identity_sha256}, "
                f"got {verification.manifest_sha256}"
            )
        manifest_file = tmp_path / "core-manifest.json"
        manifest_obj = json.loads(manifest_file.read_text(encoding="utf-8"))
        bundle_commit = manifest_obj.get("source_commit")
        if bundle_commit != binding.core_source_commit:
            raise ValueError(
                f"Core bundle source_commit mismatch: expected {binding.core_source_commit}, got {bundle_commit}"
            )

    core_identity = ArtifactIdentity(
        artifact_id=core_comp.artifact_id,
        version=core_comp.version,
        sha256=core_comp.artifact_sha256,
        size=core_comp.artifact_size,
        installed_identity_sha256=core_comp.installed_identity_sha256,
        artifact_format=core_comp.artifact_format,
    )

    return VerifiedCoreAuthority(
        binding=binding,
        core_zip_path=core_zip_file,
        core=core_identity,
    )


def bootstrap_core_authority_custody(
    *,
    source_envelope: Path,
    source_core_zip: Path,
    custody_root: Path,
    trusted_public_keys: Mapping[str, bytes] | None = None,
    expected: CoreAuthorityBinding,
) -> VerifiedCoreAuthority:
    custody_root = Path(custody_root)
    source_envelope = Path(source_envelope)
    source_core_zip = Path(source_core_zip)

    if not source_envelope.is_file():
        raise FileNotFoundError(f"Source envelope not found: {source_envelope}")
    if not source_core_zip.is_file():
        raise FileNotFoundError(f"Source core zip not found: {source_core_zip}")

    if trusted_public_keys is None:
        trusted_public_keys = PRODUCTION_RELEASE_PUBLIC_KEYS

    expected_prov = compute_core_provenance_sha256(
        authority_version_tag=expected.authority_version_tag,
        authority_release_sequence=expected.authority_release_sequence,
        authority_release_id=expected.authority_release_id,
        authority_payload_sha256=expected.authority_payload_sha256,
        authority_envelope_sha256=expected.authority_envelope_sha256,
        authority_key_id=expected.authority_key_id,
        core_source_commit=expected.core_source_commit,
    )
    if expected.provenance_sha256 != expected_prov:
        raise ValueError(f"Expected provenance_sha256 mismatch: {expected.provenance_sha256} vs {expected_prov}")

    index_path = custody_root / "core-authority-v1.json"
    if index_path.is_file():
        existing = load_verified_core_authority(custody_root, trusted_public_keys)
        if existing.binding != expected:
            raise ValueError(f"Custody already exists with mismatched binding: {existing.binding} vs {expected}")
        if source_envelope.read_bytes() != (custody_root / "release-v2.json").read_bytes():
            raise ValueError("Custody already exists with mismatched envelope bytes")
        if _get_sha256(source_core_zip) != existing.core.sha256:
            raise ValueError("Custody already exists with mismatched core zip bytes")
        return existing

    # Validate source envelope before persisting
    env_bytes = source_envelope.read_bytes()
    env_sha = hashlib.sha256(env_bytes).hexdigest()
    if env_sha != expected.authority_envelope_sha256:
        raise ValueError(f"Source envelope sha mismatch: expected {expected.authority_envelope_sha256}, got {env_sha}")

    try:
        env_doc = canonical_json_loads(env_bytes)
    except Exception as err:
        raise ValueError(f"Source envelope is not canonical JSON: {err}") from err

    release_set, verified_payload_sha = verify_release_envelope_v2(env_doc, trusted_public_keys)

    if env_doc.get("key_id") != expected.authority_key_id:
        raise ValueError(f"Source envelope key_id mismatch: {env_doc.get('key_id')} vs {expected.authority_key_id}")

    if verified_payload_sha != expected.authority_payload_sha256:
        raise ValueError(f"Source envelope payload sha mismatch: expected {expected.authority_payload_sha256}, got {verified_payload_sha}")

    if release_set.release_sequence != expected.authority_release_sequence:
        raise ValueError(f"Source envelope sequence mismatch: {release_set.release_sequence} vs {expected.authority_release_sequence}")

    if release_set.release_id != expected.authority_release_id:
        raise ValueError(f"Source envelope release_id mismatch: {release_set.release_id} vs {expected.authority_release_id}")

    if release_set.channel != "stable":
        raise ValueError(f"Source envelope channel must be 'stable', got {release_set.channel}")

    if "core" not in release_set.components:
        raise ValueError("Source envelope missing 'core' component")

    core_comp = release_set.components["core"]
    if core_comp.artifact_id != "NekoProxyCore.zip":
        raise ValueError(f"Invalid core artifact_id in source envelope: {core_comp.artifact_id}")

    expected_version = expected.authority_version_tag.lstrip("v")
    if core_comp.version != expected_version:
        raise ValueError(f"Source envelope core version mismatch: expected {expected_version}, got {core_comp.version}")

    # Validate source core zip
    zip_size = source_core_zip.stat().st_size
    zip_sha = _get_sha256(source_core_zip)
    if zip_size != core_comp.artifact_size or zip_sha != core_comp.artifact_sha256.lower():
        raise ValueError(
            f"Source core zip mismatch: expected {core_comp.artifact_sha256}/{core_comp.artifact_size}, "
            f"got {zip_sha}/{zip_size}"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        extract_core_bundle(source_core_zip, tmp_path)
        verification = verify_canonical_core_bundle(tmp_path)
        if not verification.valid:
            raise ValueError(f"Source core bundle verification failed: {verification.error}")
        if verification.manifest_sha256 != core_comp.installed_identity_sha256.lower():
            raise ValueError(
                f"Source core bundle installed identity mismatch: expected {core_comp.installed_identity_sha256}, "
                f"got {verification.manifest_sha256}"
            )
        manifest_file = tmp_path / "core-manifest.json"
        manifest_obj = json.loads(manifest_file.read_text(encoding="utf-8"))
        bundle_commit = manifest_obj.get("source_commit")
        if bundle_commit != expected.core_source_commit:
            raise ValueError(
                f"Source core bundle source_commit mismatch: expected {expected.core_source_commit}, got {bundle_commit}"
            )

    # Persist atomically
    custody_root.mkdir(parents=True, exist_ok=True)
    _atomic_write_file(custody_root / "release-v2.json", env_bytes)

    # Copy core zip atomically
    zip_target = custody_root / "NekoProxyCore.zip"
    temp_zip = custody_root / f".tmp_core_{os.getpid()}.zip"
    try:
        with source_core_zip.open("rb") as src, temp_zip.open("wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temp_zip, zip_target)
    except BaseException:
        if temp_zip.is_file():
            try:
                temp_zip.unlink()
            except OSError:
                pass
        raise

    meta_doc = {
        "authority_envelope_sha256": expected.authority_envelope_sha256,
        "authority_key_id": expected.authority_key_id,
        "authority_payload_sha256": expected.authority_payload_sha256,
        "authority_release_id": expected.authority_release_id,
        "authority_release_sequence": expected.authority_release_sequence,
        "authority_version_tag": expected.authority_version_tag,
        "core_source_commit": expected.core_source_commit,
        "provenance_sha256": expected.provenance_sha256,
        "schema_version": 1,
    }
    raw_meta = canonical_json_dumps(meta_doc) + b"\n"
    _atomic_write_file(index_path, raw_meta)

    return load_verified_core_authority(custody_root, trusted_public_keys)
