"""Application adapter for verified release-set v2 manifests."""

from __future__ import annotations

from collections.abc import Mapping

from neko_launcher.application.software_update_models import ComponentRelease, ReleaseSet
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2

_HELPER_PROTOCOL_VERSION = 1


class V2ManifestVerificationError(ValueError):
    """Fail-closed manifest rejection with a service-safe diagnostic code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class V2ReleaseManifestVerifierAdapter:
    def __init__(self, key_registry: Mapping[str, bytes]) -> None:
        self._key_registry = dict(key_registry)

    def verify(self, document: object) -> ReleaseSet:
        try:
            release_v2, _payload_sha256 = verify_release_envelope_v2(
                document,
                self._key_registry,
            )
        except ValueError:
            raise V2ManifestVerificationError("INVALID_PAYLOAD_SCHEMA") from None

        protocol = release_v2.updater_protocol
        if not protocol.minimum <= _HELPER_PROTOCOL_VERSION <= protocol.maximum:
            raise V2ManifestVerificationError("INVALID_PAYLOAD_SCHEMA")

        components = tuple(
            ComponentRelease(
                name=component.name,
                version=component.version,
                artifact_id=component.artifact_id,
                artifact_sha256=component.artifact_sha256,
                artifact_size=component.artifact_size,
                installed_identity_sha256=component.installed_identity_sha256,
            )
            for component in (
                release_v2.components["launcher"],
                release_v2.components["core"],
            )
        )
        return ReleaseSet(
            schema_version=release_v2.schema_version,
            channel=release_v2.channel,
            release_sequence=release_v2.release_sequence,
            release_id=release_v2.release_id,
            mandatory=release_v2.mandatory,
            minimum_supported_sequence=release_v2.minimum_supported_sequence,
            components=components,
        )
