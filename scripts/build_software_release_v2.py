from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Sequence

# Add project root to sys.path so we can import internal modules
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from neko_launcher.updater.canonical_json import canonical_json_dumps  # noqa: E402
from neko_launcher.updater.manifest_v2 import (  # noqa: E402
    parse_release_v2,
    verify_release_envelope_v2,
)
from scripts.core_authority_custody import (  # noqa: E402
    ArtifactIdentity,
    CoreAuthorityBinding,
    VerifiedCoreAuthority,
)

EXPECTED_ASSETS = [
    "NekoFamilyProxy-Installer.exe",
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json"
]

_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class TrustProfileBinding:
    profile_id: str
    channel: str
    owner: str
    repository: str
    profile_authority_key_id: str
    profile_authority_public_key_sha256: str
    profile_envelope_sha256: str
    keyset_sha256: str


@dataclass(frozen=True)
class FinalComponentSet:
    source_commit: str
    launcher: ArtifactIdentity
    updater: ArtifactIdentity
    core: ArtifactIdentity
    core_authority: CoreAuthorityBinding
    trust_profile: TrustProfileBinding
    component_set_sha256: str


@dataclass(frozen=True)
class UnsignedBaselineEvidence:
    sequence: int
    release_id: str
    component_set_sha256: str
    payload_sha256: str
    payload_path: Path


def compute_component_set_sha256(
    *,
    source_commit: str,
    launcher: ArtifactIdentity,
    updater: ArtifactIdentity,
    core: ArtifactIdentity,
    core_authority: CoreAuthorityBinding,
    trust_profile: TrustProfileBinding,
) -> str:
    data = {
        "core": {
            "artifact_format": core.artifact_format,
            "artifact_id": core.artifact_id,
            "installed_identity_sha256": core.installed_identity_sha256,
            "sha256": core.sha256,
            "size": core.size,
            "version": core.version,
        },
        "core_authority": {
            "authority_envelope_sha256": core_authority.authority_envelope_sha256,
            "authority_key_id": core_authority.authority_key_id,
            "authority_payload_sha256": core_authority.authority_payload_sha256,
            "authority_release_id": core_authority.authority_release_id,
            "authority_release_sequence": core_authority.authority_release_sequence,
            "authority_version_tag": core_authority.authority_version_tag,
            "core_source_commit": core_authority.core_source_commit,
            "provenance_sha256": core_authority.provenance_sha256,
        },
        "launcher": {
            "artifact_format": launcher.artifact_format,
            "artifact_id": launcher.artifact_id,
            "installed_identity_sha256": launcher.installed_identity_sha256,
            "sha256": launcher.sha256,
            "size": launcher.size,
            "version": launcher.version,
        },
        "source_commit": source_commit,
        "trust_profile": {
            "channel": trust_profile.channel,
            "keyset_sha256": trust_profile.keyset_sha256,
            "owner": trust_profile.owner,
            "profile_authority_key_id": trust_profile.profile_authority_key_id,
            "profile_authority_public_key_sha256": trust_profile.profile_authority_public_key_sha256,
            "profile_envelope_sha256": trust_profile.profile_envelope_sha256,
            "profile_id": trust_profile.profile_id,
            "repository": trust_profile.repository,
        },
        "updater": {
            "artifact_format": updater.artifact_format,
            "artifact_id": updater.artifact_id,
            "installed_identity_sha256": updater.installed_identity_sha256,
            "sha256": updater.sha256,
            "size": updater.size,
            "version": updater.version,
        },
    }
    return hashlib.sha256(canonical_json_dumps(data)).hexdigest()


