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
from neko_launcher.infrastructure.github_asset_downloader import (
    GitHubAssetDownloader,
    GitHubManifestDownloader,
)
from neko_launcher.infrastructure.github_release import GitHubLatestReleaseGateway
from neko_launcher.infrastructure.github_release_binding import (
    GitHubReleaseResolver,
    GitHubReleaseResolverError,
    ResolvedGitHubRelease,
)
from neko_launcher.updater.manifest_v2 import UPDATER_PROTOCOL_VERSION
from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS
from software_update_helpers import get_test_key_registry


EXPECTED_PRODUCTION_KEY_ID = "neko-update-prod-1"


def assert_approved_production_registry() -> None:
    assert set(PRODUCTION_RELEASE_PUBLIC_KEYS) == {EXPECTED_PRODUCTION_KEY_ID}
    assert len(PRODUCTION_RELEASE_PUBLIC_KEYS[EXPECTED_PRODUCTION_KEY_ID]) == 32


class StaticReleaseGateway:
    def __init__(self, resolved: ResolvedGitHubRelease | None = None, error: Exception | None = None) -> None:
        self.resolved = resolved
        self.error = error
        self.fetch_count = 0

    def resolve(self) -> ResolvedGitHubRelease | None:
        self.fetch_count += 1
        if self.error is not None:
            raise self.error
        return self.resolved


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


def test_composition_uses_github_resolver_and_update_check_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)

    service = app_factory.compose_update_check_service(
        config,
        key_registry=get_test_key_registry(),
        root_dir=tmp_path,
    )

    assert type(service).__name__ == "UpdateCheckService"
    resolver = service._release_gateway
    assert isinstance(resolver, GitHubReleaseResolver)
    assert isinstance(resolver._release_gateway, GitHubLatestReleaseGateway)
    assert isinstance(resolver._manifest_downloader, GitHubManifestDownloader)
    assert resolver._key_registry == get_test_key_registry()
    assert resolver._install_root == tmp_path
    assert resolver._updater_protocol == UPDATER_PROTOCOL_VERSION


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


def test_production_public_key_registry_is_approved_and_untrusted_signature_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert_approved_production_registry()

    config = make_config(monkeypatch, tmp_path)
    gateway = StaticReleaseGateway(error=GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED"))

    service = app_factory.compose_update_check_service(config)
    assert service._release_gateway._key_registry == PRODUCTION_RELEASE_PUBLIC_KEYS

    service._release_gateway = gateway
    result = service.check_manual()

    assert result.state == UpdateState.VERIFY_FAILED
    assert result.diagnostic_code == UpdateDiagnosticCode.MANIFEST_REJECTED


def test_production_compose_update_apply_service_uses_approved_registry_and_resolver(
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
    service = compose_update_apply_service(config, root_dir=tmp_path)

    resolver = getattr(service, "release_gateway", getattr(service, "_release_gateway", None))
    assert isinstance(resolver, GitHubReleaseResolver)
    assert resolver._key_registry == PRODUCTION_RELEASE_PUBLIC_KEYS
    assert resolver._install_root == tmp_path
    assert resolver._updater_protocol == UPDATER_PROTOCOL_VERSION

    downloader = getattr(service, "asset_downloader", getattr(service, "_asset_downloader", None))
    assert isinstance(downloader, GitHubAssetDownloader)

    # No separate key registry or grant gateway or capability provider on apply service
    assert not hasattr(service, "grant_gateway")
    assert not hasattr(service, "distribution_capability_provider")


def test_build_window_shares_same_resolver_instance_between_check_and_apply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        app_factory.LauncherConfig,
        "from_environment",
        classmethod(lambda cls, root: config),
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
    check_service = captured["window_kwargs"]["update_check_service"]
    apply_service = captured["window_kwargs"]["update_apply_service"]

    # Proves same resolver instance injected into check and apply!
    assert check_service._release_gateway is apply_service.release_gateway


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
            inspect.getsource(type(service._release_gateway)),
        )
    )

    assert "BEGIN PRIVATE KEY" not in production_source
    assert "BEGIN ED25519 PRIVATE KEY" not in production_source
    assert "test-only-deterministic-key-0000" not in production_source


def test_source_guards_no_obsolete_update_apis_in_app_factory() -> None:
    source = inspect.getsource(app_factory)
    forbidden = (
        "HttpArtifactGrantGateway",
        "get_distribution_capability",
        "/api/software-update",
        "software_update_api_url",
    )
    for term in forbidden:
        assert term not in source, f"Forbidden legacy update term found in app_factory: {term}"
