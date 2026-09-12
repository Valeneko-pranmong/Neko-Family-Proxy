from __future__ import annotations

import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from typing import get_type_hints

import pytest

from neko_launcher.application.software_update_models import (
    ComponentRelease,
    LocalReleaseIdentity,
    ReleaseSet,
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.infrastructure.github_release import (
    GitHubRelease,
    GitHubReleaseAsset,
)
from neko_launcher.infrastructure.github_release_binding import (
    AuthenticatedReleaseGateway,
    ResolvedGitHubRelease,
)

TARGET_MODULE = "neko_launcher.application.software_update_service"


class CodedError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class ExplodingCodeError(Exception):
    @property
    def code(self) -> str:
        raise RuntimeError("sentinel-code-property")


class CountingReleaseGateway:
    def __init__(
        self,
        resolved: ResolvedGitHubRelease | None = None,
        error: Exception | None = None,
        *,
        blocking: bool = False,
    ) -> None:
        self.resolved = resolved
        self.error = error
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.blocking = blocking
        self._lock = threading.Lock()

    def resolve(self) -> ResolvedGitHubRelease | None:
        with self._lock:
            self.calls += 1
        self.entered.set()
        if self.blocking and not self.release.wait(timeout=2):
            raise TimeoutError("test gateway was not released")
        if self.error is not None:
            raise self.error
        return self.resolved


class LocalProvider:
    def __init__(
        self,
        identity: LocalReleaseIdentity | None = None,
        error: Exception | None = None,
    ) -> None:
        self.identity = identity
        self.error = error
        self.calls = 0

    def __call__(self) -> LocalReleaseIdentity:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.identity is None:
            raise AssertionError("local provider has no configured identity")
        return self.identity


def service_type() -> type:
    try:
        from neko_launcher.application.software_update_service import (
            UpdateCheckService,
        )
    except ModuleNotFoundError as exc:
        if exc.name == TARGET_MODULE:
            pytest.fail(
                "software update service module is missing",
                pytrace=False,
            )
        raise
    return UpdateCheckService


def remote_release(sequence: int) -> ReleaseSet:
    return ReleaseSet(
        schema_version=1,
        channel="stable",
        release_sequence=sequence,
        release_id=f"release-{sequence}",
        mandatory=False,
        minimum_supported_sequence=1,
        components=(
            ComponentRelease(
                "launcher",
                "2.0.0",
                "NekoLauncher.exe",
                "a" * 64,
                100,
                "b" * 64,
            ),
            ComponentRelease(
                "core",
                "2.0.0",
                "NekoProxyCore.zip",
                "c" * 64,
                100,
                "d" * 64,
            ),
        ),
    )


def make_resolved_release(sequence: int) -> ResolvedGitHubRelease:
    rel = remote_release(sequence)
    manifest_asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=100,
        browser_download_url="https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v2.0.0/release-v2.json",
    )
    launcher_asset = GitHubReleaseAsset(
        id=2,
        name="NekoLauncher.exe",
        size=100,
        browser_download_url="https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v2.0.0/NekoLauncher.exe",
    )
    updater_asset = GitHubReleaseAsset(
        id=3,
        name="NekoUpdater.exe",
        size=100,
        browser_download_url="https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v2.0.0/NekoUpdater.exe",
    )
    core_asset = GitHubReleaseAsset(
        id=4,
        name="NekoProxyCore.zip",
        size=100,
        browser_download_url="https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v2.0.0/NekoProxyCore.zip",
    )
    gh_release = GitHubRelease(
        id=1000,
        tag_name="v2.0.0",
        draft=False,
        prerelease=False,
        assets=(manifest_asset, launcher_asset, updater_asset, core_asset),
    )
    return ResolvedGitHubRelease(
        authenticated_release=rel,
        authenticated_release_v2=None,  # type: ignore[arg-type]
        envelope_bytes=b'{"payload":"test"}',
        envelope_document={"payload": "test"},
        github_release=gh_release,
        manifest_asset=manifest_asset,
        launcher_asset=launcher_asset,
        updater_asset=updater_asset,
        core_asset=core_asset,
    )


