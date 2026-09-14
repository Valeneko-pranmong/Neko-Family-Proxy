#!/usr/bin/env python3
"""Deterministic generic detached-signature release-v2 envelope assembler and verifier."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads  # noqa: E402
from neko_launcher.updater.manifest_v2 import parse_release_v2, verify_release_envelope_v2  # noqa: E402

_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def canonicalize_release_v2_payload(document: object) -> bytes:
    if not isinstance(document, dict):
        raise ValueError("Release payload must be a JSON object")

    # Validate against ReleaseSetV2 contract
    parse_release_v2(document)

    # Returns canonical UTF-8 JSON bytes with no trailing LF
    payload_bytes = canonical_json_dumps(document)

    # Verify round-trip
    reparsed = canonical_json_loads(payload_bytes)
    if not isinstance(reparsed, dict):
        raise ValueError("Payload failed canonical JSON round-trip")
    parse_release_v2(reparsed)

    return payload_bytes


def assemble_verified_release_v2_envelope(
    *,
    payload_bytes: bytes,
    key_id: str,
    detached_signature: bytes,
    release_public_keys: Mapping[str, bytes],
) -> bytes:
    if not isinstance(payload_bytes, (bytes, bytearray)):
        raise ValueError("payload_bytes must be bytes")
    if not isinstance(detached_signature, (bytes, bytearray)):
        raise ValueError("detached_signature must be bytes")
    if len(detached_signature) != 64:
        raise ValueError(f"Invalid detached signature length: expected 64, got {len(detached_signature)}")

    if not isinstance(key_id, str) or not _KEY_ID_PATTERN.fullmatch(key_id):
        raise ValueError(f"Invalid key_id: {key_id!r}")

    if key_id not in release_public_keys:
        raise ValueError(f"Unknown key_id: {key_id}")

    # Verify payload format first
    try:
        payload_doc = canonical_json_loads(payload_bytes)
    except Exception as exc:
        raise ValueError(f"Payload bytes are not valid canonical JSON: {exc}") from exc

    parse_release_v2(payload_doc)

    payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
    signature_b64 = base64.b64encode(detached_signature).decode("ascii")

    envelope = {
        "envelope_version": 1,
        "key_id": key_id,
        "payload_b64": payload_b64,
        "signature_b64": signature_b64,
    }

    # Sorted compact UTF-8 JSON + trailing LF
    envelope_bytes = canonical_json_dumps(envelope) + b"\n"

    # Verify through canonical verify_release_envelope_v2 contract
    envelope_doc = json.loads(envelope_bytes.decode("utf-8"))
    _, returned_payload_sha = verify_release_envelope_v2(envelope_doc, release_public_keys)

    expected_sha = hashlib.sha256(payload_bytes).hexdigest()
    if returned_payload_sha != expected_sha:
        raise ValueError(
            f"Envelope verification payload SHA mismatch: got {returned_payload_sha}, expected {expected_sha}"
        )

    return envelope_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generic detached-signature release-v2 envelope assembler and verifier (no private keys)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    can_parser = subparsers.add_parser("canonicalize", help="Canonicalize a release-v2 document into payload bytes")
    can_parser.add_argument("--document", required=True, type=Path, help="Path to release document JSON")
    can_parser.add_argument("--out", type=Path, help="Output path for canonical payload bytes")

    asm_parser = subparsers.add_parser("assemble", help="Assemble envelope from canonical payload and detached signature")
    asm_parser.add_argument("--payload", required=True, type=Path, help="Path to canonical payload bytes")
    asm_parser.add_argument("--key-id", required=True, type=str, help="Release key_id")
    asm_parser.add_argument("--detached-signature", required=True, type=Path, help="Path to 64-byte binary detached signature")
    asm_parser.add_argument("--public-key-hex", required=True, type=str, help="Release public key in 64-character hex")
    asm_parser.add_argument("--out", required=True, type=Path, help="Output path for envelope JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "canonicalize":
        doc = json.loads(args.document.read_text(encoding="utf-8"))
        payload_bytes = canonicalize_release_v2_payload(doc)
        if args.out:
            args.out.write_bytes(payload_bytes)
        else:
            sys.stdout.buffer.write(payload_bytes)
        return 0

    if args.command == "assemble":
        payload_bytes = args.payload.read_bytes()
        detached_sig = args.detached_signature.read_bytes()
        pub_bytes = bytes.fromhex(args.public_key_hex)
        keys = {args.key_id: pub_bytes}

        envelope_bytes = assemble_verified_release_v2_envelope(
            payload_bytes=payload_bytes,
            key_id=args.key_id,
            detached_signature=detached_sig,
            release_public_keys=keys,
        )
        args.out.write_bytes(envelope_bytes)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
