"""Signed release envelope and payload schema v2 verifier for Phase 3 updates."""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import re
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from neko_launcher.updater.canonical_json import canonical_json_loads

_ENVELOPE_KEYS = {
    "envelope_version",
    "key_id",
    "payload_b64",
    "signature_b64",
}
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")

_MAX_PAYLOAD_SIZE = 49_152
_SIGNATURE_SIZE = 64
_PUBLIC_KEY_SIZE = 32

_V2_TOP_KEYS = {
    "schema_version",
    "channel",
    "release_sequence",
    "release_id",
    "mandatory",
    "minimum_supported_sequence",
    "updater_protocol",
    "components",
}
_V2_PROTOCOL_KEYS = {"minimum", "maximum"}
_V2_COMPONENT_KEYS = {
    "version",
    "artifact_id",
    "artifact_sha256",
    "artifact_size",
    "installed_identity_sha256",
    "artifact_format",
}


@dataclass(frozen=True)
class ComponentV2:
    name: str
    version: str
    artifact_id: str
    artifact_sha256: str
    artifact_size: int
    installed_identity_sha256: str
    artifact_format: str


@dataclass(frozen=True)
class UpdaterProtocol:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class ReleaseSetV2:
    schema_version: int
    channel: str
    release_sequence: int
    release_id: str
    mandatory: bool
    minimum_supported_sequence: int
    updater_protocol: UpdaterProtocol
    components: dict[str, ComponentV2]


def _decode_strict_base64(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as err:
        raise ValueError("INVALID_BASE64") from err

    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("INVALID_BASE64: non-canonical padding or encoding")
    return decoded


def parse_release_v2(payload: dict[str, Any]) -> ReleaseSetV2:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dict")
    if set(payload.keys()) != _V2_TOP_KEYS:
        raise ValueError("Invalid top-level fields for ReleaseSetV2")

    if payload["schema_version"] != 2:
        raise ValueError("schema_version must be 2")
    if payload["channel"] != "beta":
        raise ValueError("channel must be 'beta'")

    seq = payload["release_sequence"]
    if type(seq) is not int or seq < 1 or seq > 9223372036854775807:
        raise ValueError("Invalid release_sequence")

    min_seq = payload["minimum_supported_sequence"]
    if type(min_seq) is not int or min_seq < 1 or min_seq > seq:
        raise ValueError("Invalid minimum_supported_sequence")

    if not isinstance(payload["mandatory"], bool):
        raise ValueError("mandatory must be a boolean")

    rel_id = payload["release_id"]
    if not isinstance(rel_id, str) or not _RELEASE_ID_PATTERN.fullmatch(rel_id):
        raise ValueError("Invalid release_id")

    proto = payload["updater_protocol"]
    if not isinstance(proto, dict) or set(proto.keys()) != _V2_PROTOCOL_KEYS:
        raise ValueError("Invalid updater_protocol object")
    p_min, p_max = proto["minimum"], proto["maximum"]
    if type(p_min) is not int or type(p_max) is not int or not (1 <= p_min <= p_max <= 65535):
        raise ValueError("Invalid updater_protocol ranges")
    protocol = UpdaterProtocol(minimum=p_min, maximum=p_max)

    comps = payload["components"]
    if not isinstance(comps, dict) or set(comps.keys()) != {"launcher", "core"}:
        raise ValueError("components must contain exactly 'launcher' and 'core'")

    parsed_components = {}
    for name in ("launcher", "core"):
        c = comps[name]
        if not isinstance(c, dict) or set(c.keys()) != _V2_COMPONENT_KEYS:
            raise ValueError(f"Invalid fields in component {name}")

        version = c["version"]
        if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
            raise ValueError(f"Invalid version in component {name}")

        art_id = c["artifact_id"]
        if not isinstance(art_id, str) or not _ARTIFACT_ID_PATTERN.fullmatch(art_id):
            raise ValueError(f"Invalid artifact_id in component {name}")

        art_sha = c["artifact_sha256"]
        if not isinstance(art_sha, str) or not _HEX64_PATTERN.fullmatch(art_sha):
            raise ValueError(f"Invalid artifact_sha256 in component {name}")

        inst_sha = c["installed_identity_sha256"]
        if not isinstance(inst_sha, str) or not _HEX64_PATTERN.fullmatch(inst_sha):
            raise ValueError(f"Invalid installed_identity_sha256 in component {name}")

        size = c["artifact_size"]
        if type(size) is not int or isinstance(size, bool) or size <= 0:
            raise ValueError(f"Invalid artifact_size in component {name}")

        fmt = c["artifact_format"]
        if name == "launcher":
            if fmt != "raw-pe-v1":
                raise ValueError("Launcher artifact_format must be 'raw-pe-v1'")
            if size > 134217728:  # 128 MiB
                raise ValueError("Launcher artifact exceeds 128 MiB")
            if art_sha != inst_sha:
                raise ValueError("Launcher artifact_sha256 must equal installed_identity_sha256")
        elif name == "core":
            if fmt != "zip-core-v1":
                raise ValueError("Core artifact_format must be 'zip-core-v1'")
            if size > 1073741824:  # 1 GiB
                raise ValueError("Core artifact exceeds 1 GiB")

        parsed_components[name] = ComponentV2(
            name=name,
            version=version,
            artifact_id=art_id,
            artifact_sha256=art_sha,
            artifact_size=size,
            installed_identity_sha256=inst_sha,
            artifact_format=fmt,
        )

    return ReleaseSetV2(
        schema_version=2,
        channel="beta",
        release_sequence=seq,
        release_id=rel_id,
        mandatory=payload["mandatory"],
        minimum_supported_sequence=min_seq,
        updater_protocol=protocol,
        components=parsed_components,
    )


def verify_release_envelope_v2(
    document: object,
    key_registry: Mapping[str, bytes],
) -> tuple[ReleaseSetV2, str]:
    """Verify an Ed25519-signed release envelope and return (ReleaseSetV2, payload_sha256)."""
    if not isinstance(document, dict):
        raise ValueError("Envelope must be a dict")
    if set(document.keys()) != _ENVELOPE_KEYS:
        raise ValueError("Invalid envelope schema keys")

    if document["envelope_version"] != 1:
        raise ValueError("Unsupported envelope version")

    key_id = document["key_id"]
    if not isinstance(key_id, str) or not _KEY_ID_PATTERN.fullmatch(key_id):
        raise ValueError("Invalid key_id")

    if key_id not in key_registry:
        raise ValueError(f"Unknown key_id: {key_id}")

    public_key_bytes = key_registry[key_id]
    if not isinstance(public_key_bytes, bytes) or len(public_key_bytes) != _PUBLIC_KEY_SIZE:
        raise ValueError("Invalid public key in registry")

    payload_bytes = _decode_strict_base64(document["payload_b64"])
    signature_bytes = _decode_strict_base64(document["signature_b64"])

    if len(payload_bytes) > _MAX_PAYLOAD_SIZE:
        raise ValueError("Payload exceeds maximum size")
    if len(signature_bytes) != _SIGNATURE_SIZE:
        raise ValueError("Invalid signature length")

    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    except ValueError as err:
        raise ValueError("Invalid public key") from err

    try:
        public_key.verify(signature_bytes, payload_bytes)
    except InvalidSignature as err:
        raise ValueError("Invalid signature") from err

    payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

    try:
        payload_obj = canonical_json_loads(payload_bytes)
    except ValueError as err:
        raise ValueError(f"Payload is not valid canonical UTF-8 JSON: {err}") from err

    release_set = parse_release_v2(payload_obj)
    return release_set, payload_sha256