def local_release(
    sequence: int,
    *,
    launcher_identity: str = "e" * 64,
    core_identity: str = "d" * 64,
) -> LocalReleaseIdentity:
    return LocalReleaseIdentity(
        release_sequence=sequence,
        release_id=f"local-{sequence}",
        launcher_version="1.0.0",
        launcher_installed_identity_sha256=launcher_identity,
        core_version="1.0.0",
        core_installed_identity_sha256=core_identity,
    )


def make_service(
    gateway: CountingReleaseGateway,
    provider: LocalProvider,
):
    return service_type()(gateway, provider)


def wait_for_startup_waiter(service: object) -> None:
    condition = service._startup_condition
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        with condition:
            if len(condition._waiters) >= 1:
                return
        time.sleep(0.001)
    pytest.fail("second startup caller never entered the condition waiter path")


def assert_safe_empty_metadata(result: UpdateCheckResult) -> None:
    assert result.release_id is None
    assert result.release_sequence is None
    assert result.changed_components == ()
    assert result.launcher_version is None
    assert result.core_version is None
    assert result.mandatory is False


def assert_secret_absent(result: UpdateCheckResult, secret: str) -> None:
    assert secret not in str(result)
    assert secret not in repr(result)
    for field in fields(UpdateCheckResult):
        value = getattr(result, field.name)
        assert secret not in str(value)
        assert secret not in repr(value)


def test_authenticated_release_gateway_contract() -> None:
    signature = inspect.signature(AuthenticatedReleaseGateway.resolve)
    assert tuple(signature.parameters) == ("self",)
    hints = get_type_hints(AuthenticatedReleaseGateway.resolve)
    assert hints["return"] == ResolvedGitHubRelease | None


def test_required_diagnostic_codes_have_exact_values() -> None:
    assert (
        UpdateDiagnosticCode.MANIFEST_UNAVAILABLE.value
        == "MANIFEST_UNAVAILABLE"
    )
    assert (
        UpdateDiagnosticCode.MANIFEST_REJECTED.value
        == "MANIFEST_REJECTED"
    )
    assert (
        UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE.value
        == "UPDATE_CHECK_INTERNAL_FAILURE"
    )
    assert UpdateDiagnosticCode.DOWNGRADE_REJECTED.value == "DOWNGRADE_REJECTED"
    assert (
        UpdateDiagnosticCode.UPDATER_INCOMPATIBLE.value
        == "UPDATER_INCOMPATIBLE"
    )
    assert (
        UpdateDiagnosticCode.GITHUB_RELEASE_UNAVAILABLE.value
        == "GITHUB_RELEASE_UNAVAILABLE"
    )


def test_service_public_method_contract() -> None:
    service_class = service_type()
    assert tuple(inspect.signature(service_class).parameters) == (
        "release_gateway",
        "local_identity_provider",
    )
    assert tuple(inspect.signature(service_class.check_startup).parameters) == (
        "self",
    )
    assert tuple(inspect.signature(service_class.check_manual).parameters) == (
        "self",
    )
    assert UpdateInvocationReason.STARTUP is not UpdateInvocationReason.MANUAL


def test_sequential_startup_checks_share_cached_result() -> None:
    resolved = make_resolved_release(2)
    gateway = CountingReleaseGateway(resolved)
    provider = LocalProvider(local_release(1))
    service = make_service(gateway, provider)

    first = service.check_startup()
    second = service.check_startup()

    assert gateway.calls == 1
    assert first is second


def test_concurrent_startup_checks_are_single_flight() -> None:
    resolved = make_resolved_release(2)
    gateway = CountingReleaseGateway(resolved, blocking=True)
    service = make_service(
        gateway,
        LocalProvider(local_release(1)),
    )
    second_started = threading.Event()

    def second_call() -> UpdateCheckResult:
        second_started.set()
        return service.check_startup()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(service.check_startup)
        assert gateway.entered.wait(timeout=1)
        second_future = executor.submit(second_call)
        assert second_started.wait(timeout=1)
        wait_for_startup_waiter(service)
        gateway.release.set()
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert gateway.calls == 1
    assert first is second


