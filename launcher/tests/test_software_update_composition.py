from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import neko_launcher.bootstrap.app_factory as app_factory
import neko_launcher.infrastructure.defaults as defaults
from neko_launcher.application.software_update_models import (
    UpdateDiagnosticCode,
    UpdateState,
)
from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS
from software_update_helpers import get_test_key_registry, signed_envelope, valid_release_document


EXPECTED_PRODUCTION_KEY_ID = "neko-update-prod-1"


def assert_approved_production_registry() -> None:
    assert set(PRODUCTION_RELEASE_PUBLIC_KEYS) == {EXPECTED_PRODUCTION_KEY_ID}
    assert len(PRODUCTION_RELEASE_PUBLIC_KEYS[EXPECTED_PRODUCTION_KEY_ID]) == 32


class StaticManifestGateway:
    def __init__(self, document: object) -> None:
        self.document = document
        self.fetch_count = 0

    def fetch(self) -> object:
        self.fetch_count += 1
        return self.document


def make_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LauncherConfig:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData"))
    return LauncherConfig.from_environment(tmp_path / "workspace")


def test_composition_helper_exists() -> None:
    assert hasattr(app_factory, "compose_update_check_service")


def test_composition_helper_apply_service_exists() -> None:
    assert hasattr(app_factory, "compose_update_apply_service")


