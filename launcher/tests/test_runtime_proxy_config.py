from __future__ import annotations

import pytest

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    OpaquePermit,
)
from neko_launcher.application.runtime_proxy_config import (
    LaunchAuthorizationBundle,
    OpaqueRuntimeCredential,
    RuntimeProxyConfig,
)

SENTINEL_SECRET = "SENTINEL_PROXY_SECRET_42"
EXPECTED_DIGEST = "02060535a1e3c4db74edffc8d0b1f5bfd6feee948980669ff06acab9afdecf4d"


def sample_runtime_config(
    credential: str = SENTINEL_SECRET,
    **overrides: object,
) -> RuntimeProxyConfig:
    kwargs: dict[str, object] = {
        "schema_version": 1,
        "config_version": 18,
        "endpoint_id": "japan-vps-1",
        "host": "127.0.0.1",
        "port": 8389,
        "protocol": "shadowsocks",
        "cipher": "aes-256-gcm",
        "credential": OpaqueRuntimeCredential(credential),
        "issued_at": 1000,
        "expires_at": 1120,
    }
    kwargs.update(overrides)
    return RuntimeProxyConfig(**kwargs)  # type: ignore[arg-type]


def test_opaque_runtime_credential_redacts_secret_in_str_repr():
    cred = OpaqueRuntimeCredential(SENTINEL_SECRET)
    assert SENTINEL_SECRET not in str(cred)
    assert SENTINEL_SECRET not in repr(cred)
    assert str(cred) == "OpaqueRuntimeCredential(<redacted>)"
    assert repr(cred) == "OpaqueRuntimeCredential(<redacted>)"
    assert cred.reveal_for_transport() == SENTINEL_SECRET
    assert cred.diagnostic_length == len(SENTINEL_SECRET)


def test_opaque_runtime_credential_rejects_empty():
    with pytest.raises(AuthorizedCoreError) as exc_info:
        OpaqueRuntimeCredential("")
    assert exc_info.value.code == AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE


def test_runtime_proxy_config_str_repr_redacts_secret():
    config = sample_runtime_config()
    assert SENTINEL_SECRET not in str(config)
    assert SENTINEL_SECRET not in repr(config)


def test_launch_authorization_bundle_str_repr_redacts_secret_and_permit():
    permit = OpaquePermit("super-secret-permit-token")
    config = sample_runtime_config()
    bundle = LaunchAuthorizationBundle(permit=permit, runtime_config=config)
    bundle_str = str(bundle)
    bundle_repr = repr(bundle)
    assert SENTINEL_SECRET not in bundle_str
    assert SENTINEL_SECRET not in bundle_repr
    assert "super-secret-permit-token" not in bundle_str
    assert "super-secret-permit-token" not in bundle_repr
    assert bundle.permit is permit
    assert bundle.runtime_config is config


def test_runtime_proxy_config_canonical_bytes_and_digest():
    config = sample_runtime_config()
    expected_canonical = (
        b"schema_version=1\n"
        b"config_version=18\n"
        b"endpoint_id=japan-vps-1\n"
        b"host=127.0.0.1\n"
        b"port=8389\n"
        b"protocol=shadowsocks\n"
        b"cipher=aes-256-gcm\n"
        b"credential=SENTINEL_PROXY_SECRET_42\n"
        b"issued_at=1000\n"
        b"expires_at=1120\n"
    )
    assert config.canonical_bytes == expected_canonical
    assert config.canonical_digest == EXPECTED_DIGEST


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("schema_version", 2),
        ("schema_version", 0),
        ("schema_version", "1"),
        ("config_version", 0),
        ("config_version", -1),
        ("config_version", "18"),
        ("endpoint_id", ""),
        ("endpoint_id", "x" * 65),
        ("endpoint_id", "japan\nvps"),
        ("endpoint_id", "japan\rvps"),
        ("endpoint_id", "japan\0vps"),
        ("host", ""),
        ("host", "x" * 254),
        ("host", "127.0.0.1\n"),
        ("port", 0),
        ("port", 65536),
        ("port", "8389"),
        ("protocol", "vmess"),
        ("protocol", "Shadowsocks"),
        ("cipher", ""),
        ("cipher", "x" * 65),
        ("cipher", "aes\n256"),
        ("issued_at", -1),
        ("issued_at", "1000"),
        ("expires_at", 1000),  # must be > issued_at
        ("expires_at", 999),
        ("expires_at", 1000 + 121),  # lifetime exactly 120 seconds in v1
        ("expires_at", 1000 + 119),
    ],
)
def test_runtime_proxy_config_validates_bounds_and_invariants(field: str, bad_value: object):
    with pytest.raises(AuthorizedCoreError) as exc_info:
        sample_runtime_config(**{field: bad_value})
    assert exc_info.value.code == AuthorizedCoreErrorCode.RUNTIME_CONFIGURATION_UNAVAILABLE


def test_runtime_proxy_config_from_dict_strict():
    data = {
        "schemaVersion": 1,
        "configVersion": 18,
        "endpointId": "japan-vps-1",
        "host": "127.0.0.1",
        "port": 8389,
        "protocol": "shadowsocks",
        "cipher": "aes-256-gcm",
        "credential": SENTINEL_SECRET,
        "issuedAt": 1000,
        "expiresAt": 1120,
    }
    config = RuntimeProxyConfig.from_dict(data)
    assert config.schema_version == 1
    assert config.config_version == 18
    assert config.endpoint_id == "japan-vps-1"
    assert config.host == "127.0.0.1"
    assert config.port == 8389
    assert config.protocol == "shadowsocks"
    assert config.cipher == "aes-256-gcm"
    assert config.credential.reveal_for_transport() == SENTINEL_SECRET
    assert config.issued_at == 1000
    assert config.expires_at == 1120
    assert config.canonical_digest == EXPECTED_DIGEST


def test_runtime_proxy_config_from_dict_rejects_unknown_or_missing_fields():
    base = {
        "schemaVersion": 1,
        "configVersion": 18,
        "endpointId": "japan-vps-1",
        "host": "127.0.0.1",
        "port": 8389,
        "protocol": "shadowsocks",
        "cipher": "aes-256-gcm",
        "credential": SENTINEL_SECRET,
        "issuedAt": 1000,
        "expiresAt": 1120,
    }
    with pytest.raises(AuthorizedCoreError):
        RuntimeProxyConfig.from_dict({**base, "extra": "field"})

    for k in base:
        sub = dict(base)
        del sub[k]
        with pytest.raises(AuthorizedCoreError):
            RuntimeProxyConfig.from_dict(sub)
