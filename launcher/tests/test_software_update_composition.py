from __future__ import annotations

import inspect
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping

import pytest

import neko_launcher.bootstrap.app_factory as app_factory
import neko_launcher.infrastructure.defaults as defaults
from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    LocalReleaseIdentity,
    UpdateDiagnosticCode,
    UpdateState,
)
from neko_launcher.infrastructure.authenticated_release_identity import (
    AuthenticatedReleaseIdentityReader,
)
from neko_launcher.infrastructure.config import LauncherConfig
from neko_launcher.infrastructure.github_asset_downloader import (
    GitHubManifestDownloader,
)
from neko_launcher.infrastructure.github_release import GitHubLatestReleaseGateway
from neko_launcher.infrastructure.github_release_binding import (
    GitHubReleaseResolver,
    GitHubReleaseResolverError,
    ResolvedGitHubRelease,
)
from neko_launcher.infrastructure.update_channel_profile import UpdateChannelProfile
from neko_launcher.updater.manifest_v2 import UPDATER_PROTOCOL_VERSION
from neko_launcher.updater.trust_profile import (
    VerifiedUpdateTrustProfile,
    load_installed_update_trust_profile,
)
from software_update_helpers import get_test_key_registry

try:
    from neko_launcher.infrastructure.software_update_authority_admission import (
        SoftwareUpdateAuthorityAdmissionService,
    )
except ImportError:
    SoftwareUpdateAuthorityAdmissionService = None  # type: ignore[assignment, misc]



TEST_KEY_ID = "neko-update-prod-1"
TEST_PUBLIC_KEY = get_test_key_registry()["neko-update-test-1"]


def make_test_verified_profile(
    *,
    profile_id: str = "production",
    channel: str = "stable",
    owner: str = "Valeneko-pranmong",
    repo: str = "Neko-Family-Proxy-Updates-Proof",
    keys: Mapping[str, bytes] | None = None,
) -> VerifiedUpdateTrustProfile:
    key_mapping = keys if keys is not None else {TEST_KEY_ID: TEST_PUBLIC_KEY}
    return VerifiedUpdateTrustProfile(
        profile_id=profile_id,
        channel=channel,
        owner=owner,
        repository=repo,
        release_public_keys=MappingProxyType(dict(key_mapping)),
        keyset_sha256="1" * 64,
        profile_envelope_sha256="2" * 64,
        profile_authority_key_id="auth-key",
        profile_authority_public_key_sha256="3" * 64,
    )


def make_test_local_identity(sequence: int = 8) -> LocalReleaseIdentity:
    binding = AuthenticatedReleaseBinding(
        release_sequence=sequence,
        release_id=f"r{sequence}-stable",
        payload_sha256="a" * 64,
    )
    return LocalReleaseIdentity(
        committed=binding,
        high_water=binding,
        observed=binding,
        failed=None,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256="b" * 64,
        updater_version="5.1.2",
        updater_installed_identity_sha256="c" * 64,
        core_version="1.0.0",
        core_installed_identity_sha256="d" * 64,
    )


class FakeIdentityReader:
    def __init__(
        self,
        identity: LocalReleaseIdentity,
        trust_profile: VerifiedUpdateTrustProfile | None = None,
    ) -> None:
        self.identity = identity
        self.calls: list[Path] = []
        self._trust_profile = trust_profile or make_test_verified_profile()

    def read(self, install_root: Path) -> LocalReleaseIdentity:
        self.calls.append(install_root)
        return self.identity


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
    assert app_factory.AuthenticatedReleaseIdentityReader is AuthenticatedReleaseIdentityReader
    assert app_factory.load_installed_update_trust_profile is load_installed_update_trust_profile


def test_composition_helper_apply_service_exists() -> None:
    assert hasattr(app_factory, "compose_update_apply_service")


def test_composition_helper_coordinator_exists() -> None:
    assert hasattr(app_factory, "compose_update_coordinator")


def test_production_composition_uses_authenticated_identity_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    reader = FakeIdentityReader(make_test_local_identity(sequence=8))
    service = app_factory.compose_update_check_service(
        config,
        root_dir=tmp_path,
        identity_reader=reader,
    )
    result = service._local_identity_provider()
    assert result.committed.release_sequence == 8
    assert reader.calls == [tmp_path]


def test_production_composition_does_not_accept_raw_release_key_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    with pytest.raises(TypeError):
        app_factory.compose_update_check_service(
            config,
            key_registry=get_test_key_registry(),  # type: ignore[call-arg]
        )


