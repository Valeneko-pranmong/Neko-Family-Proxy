from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.manifest_v2 import (
    parse_release_v2,
    verify_release_envelope_v2,
)

_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


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
    core_artifact: Path | str,
    private_key_file: Path | str,
    key_id: str,
    public_key_file: Path | str,
    output: Path | str,
) -> dict[str, object]:
    if not isinstance(key_id, str) or _KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise ValueError("KEY_ID_INVALID")

    metadata = _load_metadata(Path(metadata_path))
    artifact_paths = {
        "launcher": Path(launcher_artifact),
        "core": Path(core_artifact),
    }
    identities = {name: _artifact_identity(path) for name, path in artifact_paths.items()}
    for name, (actual_hash, actual_size) in identities.items():
        component = metadata["components"][name]
        if (
            component["artifact_sha256"] != actual_hash
            or component["artifact_size"] != actual_size
        ):
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
            core_artifact=arguments.core_artifact,
            private_key_file=arguments.private_key_file,
            key_id=arguments.key_id,
            public_key_file=arguments.public_key_file,
            output=arguments.output,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print("release-v2 build failed", file=sys.stderr)
        return 1
    print("release-v2 build succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