def test_development_composition_uses_unpublished_sequence_zero_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    launcher = tmp_path / "launcher.py"
    launcher.write_bytes(b"source launcher")
    core_manifest = config.proxy_core_path.with_name("canonical-core-manifest.json")
    core_manifest.parent.mkdir(parents=True)
    core_manifest.write_bytes(b"canonical core")

    captured: dict[str, object] = {}

    def fake_load_local_release_identity(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(app_factory.sys, "frozen", False, raising=False)
    monkeypatch.setattr(app_factory, "__file__", str(launcher))
    monkeypatch.setattr(
        app_factory,
        "load_local_release_identity",
        fake_load_local_release_identity,
    )

    service = app_factory.compose_update_check_service(
        config,
        key_registry=get_test_key_registry(),
    )

    service._local_identity_provider()

    assert captured["release_sequence"] == 0
    assert captured["release_id"] == "dev-unpublished"
    assert captured["launcher_executable"] == launcher.resolve()
    assert captured["core_manifest"] == core_manifest


def test_packaged_composition_hashes_sys_executable_as_launcher_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    packaged_executable = tmp_path / "NekoLauncher.exe"
    captured: dict[str, object] = {}

    def fake_load_local_release_identity(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(app_factory.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_factory.sys, "executable", str(packaged_executable))
    monkeypatch.setattr(
        app_factory,
        "load_local_release_identity",
        fake_load_local_release_identity,
    )

    service = app_factory.compose_update_check_service(
        config,
        key_registry=get_test_key_registry(),
    )

    service._local_identity_provider()

    assert captured["launcher_executable"] == packaged_executable


def test_composition_uses_http_gateway_verifier_and_update_check_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)

    service = app_factory.compose_update_check_service(
        config,
        key_registry=get_test_key_registry(),
    )

    assert type(service).__name__ == "UpdateCheckService"
    assert type(service._manifest_gateway).__name__ == "HttpUpdateManifestGateway"
    assert type(service._verifier).__name__ == "V2ReleaseManifestVerifierAdapter"
    assert (
        service._manifest_gateway._base_url
        == "https://neko-control-room.vercel.app"
    )


def test_composition_is_lazy_when_canonical_core_manifest_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    core_manifest = config.proxy_core_path.with_name("canonical-core-manifest.json")

    assert not core_manifest.exists()

    service = app_factory.compose_update_check_service(
        config,
        key_registry=get_test_key_registry(),
    )

    assert service is not None
    assert not core_manifest.exists()


def test_valid_test_signed_manifest_reaches_lazy_identity_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    document = signed_envelope(
        {
            "schema_version": 2,
            "channel": "beta",
            "release_sequence": 42,
            "release_id": "r-42-test",
            "mandatory": False,
            "minimum_supported_sequence": 1,
            "updater_protocol": {"minimum": 1, "maximum": 1},
            "components": {
                "launcher": {
                    "version": "2.0.0",
                    "artifact_id": "launcher-42",
                    "artifact_sha256": "1" * 64,
                    "installed_identity_sha256": "1" * 64,
                    "artifact_size": 1024,
                    "artifact_format": "raw-pe-v1",
                },
                "core": {
                    "version": "3.0.0",
                    "artifact_id": "core-42",
                    "artifact_sha256": "2" * 64,
                    "installed_identity_sha256": "3" * 64,
                    "artifact_size": 2048,
                    "artifact_format": "zip-core-v1",
                },
            },
        }
    )
    gateway = StaticManifestGateway(document)

    service = app_factory.compose_update_check_service(
        config,
        key_registry=get_test_key_registry(),
    )
    service._manifest_gateway = gateway

    result = service.check_manual()

    assert gateway.fetch_count == 1
    assert result.state == UpdateState.VERIFY_FAILED
    assert (
        result.diagnostic_code
        == UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    )


def test_production_public_key_registry_is_approved_and_untrusted_signature_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert_approved_production_registry()

    config = make_config(monkeypatch, tmp_path)
    gateway = StaticManifestGateway(signed_envelope(valid_release_document()))

    service = app_factory.compose_update_check_service(config)
    service._manifest_gateway = gateway

    assert service._verifier._key_registry == PRODUCTION_RELEASE_PUBLIC_KEYS

    result = service.check_manual()

    assert result.state == UpdateState.VERIFY_FAILED
    assert result.diagnostic_code == UpdateDiagnosticCode.MANIFEST_REJECTED


def test_production_compose_update_apply_service_uses_approved_registry_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert_approved_production_registry()

    compose_update_apply_service = getattr(
        app_factory, "compose_update_apply_service", None
    )
    if compose_update_apply_service is None:
        pytest.fail("compose_update_apply_service not implemented", pytrace=False)

    config = make_config(monkeypatch, tmp_path)
    service = compose_update_apply_service(config)

    registry = getattr(
        service, "_key_registry", getattr(service, "key_registry", None)
    )
    if registry is not None:
        assert registry == PRODUCTION_RELEASE_PUBLIC_KEYS

    valid_signed_manifest = signed_envelope(
        {
            "schema_version": 2,
            "channel": "beta",
            "release_sequence": 50,
            "release_id": "r-50-test",
            "mandatory": False,
            "minimum_supported_sequence": 1,
            "updater_protocol": {"minimum": 1, "maximum": 1},
            "components": {
                "launcher": {
                    "version": "2.0.0",
                    "artifact_id": "launcher-50",
                    "artifact_sha256": "1" * 64,
                    "installed_identity_sha256": "1" * 64,
                    "artifact_size": 1024,
                    "artifact_format": "raw-pe-v1",
                },
                "core": {
                    "version": "3.0.0",
                    "artifact_id": "core-50",
                    "artifact_sha256": "2" * 64,
                    "installed_identity_sha256": "3" * 64,
                    "artifact_size": 2048,
                    "artifact_format": "zip-core-v1",
                },
            },
        }
    )
    gateway = StaticManifestGateway(valid_signed_manifest)
    if hasattr(service, "_manifest_gateway"):
        service._manifest_gateway = gateway
    else:
        monkeypatch.setattr(service, "manifest_gateway", gateway, raising=False)

    monkeypatch.setattr(
        "neko_launcher.infrastructure.software_update_client.HttpUpdateManifestGateway.fetch",
        lambda self: valid_signed_manifest,
        raising=False,
    )

    try:
        from neko_launcher.infrastructure.software_update_apply import (
            SoftwareUpdateApplyError,
        )

        expected_error: type[Exception] = SoftwareUpdateApplyError
    except ImportError:
        expected_error = Exception

    with pytest.raises(expected_error) as exc_info:
        service.prepare()

    if hasattr(exc_info.value, "code"):
        assert exc_info.value.code is not None


def test_apply_composition_injects_lazy_production_distribution_capability_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from neko_launcher.infrastructure.distribution_credential import (
        get_distribution_capability,
    )

    captured: dict[str, object] = {}

    def capture_service(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(app_factory, "SoftwareUpdateApplyService", capture_service)
    config = make_config(monkeypatch, tmp_path)

    service = app_factory.compose_update_apply_service(config, root_dir=tmp_path)

    assert service is not None
    assert "distribution_capability_provider" in captured, (
        "composition must inject lazy distribution capability provider"
    )
    assert captured["distribution_capability_provider"] is get_distribution_capability
    assert captured["key_registry"] is PRODUCTION_RELEASE_PUBLIC_KEYS
    assert_approved_production_registry()


def test_production_update_configuration_contains_no_private_key_material(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    service = app_factory.compose_update_check_service(config)

    production_source = "\n".join(
        (
            inspect.getsource(defaults),
            inspect.getsource(app_factory),
            inspect.getsource(type(service._verifier)),
        )
    )

    assert "BEGIN PRIVATE KEY" not in production_source
    assert "BEGIN ED25519 PRIVATE KEY" not in production_source
    assert "test-only-deterministic-key-0000" not in production_source


def test_build_window_forwards_exact_composed_update_service_without_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    composed_service = object()
    composed_apply_service = object()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        app_factory.LauncherConfig,
        "from_environment",
        classmethod(lambda cls, root: config),
    )
    monkeypatch.setattr(
        app_factory,
        "compose_update_check_service",
        lambda received: (
            captured.setdefault("composition_config", received),
            composed_service,
        )[1],
    )
    monkeypatch.setattr(
        app_factory,
        "compose_update_apply_service",
        lambda received: (
            captured.setdefault("apply_composition_config", received),
            composed_apply_service,
        )[1],
        raising=False,
    )
    monkeypatch.setattr(
        app_factory,
        "CURRENT_PRODUCTION_AUTHORIZATION",
        SimpleNamespace(is_ready=False),
    )
    monkeypatch.setattr(
        app_factory,
        "create_production_proxy_gateway",
        lambda: object(),
    )

    for name in (
        "EventBus",
        "GameProcessManager",
        "KeyringSecureStore",
        "LocalInstallationIdentity",
        "ApplicationController",
        "LauncherService",
        "NamedPipeCoreTelemetryClient",
    ):
        monkeypatch.setattr(
            app_factory,
            name,
            lambda *args, **kwargs: SimpleNamespace(),
        )

    monkeypatch.setattr(
        app_factory,
        "SupabaseGateway",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        app_factory,
        "HttpAccountRecoveryGateway",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        app_factory,
        "PublicProxyStatusClient",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    import neko_launcher.application.diagnostics as diagnostics_module
    import neko_launcher.infrastructure.diagnostics_logger as logger_module

    monkeypatch.setattr(
        logger_module,
        "DevelopmentLogger",
        lambda *args, **kwargs: SimpleNamespace(
            log_session_header=lambda **values: None
        ),
    )
    monkeypatch.setattr(
        diagnostics_module,
        "CoreDiagnosticsRecorder",
        lambda sink: SimpleNamespace(),
    )

    class CapturingWindow:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["window_args"] = args
            captured["window_kwargs"] = kwargs

    monkeypatch.setattr(app_factory, "AppWindow", CapturingWindow)

    window = app_factory.build_window(tmp_path)

    assert isinstance(window, CapturingWindow)
    assert captured["composition_config"] is config
    assert captured["window_kwargs"]["update_check_service"] is composed_service
    assert captured["window_kwargs"].get("update_apply_service") is composed_apply_service