def test_manual_checks_always_fetch_and_do_not_reset_startup_cache() -> None:
    resolved = make_resolved_release(2)
    gateway = CountingReleaseGateway(resolved)
    service = make_service(
        gateway,
        LocalProvider(local_release(1)),
    )

    startup_before = service.check_startup()
    first_manual = service.check_manual()
    second_manual = service.check_manual()
    startup_after = service.check_startup()

    assert gateway.calls == 3
    assert startup_before is startup_after
    assert first_manual is not second_manual


def test_missing_manifest_is_unavailable_without_verification() -> None:
    gateway = CountingReleaseGateway(None)
    provider = LocalProvider(error=AssertionError("must not be called"))
    result = make_service(gateway, provider).check_manual()

    assert result.state is UpdateState.UNAVAILABLE
    assert result.diagnostic_code is None
    assert_safe_empty_metadata(result)
    assert provider.calls == 0


@pytest.mark.parametrize(
    "code",
    ("MANIFEST_UNAVAILABLE", "GITHUB_RELEASE_UNAVAILABLE"),
)
def test_coded_manifest_unavailable_maps_to_unavailable(code: str) -> None:
    gateway = CountingReleaseGateway(
        error=CodedError(code, "unsafe detail"),
    )
    result = make_service(
        gateway,
        LocalProvider(error=AssertionError("must not be called")),
    ).check_manual()

    assert result.state is UpdateState.UNAVAILABLE
    assert result.diagnostic_code in (
        UpdateDiagnosticCode.MANIFEST_UNAVAILABLE,
        UpdateDiagnosticCode.GITHUB_RELEASE_UNAVAILABLE,
    )
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, "unsafe detail")


@pytest.mark.parametrize(
    "code",
    ("MANIFEST_RESPONSE_INVALID", "RELEASE_MANIFEST_REJECTED", "SIGNATURE_INVALID"),
)
def test_rejected_manifest_codes_map_to_manifest_rejected(code: str) -> None:
    error = CodedError(code, "unsafe rejected detail")
    gateway = CountingReleaseGateway(error=error)
    result = make_service(
        gateway,
        LocalProvider(local_release(1)),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.MANIFEST_REJECTED
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, "unsafe rejected detail")


def test_updater_incompatible_maps_to_updater_incompatible() -> None:
    error = CodedError("UPDATER_INCOMPATIBLE", "unsafe updater detail")
    gateway = CountingReleaseGateway(error=error)
    result = make_service(
        gateway,
        LocalProvider(local_release(1)),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.UPDATER_INCOMPATIBLE
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, "unsafe updater detail")


def test_available_launcher_only_update_has_safe_release_metadata() -> None:
    resolved = make_resolved_release(2)
    result = make_service(
        CountingReleaseGateway(resolved),
        LocalProvider(
            local_release(
                1,
                launcher_identity="e" * 64,
                core_identity="d" * 64,
            )
        ),
    ).check_manual()

    assert result.state is UpdateState.AVAILABLE
    assert result.diagnostic_code is None
    assert result.release_id == "release-2"
    assert result.release_sequence == 2
    assert result.changed_components == ("launcher",)
    assert result.launcher_version == "2.0.0"
    assert result.core_version == "2.0.0"
    assert result.mandatory is False


