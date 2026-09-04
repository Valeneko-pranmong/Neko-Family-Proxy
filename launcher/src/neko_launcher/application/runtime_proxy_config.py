from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    OpaquePermit,
)


MAX_SAFE_INTEGER = 9007199254740991


class OpaqueRuntimeCredential:
    """Sensitive runtime proxy credential whose str and repr never expose its value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if (
            not isinstance(value, str)
            or not value
            or not (1 <= len(value) <= 256)
            or not value.isascii()
            or "\r" in value
            or "\n" in value
            or any(ord(c) < 32 or ord(c) > 126 for c in value)
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE)
        self._value = value

    def __repr__(self) -> str:
        return "OpaqueRuntimeCredential(<redacted>)"

    __str__ = __repr__

    def reveal_for_transport(self) -> str:
        return self._value

    @property
    def diagnostic_length(self) -> int:
        return len(self._value)


@dataclass(frozen=True)
class RuntimeProxyConfig:
    schema_version: int
    config_version: int
    endpoint_id: str
    host: str
    port: int
    protocol: str
    cipher: str
    credential: OpaqueRuntimeCredential
    issued_at: int
    expires_at: int

    def __repr__(self) -> str:
        return (
            f"RuntimeProxyConfig(schema_version={self.schema_version}, "
            f"config_version={self.config_version}, "
            f"endpoint_id={self.endpoint_id!r}, "
            f"host={self.host!r}, "
            f"port={self.port}, "
            f"protocol={self.protocol!r}, "
            f"cipher={self.cipher!r}, "
            f"credential={self.credential!r}, "
            f"issued_at={self.issued_at}, "
            f"expires_at={self.expires_at})"
        )

    __str__ = __repr__

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.config_version) is not int
            or not (1 <= self.config_version <= MAX_SAFE_INTEGER)
            or type(self.endpoint_id) is not str
            or not (1 <= len(self.endpoint_id) <= 64)
            or not self.endpoint_id.isascii()
            or any(ord(c) < 32 or ord(c) > 126 for c in self.endpoint_id)
            or type(self.host) is not str
            or not (1 <= len(self.host) <= 253)
            or not self.host.isascii()
            or any(ord(c) < 32 or ord(c) > 126 for c in self.host)
            or type(self.port) is not int
            or not (1 <= self.port <= 65535)
            or self.protocol != "shadowsocks"
            or type(self.cipher) is not str
            or not (1 <= len(self.cipher) <= 64)
            or not self.cipher.isascii()
            or any(ord(c) < 32 or ord(c) > 126 for c in self.cipher)
            or not isinstance(self.credential, OpaqueRuntimeCredential)
            or type(self.issued_at) is not int
            or not (0 <= self.issued_at <= MAX_SAFE_INTEGER - 120)
            or type(self.expires_at) is not int
            or not (0 <= self.expires_at <= MAX_SAFE_INTEGER)
            or (self.expires_at - self.issued_at) != 120
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE)

    @property
    def canonical_bytes(self) -> bytes:
        text = (
            f"schema_version={self.schema_version}\n"
            f"config_version={self.config_version}\n"
            f"endpoint_id={self.endpoint_id}\n"
            f"host={self.host}\n"
            f"port={self.port}\n"
            f"protocol={self.protocol}\n"
            f"cipher={self.cipher}\n"
            f"credential={self.credential.reveal_for_transport()}\n"
            f"issued_at={self.issued_at}\n"
            f"expires_at={self.expires_at}\n"
        )
        return text.encode("ascii")

    @property
    def canonical_digest(self) -> str:
        return sha256(self.canonical_bytes).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeProxyConfig:
        if not isinstance(data, dict):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE)

        allowed_keys = {
            "schemaVersion",
            "configVersion",
            "endpointId",
            "host",
            "port",
            "protocol",
            "cipher",
            "credential",
            "issuedAt",
            "expiresAt",
        }
        if set(data.keys()) != allowed_keys:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE)

        cred_raw = data["credential"]
        if not isinstance(cred_raw, str):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE)

        return cls(
            schema_version=data["schemaVersion"],
            config_version=data["configVersion"],
            endpoint_id=data["endpointId"],
            host=data["host"],
            port=data["port"],
            protocol=data["protocol"],
            cipher=data["cipher"],
            credential=OpaqueRuntimeCredential(cred_raw),
            issued_at=data["issuedAt"],
            expires_at=data["expiresAt"],
        )


@dataclass(frozen=True)
class LaunchAuthorizationBundle:
    permit: OpaquePermit
    runtime_config: RuntimeProxyConfig

    def __repr__(self) -> str:
        return (
            f"LaunchAuthorizationBundle(permit={self.permit!r}, "
            f"runtime_config={self.runtime_config!r})"
        )

    __str__ = __repr__

    def __post_init__(self) -> None:
        if not isinstance(self.permit, OpaquePermit) or not isinstance(
            self.runtime_config, RuntimeProxyConfig
        ):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE)
