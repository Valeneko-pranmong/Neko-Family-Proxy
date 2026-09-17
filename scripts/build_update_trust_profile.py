#!/usr/bin/env python3
"""Deterministic unsigned update trust profile canonicalizer and detached-signature assembler."""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Add launcher/src to sys.path so neko_launcher modules can be imported
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads  # noqa: E402
from neko_launcher.updater.trust_profile import verify_update_trust_profile  # noqa: E402

_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class UpdateTrustProfileSpec:
    profile_id: str
    channel: str
    owner: str
    repository: str
    release_keys: list[dict[str, str]]


def canonicalize_profile_payload(spec: UpdateTrustProfileSpec) -> bytes:
    for field_name in ("profile_id", "channel", "owner", "repository"):
        val = getattr(spec, field_name)
        if not isinstance(val, str) or not _ID_PATTERN.fullmatch(val):
            raise ValueError(f"Invalid profile spec field {field_name}: {val!r}")

    if not isinstance(spec.release_keys, list) or len(spec.release_keys) == 0:
        raise ValueError("release_keys must be a non-empty list")

    seen_ids: list[str] = []
    clean_keys: list[dict[str, str]] = []
    for item in spec.release_keys:
        if not isinstance(item, dict) or set(item.keys()) != {"key_id", "public_key_hex"}:
            raise ValueError(f"Invalid release_keys entry: {item}")
        k_id = item["key_id"]
        k_hex = item["public_key_hex"]
        if not isinstance(k_id, str) or not _ID_PATTERN.fullmatch(k_id):
            raise ValueError(f"Invalid release key_id: {k_id!r}")
        if not isinstance(k_hex, str) or not _HEX64_PATTERN.fullmatch(k_hex):
            raise ValueError(f"Invalid public_key_hex for {k_id}: {k_hex!r}")

        if k_id in seen_ids:
            raise ValueError(f"Duplicate release key_id: {k_id}")
        seen_ids.append(k_id)
        clean_keys.append({"key_id": k_id, "public_key_hex": k_hex})

    if seen_ids != sorted(seen_ids):
        raise ValueError("release_keys must be strictly sorted by key_id")

    if spec.profile_id == "production":
        if any("proof" in k.lower() for k in seen_ids):
            raise ValueError("Production profile must not contain proof keys")
        if spec.repository == "Neko-Family-Proxy-Updates":
            raise ValueError(
                "Production profile repository 'Neko-Family-Proxy-Updates' is superseded; "
                "expected canonical repository 'Neko-Family-Proxy'"
            )
        if spec.owner != "Valeneko-pranmong" or spec.repository != "Neko-Family-Proxy":
            raise ValueError(
                f"Production profile repository mismatch: expected 'Valeneko-pranmong/Neko-Family-Proxy', "
                f"got '{spec.owner}/{spec.repository}'"
            )

    payload = {
        "channel": spec.channel,
        "owner": spec.owner,
        "profile_id": spec.profile_id,
        "release_keys": clean_keys,
        "repository": spec.repository,
    }
    # No trailing LF
    return canonical_json_dumps(payload)


def assemble_verified_profile_envelope(
    *,
    payload_bytes: bytes,
    profile_authority_key_id: str,
    detached_signature: bytes,
    profile_authority_public_keys: Mapping[str, bytes],
) -> bytes:
    if not isinstance(payload_bytes, (bytes, bytearray)):
        raise ValueError("payload_bytes must be bytes")
    if not isinstance(detached_signature, (bytes, bytearray)):
        raise ValueError("detached_signature must be bytes")
    if len(detached_signature) != 64:
        raise ValueError(f"Invalid detached signature length: expected 64, got {len(detached_signature)}")

    if not isinstance(profile_authority_key_id, str) or not _ID_PATTERN.fullmatch(profile_authority_key_id):
        raise ValueError(f"Invalid profile_authority_key_id: {profile_authority_key_id!r}")

    if profile_authority_key_id not in profile_authority_public_keys:
        raise ValueError(f"Unknown authority key_id: {profile_authority_key_id}")

    try:
        payload_obj = canonical_json_loads(payload_bytes)
    except Exception as exc:
        raise ValueError(f"payload_bytes is not valid canonical JSON: {exc}") from exc

    sig_b64 = base64.b64encode(detached_signature).decode("ascii")
    envelope_obj = {
        "key_id": profile_authority_key_id,
        "payload": payload_obj,
        "schema_version": 1,
        "signature_b64": sig_b64,
    }

    envelope_bytes = canonical_json_dumps(envelope_obj) + b"\n"

    # Verify self-consistency through the canonical verifier
    verified = verify_update_trust_profile(
        envelope_bytes,
        profile_authority_public_keys=profile_authority_public_keys,
    )

    if verified.profile_authority_key_id != profile_authority_key_id:
        raise ValueError("Verified key_id does not match requested authority key_id")

    return envelope_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic unsigned update trust profile canonicalizer and assembler (read-only, no private keys)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    can_parser = subparsers.add_parser("canonicalize", help="Canonicalize a profile spec into payload bytes")
    can_parser.add_argument("--spec", required=True, type=Path, help="Path to profile spec JSON")
    can_parser.add_argument("--out", type=Path, help="Output path for canonical payload bytes")

    asm_parser = subparsers.add_parser("assemble", help="Assemble envelope from canonical payload and detached signature")
    asm_parser.add_argument("--payload", required=True, type=Path, help="Path to canonical payload bytes")
    asm_parser.add_argument("--key-id", required=True, type=str, help="Profile Authority key_id")
    asm_parser.add_argument("--detached-signature", required=True, type=Path, help="Path to 64-byte binary detached signature")
    asm_parser.add_argument("--authority-public-key-hex", required=True, type=str, help="Authority public key in 64-character hex")
    asm_parser.add_argument("--out", required=True, type=Path, help="Output path for envelope JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "canonicalize":
        spec_data = json.loads(args.spec.read_text(encoding="utf-8"))
        spec = UpdateTrustProfileSpec(
            profile_id=spec_data["profile_id"],
            channel=spec_data["channel"],
            owner=spec_data["owner"],
            repository=spec_data["repository"],
            release_keys=spec_data["release_keys"],
        )
        payload_bytes = canonicalize_profile_payload(spec)
        if args.out:
            args.out.write_bytes(payload_bytes)
        else:
            sys.stdout.buffer.write(payload_bytes)
        return 0

    if args.command == "assemble":
        payload_bytes = args.payload.read_bytes()
        detached_sig = args.detached_signature.read_bytes()
        pub_bytes = bytes.fromhex(args.authority_public_key_hex)
        authority_keys = {args.key_id: pub_bytes}

        envelope_bytes = assemble_verified_profile_envelope(
            payload_bytes=payload_bytes,
            profile_authority_key_id=args.key_id,
            detached_signature=detached_sig,
            profile_authority_public_keys=authority_keys,
        )
        args.out.write_bytes(envelope_bytes)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
