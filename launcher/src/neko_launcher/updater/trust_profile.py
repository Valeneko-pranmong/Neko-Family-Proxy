from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads
from neko_launcher.updater.trust import PROFILE_AUTHORITY_PUBLIC_KEYS

_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENVELOPE_KEYS = frozenset({"key_id", "payload", "schema_version", "signature_b64"})
_PAYLOAD_KEYS = frozenset({"channel", "owner", "profile_id", "release_keys", "repository"})
_RELEASE_KEY_KEYS = frozenset({"key_id", "public_key_hex"})


@dataclass(frozen=True)
class VerifiedUpdateTrustProfile:
    profile_id: str
    channel: str
    owner: str
    repository: str
    release_public_keys: Mapping[str, bytes]
    keyset_sha256: str
    profile_envelope_sha256: str
    profile_authority_key_id: str
    profile_authority_public_key_sha256: str


def verify_update_trust_profile(
    raw: bytes,
    *,
    profile_authority_public_keys: Mapping[str, bytes],
) -> VerifiedUpdateTrustProfile:
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("raw must be bytes")

    # The persisted file bytes are exactly canonical_json_dumps(envelope_obj) + b"\n";
    # exactly one terminal LF and no BOM, CRLF, leading/trailing whitespace, or second newline.
    if not raw.endswith(b"\n") or raw.endswith(b"\r\n") or raw.endswith(b"\n\n"):
        raise ValueError("Raw profile must end with exactly one terminal LF without CRLF")

    body = bytes(raw[:-1])
    if body.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Raw profile must not contain a UTF-8 BOM")

    if body != body.strip(b" \t\r\n"):
        raise ValueError("Raw profile must not contain leading or trailing whitespace before LF")

    try:
        envelope_obj = canonical_json_loads(body)
    except Exception as exc:
        raise ValueError(f"Invalid canonical JSON body: {exc}") from exc

    if canonical_json_dumps(envelope_obj) != body:
        raise ValueError("Profile envelope body is not canonical UTF-8 JSON")

    if not isinstance(envelope_obj, dict):
        raise ValueError("Profile envelope must be a JSON object")

    if set(envelope_obj.keys()) != _ENVELOPE_KEYS:
        raise ValueError(f"Invalid profile envelope keys: expected {_ENVELOPE_KEYS}, got {set(envelope_obj.keys())}")

    if envelope_obj["schema_version"] != 1:
        raise ValueError(f"Unsupported schema_version: {envelope_obj['schema_version']}")

    key_id = envelope_obj["key_id"]
    if not isinstance(key_id, str) or not _ID_PATTERN.fullmatch(key_id):
        raise ValueError(f"Invalid authority key_id format: {key_id!r}")

    if key_id not in profile_authority_public_keys:
        raise ValueError(f"Unknown authority key_id: {key_id}")

    auth_pub_bytes = profile_authority_public_keys[key_id]
    if not isinstance(auth_pub_bytes, bytes) or len(auth_pub_bytes) != 32:
        raise ValueError(f"Invalid authority public key for key_id {key_id}")

    payload = envelope_obj["payload"]
    if not isinstance(payload, dict):
        raise ValueError("Profile payload must be a JSON object")

    if set(payload.keys()) != _PAYLOAD_KEYS:
        raise ValueError(f"Invalid profile payload keys: expected {_PAYLOAD_KEYS}, got {set(payload.keys())}")

    for field_name in ("profile_id", "channel", "owner", "repository"):
        val = payload[field_name]
        if not isinstance(val, str) or not _ID_PATTERN.fullmatch(val):
            raise ValueError(f"Invalid payload field {field_name}: {val!r}")

    profile_id = payload["profile_id"]
    channel = payload["channel"]
    owner = payload["owner"]
    repository = payload["repository"]

    release_keys = payload["release_keys"]
    if not isinstance(release_keys, list) or len(release_keys) == 0:
        raise ValueError("release_keys must be a non-empty list")

    seen_key_ids: list[str] = []
    key_dict: dict[str, bytes] = {}
    for item in release_keys:
        if not isinstance(item, dict) or set(item.keys()) != _RELEASE_KEY_KEYS:
            raise ValueError(f"Invalid release_keys item: {item}")
        rel_key_id = item["key_id"]
        rel_pub_hex = item["public_key_hex"]
        if not isinstance(rel_key_id, str) or not _ID_PATTERN.fullmatch(rel_key_id):
            raise ValueError(f"Invalid release key_id: {rel_key_id!r}")
        if not isinstance(rel_pub_hex, str) or not _HEX64_PATTERN.fullmatch(rel_pub_hex):
            raise ValueError(f"Invalid public_key_hex for {rel_key_id}: {rel_pub_hex!r}")

        if rel_key_id in seen_key_ids:
            raise ValueError(f"Duplicate release key_id: {rel_key_id}")
        seen_key_ids.append(rel_key_id)
        key_dict[rel_key_id] = bytes.fromhex(rel_pub_hex)

    if seen_key_ids != sorted(seen_key_ids):
        raise ValueError("release_keys must be strictly sorted by unique key_id")

    if profile_id == "production" and any("proof" in k.lower() for k in seen_key_ids):
        raise ValueError("Production profile must not contain proof keys")

    payload_bytes = canonical_json_dumps(payload)
    sig_b64 = envelope_obj["signature_b64"]
    if not isinstance(sig_b64, str):
        raise ValueError("signature_b64 must be a string")

    try:
        sig_bytes = base64.b64decode(sig_b64, validate=True)
        if base64.b64encode(sig_bytes).decode("ascii") != sig_b64:
            raise ValueError("signature_b64 is not canonical base64")
    except Exception as exc:
        raise ValueError(f"Invalid base64 signature: {exc}") from exc

    if len(sig_bytes) != 64:
        raise ValueError(f"Invalid signature length: expected 64 bytes, got {len(sig_bytes)}")

    try:
        pub_key = Ed25519PublicKey.from_public_bytes(auth_pub_bytes)
        pub_key.verify(sig_bytes, payload_bytes)
    except InvalidSignature as exc:
        raise ValueError(f"Invalid signature for profile: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Signature verification failed: {exc}") from exc

    profile_envelope_sha256 = hashlib.sha256(raw).hexdigest()
    keyset_sha256 = hashlib.sha256(canonical_json_dumps({"release_keys": release_keys})).hexdigest()
    profile_authority_public_key_sha256 = hashlib.sha256(auth_pub_bytes).hexdigest()

    return VerifiedUpdateTrustProfile(
        profile_id=profile_id,
        channel=channel,
        owner=owner,
        repository=repository,
        release_public_keys=types.MappingProxyType(key_dict),
        keyset_sha256=keyset_sha256,
        profile_envelope_sha256=profile_envelope_sha256,
        profile_authority_key_id=key_id,
        profile_authority_public_key_sha256=profile_authority_public_key_sha256,
    )


def load_installed_update_trust_profile(install_root: Path) -> VerifiedUpdateTrustProfile:
    profile_path = Path(install_root) / "trust" / "update-profile-v1.json"
    if not profile_path.is_file():
        raise FileNotFoundError(f"Installed trust profile missing at {profile_path}")

    raw = profile_path.read_bytes()
    return verify_update_trust_profile(
        raw,
        profile_authority_public_keys=PROFILE_AUTHORITY_PUBLIC_KEYS,
    )