def test_downgrade_is_rejected_by_real_policy() -> None:
    resolved = make_resolved_release(1)
    result = make_service(
        CountingReleaseGateway(resolved),
        LocalProvider(local_release(2)),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.DOWNGRADE_REJECTED


def test_local_identity_failure_is_sanitized_before_metadata_exists() -> None:
    secret = "sentinel-local-identity-detail"
    resolved = make_resolved_release(2)
    result = make_service(
        CountingReleaseGateway(resolved),
        LocalProvider(error=ValueError(secret)),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert (
        result.diagnostic_code
        is UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    )
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, secret)


def test_concurrent_startup_internal_failure_is_cached_and_sanitized() -> None:
    secret = "sentinel-internal-detail"
    gateway = CountingReleaseGateway(
        error=RuntimeError(secret),
        blocking=True,
    )
    service = make_service(
        gateway,
        LocalProvider(error=AssertionError("must not be called")),
    )
    second_started = threading.Event()

    def second_call() -> UpdateCheckResult:
        second_started.set()
        return service.check_startup()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(service.check_startup)
        assert gateway.entered.wait(timeout=1)
        second_future = executor.submit(second_call)
        assert second_started.wait(timeout=1)
        wait_for_startup_waiter(service)
        gateway.release.set()
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert gateway.calls == 1
    assert first is second
    assert first.state is UpdateState.VERIFY_FAILED
    assert (
        first.diagnostic_code
        is UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    )
    assert_safe_empty_metadata(first)
    assert_secret_absent(first, secret)


def test_unknown_coded_exception_is_internal_failure() -> None:
    secret = "sentinel-unknown-code"
    result = make_service(
        CountingReleaseGateway(
            error=CodedError("NEW_UNTRUSTED_CODE", secret),
        ),
        LocalProvider(error=AssertionError("must not be called")),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert (
        result.diagnostic_code
        is UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    )
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, secret)


def test_gateway_runtime_error_does_not_leak_raw_document() -> None:
    secret = "sentinel-raw-manifest-document"
    result = make_service(
        CountingReleaseGateway(error=RuntimeError(secret)),
        LocalProvider(error=AssertionError("must not be called")),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert (
        result.diagnostic_code
        is UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    )
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, secret)


def test_exception_code_accessor_failure_cannot_strand_startup_waiters() -> None:
    gateway = CountingReleaseGateway(
        error=ExplodingCodeError("safe outer message"),
        blocking=True,
    )
    service = make_service(
        gateway,
        LocalProvider(error=AssertionError("must not be called")),
    )
    executor = ThreadPoolExecutor(max_workers=2)
    first_future = executor.submit(service.check_startup)
    assert gateway.entered.wait(timeout=1)
    second_future = executor.submit(service.check_startup)
    wait_for_startup_waiter(service)
    gateway.release.set()

    try:
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)
    finally:
        condition = service._startup_condition
        with condition:
            service._startup_checking = False
            condition.notify_all()
        executor.shutdown(wait=False, cancel_futures=True)

    assert first is second
    assert first.state is UpdateState.VERIFY_FAILED
    assert (
        first.diagnostic_code
        is UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    )
    assert_safe_empty_metadata(first)
    assert_secret_absent(first, "sentinel-code-property")


def test_check_startup_with_resolved_returns_result_and_resolved() -> None:
    resolved = make_resolved_release(2)
    gateway = CountingReleaseGateway(resolved)
    provider = LocalProvider(local_release(1))
    service = make_service(gateway, provider)

    result, res = service.check_startup_with_resolved()
    assert result.state is UpdateState.AVAILABLE
    assert res is resolved

    # Cached on subsequent call
    result2, res2 = service.check_startup_with_resolved()
    assert gateway.calls == 1
    assert result2 is result
    assert res2 is res


def test_check_manual_with_resolved_returns_result_and_resolved() -> None:
    resolved = make_resolved_release(2)
    gateway = CountingReleaseGateway(resolved)
    provider = LocalProvider(local_release(1))
    service = make_service(gateway, provider)

    result, res = service.check_manual_with_resolved()
    assert result.state is UpdateState.AVAILABLE
    assert res is resolved
    assert gateway.calls == 1


def test_check_with_resolved_error_returns_none_for_resolved() -> None:
    gateway = CountingReleaseGateway(error=CodedError("MANIFEST_UNAVAILABLE", "offline"))
    provider = LocalProvider(local_release(1))
    service = make_service(gateway, provider)

    result, res = service.check_startup_with_resolved()
    assert result.state is UpdateState.UNAVAILABLE
    assert res is None