def test_production_composition_derives_discovery_and_identity_from_same_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    profile = make_test_verified_profile(owner="Valeneko-pranmong", repo="Neko-Family-Proxy-Updates-Proof")
    monkeypatch.setattr(
        app_factory,
        "load_installed_update_trust_profile",
        lambda root: profile,
    )
    reader = FakeIdentityReader(make_test_local_identity(sequence=8), trust_profile=profile)
    service = app_factory.compose_update_check_service(
        config,
        root_dir=tmp_path,
        identity_reader=reader,
    )
    assert service._release_gateway._channel_profile.owner == "Valeneko-pranmong"
    assert service._release_gateway._channel_profile.repository == "Neko-Family-Proxy-Updates-Proof"
    result = service._local_identity_provider()
    assert result.committed.release_sequence == 8
    assert result.release_id != "dev-unpublished"


def test_production_composition_gateway_uses_profile_authenticated_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    profile = make_test_verified_profile(owner="Valeneko-pranmong", repo="Neko-Family-Proxy-Updates-Proof")
    reader = FakeIdentityReader(make_test_local_identity(sequence=8), trust_profile=profile)
    service = app_factory.compose_update_check_service(
        config,
        verified_profile=profile,
        root_dir=tmp_path,
        identity_reader=reader,
    )
    gateway = service._release_gateway._release_gateway
    assert gateway.channel_profile.owner == "Valeneko-pranmong"
    assert gateway.channel_profile.repository == "Neko-Family-Proxy-Updates-Proof"
    assert gateway.channel_profile.latest_release_api == (
        "https://api.github.com/repos/Valeneko-pranmong/Neko-Family-Proxy-Updates-Proof/releases/latest"
    )


