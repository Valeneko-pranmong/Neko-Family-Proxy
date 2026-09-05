from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from neko_launcher.application.software_update_models import parse_release_set

_KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sign a canonical Neko software release-set payload.",
        allow_abbrev=False,
    )
    if any(
        argument == "--private-key" or argument.startswith("--private-key=")
        for argument in sys.argv[1:]
    ):
        parser.error("inline private key arguments are forbidden")

    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--private-key-file", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    key_data = path.read_bytes()
    if len(key_data) == 32:
        return Ed25519PrivateKey.from_private_bytes(key_data)

    loaded = serialization.load_pem_private_key(key_data, password=None)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError("PRIVATE_KEY_INVALID")
    return loaded


def _load_release(path: Path) -> tuple[dict[str, object], object]:
    raw_document = json.loads(path.read_text(encoding="utf-8"))
    release = parse_release_set(raw_document)
    return raw_document, release


def _canonical_payload(document: dict[str, object]) -> bytes:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _write_new_file(path: Path, document: dict[str, object]) -> None:
    data = (
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
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


def main() -> int:
    try:
        arguments = _arguments()
        if _KEY_ID_PATTERN.fullmatch(arguments.key_id) is None:
            raise ValueError("KEY_ID_INVALID")
        document, release = _load_release(arguments.input)
        payload = _canonical_payload(document)
        private_key = _load_private_key(arguments.private_key_file)
        signature = private_key.sign(payload)
        envelope = {
            "envelope_version": 1,
            "key_id": arguments.key_id,
            "payload_b64": base64.b64encode(payload).decode("ascii"),
            "signature_b64": base64.b64encode(signature).decode("ascii"),
        }
        _write_new_file(arguments.output, envelope)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print("software release signing failed", file=sys.stderr)
        return 1

    print(
        "signed software release "
        f"key_id={arguments.key_id} "
        f"release_id={release.release_id} "
        f"sequence={release.release_sequence} "
        f"output={arguments.output}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
