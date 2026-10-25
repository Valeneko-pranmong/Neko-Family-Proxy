#!/usr/bin/env python3
"""Sign an update trust profile with a profile-authority Ed25519 key."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_update_trust_profile import (  # noqa: E402
    UpdateTrustProfileSpec,
    assemble_verified_profile_envelope,
    canonicalize_profile_payload,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sign a canonical update trust profile with a profile-authority key",
    )
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--private-key-file", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--public-key-hex", required=True)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec_data = json.loads(args.spec.read_text(encoding="utf-8"))
    spec = UpdateTrustProfileSpec(
        profile_id=spec_data["profile_id"],
        channel=spec_data["channel"],
        owner=spec_data["owner"],
        repository=spec_data["repository"],
        release_keys=spec_data["release_keys"],
    )
    payload_bytes = canonicalize_profile_payload(spec)

    private_key = serialization.load_pem_private_key(
        args.private_key_file.read_bytes(),
        password=None,
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Profile authority key must be Ed25519")
    signature = private_key.sign(payload_bytes)
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    if public_key.hex() != args.public_key_hex.lower():
        raise ValueError("Profile authority public key does not match the private key")

    envelope = assemble_verified_profile_envelope(
        payload_bytes=payload_bytes,
        profile_authority_key_id=args.key_id,
        detached_signature=signature,
        profile_authority_public_keys={args.key_id: public_key},
    )
    args.out.write_bytes(envelope)
    return 0


if __name__ == "__main__":
    sys.exit(main())