def test_production_composition_rejects_mismatched_profile_between_gateway_and_identity_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    profile_a = make_test_verified_profile(owner="Valeneko-pranmong", repo="RepoA")
    profile_b = make_test_verified_profile(owner="Valeneko-pranmong", repo="RepoB")

    channel_profile_b = UpdateChannelProfile.from_verified(profile_b)
    mismatched_resolver = GitHubReleaseResolver(
        release_gateway=GitHubLatestReleaseGateway(channel_profile=channel_profile_b),
        manifest_downloader=GitHubManifestDownloader(channel_profile=channel_profile_b),
        channel_profile=channel_profile_b,
        install_root=tmp_path,
        updater_protocol=UPDATER_PROTOCOL_VERSION,
    )
    reader_a = FakeIdentityReader(make_test_local_identity(sequence=5), trust_profile=profile_a)

    with pytest.raises(ValueError, match="mismatch"):
        app_factory.compose_update_check_service(
            config,
            resolver=mismatched_resolver,
            identity_reader=reader_a,
            root_dir=tmp_path,
        )


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

    def fake_load_development_release_identity(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(app_factory.sys, "frozen", False, raising=False)
    monkeypatch.setattr(app_factory, "__file__", str(launcher))
    monkeypatch.setattr(
        app_factory,
        "load_development_release_identity",
        fake_load_development_release_identity,
    )

    service = app_factory.compose_development_update_check_service(
        config,
        resolver=StaticReleaseGateway(),
    )

    service._local_identity_provider()

    assert captured["launcher_version"] == app_factory.__version__
    assert captured["launcher_executable"] == launcher.resolve()
    assert captured["core_version"] == "dev-unpublished"
    assert captured["core_manifest"] == core_manifest


def test_packaged_composition_hashes_sys_executable_as_launcher_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    packaged_executable = tmp_path / "NekoLauncher.exe"
    captured: dict[str, object] = {}

    def fake_load_development_release_identity(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(app_factory.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_factory.sys, "executable", str(packaged_executable))
    monkeypatch.setattr(
        app_factory,
        "load_development_release_identity",
        fake_load_development_release_identity,
    )

    service = app_factory.compose_development_update_check_service(
        config,
        resolver=StaticReleaseGateway(),
    )

    service._local_identity_provider()

    assert captured["launcher_executable"] == packaged_executable


def test_composition_uses_github_resolver_and_update_check_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    profile = make_test_verified_profile()
    reader = FakeIdentityReader(make_test_local_identity(sequence=8), trust_profile=profile)

    service = app_factory.compose_update_check_service(
        config,
        verified_profile=profile,
        root_dir=tmp_path,
        identity_reader=reader,
    )

    assert type(service).__name__ == "UpdateCheckService"
    resolver = service._release_gateway
    assert isinstance(resolver, GitHubReleaseResolver)
    assert isinstance(resolver._release_gateway, GitHubLatestReleaseGateway)
    assert isinstance(resolver._manifest_downloader, GitHubManifestDownloader)
    assert resolver._channel_profile == UpdateChannelProfile.from_verified(profile)
    assert resolver._install_root == tmp_path
    assert resolver._updater_protocol == UPDATER_PROTOCOL_VERSION


def test_composition_is_lazy_when_canonical_core_manifest_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    core_manifest = config.proxy_core_path.with_name("canonical-core-manifest.json")

    assert not core_manifest.exists()

    profile = make_test_verified_profile()
    reader = FakeIdentityReader(make_test_local_identity(sequence=8), trust_profile=profile)
    service = app_factory.compose_update_check_service(
        config,
        verified_profile=profile,
        root_dir=tmp_path,
        identity_reader=reader,
    )

    assert service is not None
    assert not core_manifest.exists()


def test_profile_authenticated_registry_rejects_untrusted_signature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    profile = make_test_verified_profile()
    monkeypatch.setattr(
        app_factory,
        "load_installed_update_trust_profile",
        lambda root: profile,
    )
    gateway = StaticReleaseGateway(error=GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED"))

    service = app_factory.compose_update_check_service(
        config,
        root_dir=tmp_path,
        identity_reader=FakeIdentityReader(make_test_local_identity(), trust_profile=profile),
    )
    assert service._release_gateway._channel_profile == UpdateChannelProfile.from_verified(profile)

    service._release_gateway = gateway
    result = service.check_manual()

    assert result.state == UpdateState.VERIFY_FAILED
    assert result.diagnostic_code == UpdateDiagnosticCode.MANIFEST_REJECTED


def test_missing_installed_profile_disables_production_composition_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)

    service = app_factory.compose_update_check_service(config, root_dir=tmp_path)
    result = service.check_manual()

    assert result.state == UpdateState.UNAVAILABLE
    assert service._release_gateway.__class__.__name__ == "_UnavailableReleaseGateway"
    assert not hasattr(service._release_gateway, "_key_registry")


def test_production_compose_update_apply_service_does_not_wire_network_resolver_or_downloader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = make_test_verified_profile()
    monkeypatch.setattr(
        app_factory,
        "load_installed_update_trust_profile",
        lambda root: profile,
    )

    compose_update_apply_service = getattr(
        app_factory, "compose_update_apply_service", None
    )
    if compose_update_apply_service is None:
        pytest.fail("compose_update_apply_service not implemented", pytrace=False)

    config = make_config(monkeypatch, tmp_path)
    service = compose_update_apply_service(config, root_dir=tmp_path)

    resolver = getattr(service, "release_gateway", getattr(service, "_release_gateway", None))
    assert resolver is None

    downloader = getattr(service, "asset_downloader", getattr(service, "_asset_downloader", None))
    assert downloader is None

    # No separate key registry or grant gateway or capability provider on apply service
    assert not hasattr(service, "grant_gateway")
    assert not hasattr(service, "distribution_capability_provider")


def test_build_window_wires_coordinator_with_admission_and_apply_service_without_network_dependencies(
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
    profile = make_test_verified_profile()
    monkeypatch.setattr(
        app_factory,
        "load_installed_update_trust_profile",
        lambda root: profile,
    )
    monkeypatch.setattr(
        app_factory,
        "AuthenticatedReleaseIdentityReader",
        lambda prof: FakeIdentityReader(make_test_local_identity(), trust_profile=prof),
    )

    window = app_factory.build_window(tmp_path)

    assert isinstance(window, CapturingWindow)
    check_service = captured["window_kwargs"]["update_check_service"]
    apply_service = captured["window_kwargs"]["update_apply_service"]

    assert not hasattr(apply_service, "release_gateway")
    assert not hasattr(apply_service, "asset_downloader")

    assert "update_coordinator" in captured["window_kwargs"]
    coordinator = captured["window_kwargs"]["update_coordinator"]
    assert coordinator is not None
    assert coordinator._pending_store is coordinator._stage_service._pending_store
    assert coordinator._check_service is check_service
    assert hasattr(coordinator, "_admission_service")
    assert coordinator._admission_service is not None
    if SoftwareUpdateAuthorityAdmissionService is not None:
        assert isinstance(coordinator._admission_service, SoftwareUpdateAuthorityAdmissionService)



def test_production_update_configuration_contains_no_private_key_material(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = make_config(monkeypatch, tmp_path)
    profile = make_test_verified_profile()
    monkeypatch.setattr(
        app_factory,
        "load_installed_update_trust_profile",
        lambda root: profile,
    )
    service = app_factory.compose_update_check_service(
        config,
        root_dir=tmp_path,
        identity_reader=FakeIdentityReader(make_test_local_identity(), trust_profile=profile),
    )

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