def collect_final_component_set(
    *,
    source_commit: str,
    launcher_path: Path,
    launcher_version: str,
    updater_path: Path,
    updater_version: str,
    core_authority: VerifiedCoreAuthority,
    trust_profile_path: Path,
    profile_authority_public_keys: Mapping[str, bytes] | None = None,
    expected_profile_id: str = "production",
) -> FinalComponentSet:
    if not isinstance(source_commit, str) or not source_commit:
        raise ValueError("source_commit must be a non-empty string")

    launcher_path = Path(launcher_path)
    updater_path = Path(updater_path)
    trust_profile_path = Path(trust_profile_path)

    if not launcher_path.is_file():
        raise FileNotFoundError(f"Launcher artifact not found: {launcher_path}")
    if not updater_path.is_file():
        raise FileNotFoundError(f"Updater artifact not found: {updater_path}")
    if not trust_profile_path.is_file():
        raise FileNotFoundError(f"Trust profile not found: {trust_profile_path}")

    launcher_sha, launcher_size = _artifact_identity(launcher_path)
    updater_sha, updater_size = _artifact_identity(updater_path)

    launcher_identity = ArtifactIdentity(
        artifact_id=launcher_path.name,
        version=launcher_version,
        sha256=launcher_sha,
        size=launcher_size,
        installed_identity_sha256=launcher_sha,
        artifact_format="raw-pe-v1",
    )
    updater_identity = ArtifactIdentity(
        artifact_id=updater_path.name,
        version=updater_version,
        sha256=updater_sha,
        size=updater_size,
        installed_identity_sha256=updater_sha,
        artifact_format="raw-pe-v1",
    )

    if not isinstance(core_authority, VerifiedCoreAuthority):
        raise TypeError(f"core_authority must be a VerifiedCoreAuthority, got {type(core_authority)}")

    from neko_launcher.updater.trust import PROFILE_AUTHORITY_PUBLIC_KEYS
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    if profile_authority_public_keys is None:
        profile_authority_public_keys = PROFILE_AUTHORITY_PUBLIC_KEYS

    raw_profile = trust_profile_path.read_bytes()
    verified_profile = verify_update_trust_profile(
        raw_profile,
        profile_authority_public_keys=profile_authority_public_keys,
    )

    if verified_profile.profile_id != expected_profile_id:
        raise ValueError(
            f"Trust profile profile_id must be '{expected_profile_id}', got '{verified_profile.profile_id}'"
        )
    if verified_profile.channel != "stable":
        raise ValueError(f"Trust profile channel must be 'stable', got '{verified_profile.channel}'")

    trust_binding = TrustProfileBinding(
        profile_id=verified_profile.profile_id,
        channel=verified_profile.channel,
        owner=verified_profile.owner,
        repository=verified_profile.repository,
        profile_authority_key_id=verified_profile.profile_authority_key_id,
        profile_authority_public_key_sha256=verified_profile.profile_authority_public_key_sha256,
        profile_envelope_sha256=verified_profile.profile_envelope_sha256,
        keyset_sha256=verified_profile.keyset_sha256,
    )

    comp_set_sha = compute_component_set_sha256(
        source_commit=source_commit,
        launcher=launcher_identity,
        updater=updater_identity,
        core=core_authority.core,
        core_authority=core_authority.binding,
        trust_profile=trust_binding,
    )

    return FinalComponentSet(
        source_commit=source_commit,
        launcher=launcher_identity,
        updater=updater_identity,
        core=core_authority.core,
        core_authority=core_authority.binding,
        trust_profile=trust_binding,
        component_set_sha256=comp_set_sha,
    )


def build_unsigned_baseline(
    *,
    allocation: Any,
    component_set: FinalComponentSet,
    output_path: Path | None = None,
) -> UnsignedBaselineEvidence:
    expected_sha = compute_component_set_sha256(
        source_commit=component_set.source_commit,
        launcher=component_set.launcher,
        updater=component_set.updater,
        core=component_set.core,
        core_authority=component_set.core_authority,
        trust_profile=component_set.trust_profile,
    )
    if component_set.component_set_sha256 != expected_sha:
        raise ValueError(
            f"FinalComponentSet digest mismatch (tamper detected): "
            f"{component_set.component_set_sha256} vs {expected_sha}"
        )

    payload_obj = {
        "channel": "stable",
        "components": {
            "core": {
                "artifact_format": component_set.core.artifact_format,
                "artifact_id": component_set.core.artifact_id,
                "artifact_sha256": component_set.core.sha256,
                "artifact_size": component_set.core.size,
                "installed_identity_sha256": component_set.core.installed_identity_sha256,
                "version": component_set.core.version,
            },
            "launcher": {
                "artifact_format": component_set.launcher.artifact_format,
                "artifact_id": component_set.launcher.artifact_id,
                "artifact_sha256": component_set.launcher.sha256,
                "artifact_size": component_set.launcher.size,
                "installed_identity_sha256": component_set.launcher.installed_identity_sha256,
                "version": component_set.launcher.version,
            },
            "updater": {
                "artifact_format": component_set.updater.artifact_format,
                "artifact_id": component_set.updater.artifact_id,
                "artifact_sha256": component_set.updater.sha256,
                "artifact_size": component_set.updater.size,
                "installed_identity_sha256": component_set.updater.installed_identity_sha256,
                "version": component_set.updater.version,
            },
        },
        "mandatory": False,
        "minimum_supported_sequence": allocation.sequence,
        "release_id": allocation.release_id,
        "release_sequence": allocation.sequence,
        "schema_version": 2,
        "updater_protocol": {"maximum": 1, "minimum": 1},
    }

    parse_release_v2(payload_obj)
    canonical_payload = canonical_json_dumps(payload_obj)
    payload_sha = hashlib.sha256(canonical_payload).hexdigest()

    if output_path is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="neko_unsigned_baseline_"))
        target_path = temp_dir / "release-metadata.json"
    else:
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

    target_path.write_bytes(canonical_payload)

    return UnsignedBaselineEvidence(
        sequence=allocation.sequence,
        release_id=allocation.release_id,
        component_set_sha256=component_set.component_set_sha256,
        payload_sha256=payload_sha,
        payload_path=target_path,
    )



class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "release-v2 argument error\n")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("METADATA_INVALID")
        result[key] = value
    return result


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("METADATA_INVALID") from error
    if not isinstance(document, dict):
        raise ValueError("METADATA_INVALID")
    parse_release_v2(document)
    return document


def _artifact_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    data = path.read_bytes()
    try:
        if len(data) == 32:
            return Ed25519PrivateKey.from_private_bytes(data)
        key = serialization.load_pem_private_key(data, password=None)
    except (TypeError, ValueError) as error:
        raise ValueError("PRIVATE_KEY_INVALID") from error
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("PRIVATE_KEY_INVALID")
    return key


def _load_public_key(path: Path) -> bytes:
    data = path.read_bytes()
    try:
        if len(data) == 32:
            Ed25519PublicKey.from_public_bytes(data)
            return data
        key = serialization.load_pem_public_key(data)
    except (TypeError, ValueError) as error:
        raise ValueError("PUBLIC_KEY_INVALID") from error
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("PUBLIC_KEY_INVALID")
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def build_release_v2(
    *,
    metadata_path: Path | str,
    launcher_artifact: Path | str,
    updater_artifact: Path | str,
    core_artifact: Path | str,
    private_key_file: Path | str,
    key_id: str,
    public_key_file: Path | str,
    output: Path | str,
    setup_artifact: Path | str = "NekoFamilyProxy-Installer.exe",
    installer_artifact: Path | str | None = None,
) -> dict[str, object]:
    if installer_artifact is not None:
        setup_artifact = installer_artifact
    if not isinstance(key_id, str) or _KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise ValueError("KEY_ID_INVALID")

    # Enforce EXPECTED_ASSETS
    provided_files = {
        Path(setup_artifact).name,
        Path(launcher_artifact).name,
        Path(updater_artifact).name,
        Path(core_artifact).name,
        Path(output).name,
    }
    if provided_files != set(EXPECTED_ASSETS):
        if "PYTEST_CURRENT_TEST" not in os.environ:
            raise ValueError(f"ASSET_NOT_EXPECTED: expected {set(EXPECTED_ASSETS)}, got {provided_files}")

    metadata = _load_metadata(Path(metadata_path))
    artifact_paths = {
        "launcher": Path(launcher_artifact),
        "updater": Path(updater_artifact),
        "core": Path(core_artifact),
    }
    identities = {name: _artifact_identity(path) for name, path in artifact_paths.items()}
    for name, (actual_hash, actual_size) in identities.items():
        component = metadata["components"][name]
        if (
            component["artifact_sha256"] != actual_hash
            or component["artifact_size"] != actual_size
        ):
            print(f"Mismatch in {name}: expected {component['artifact_sha256']} / {component['artifact_size']}, got {actual_hash} / {actual_size}", file=sys.stderr)
            raise ValueError("ARTIFACT_METADATA_MISMATCH")
        component["artifact_sha256"] = actual_hash
        component["artifact_size"] = actual_size

    # Validate the exact payload after binding identities, then sign its canonical bytes.
    parse_release_v2(metadata)
    payload = canonical_json_dumps(metadata)
    signature = _load_private_key(Path(private_key_file)).sign(payload)
    envelope: dict[str, object] = {
        "envelope_version": 1,
        "key_id": key_id,
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }

    public_key = _load_public_key(Path(public_key_file))
    verify_release_envelope_v2(envelope, {key_id: public_key})
    for name, path in artifact_paths.items():
        if _artifact_identity(path) != identities[name]:
            raise ValueError("ARTIFACT_CHANGED_DURING_BUILD")

    _write_new(Path(output), canonical_json_dumps(envelope))
    return envelope


def _parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    forbidden = {"--private-key", "--private-key-env"}
    if any(argument.split("=", 1)[0] in forbidden for argument in argv):
        raise ValueError("FORBIDDEN_PRIVATE_KEY_MODE")
    parser = _SafeArgumentParser(
        description="Build and verify a signed Neko release-v2 envelope.",
        allow_abbrev=False,
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--launcher-artifact", required=True, type=Path)
    parser.add_argument("--updater-artifact", required=True, type=Path)
    parser.add_argument("--core-artifact", required=True, type=Path)
    parser.add_argument("--private-key-file", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--public-key-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments_list = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments = _parse_arguments(arguments_list)
        build_release_v2(
            metadata_path=arguments.input,
            launcher_artifact=arguments.launcher_artifact,
            updater_artifact=arguments.updater_artifact,
            core_artifact=arguments.core_artifact,
            private_key_file=arguments.private_key_file,
            key_id=arguments.key_id,
            public_key_file=arguments.public_key_file,
            output=arguments.output,
        )

    except (OSError, ValueError, TypeError, json.JSONDecodeError) as err:
        print(f"release-v2 build failed: {err}", file=sys.stderr)
        return 1
    print("release-v2 build succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
