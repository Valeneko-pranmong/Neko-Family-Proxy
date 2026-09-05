from __future__ import annotations

import inspect
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from typing import get_type_hints

import pytest

from neko_launcher.application import ports
from neko_launcher.application.software_update_models import (
    ComponentRelease,
    LocalReleaseIdentity,
    ReleaseSet,
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
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


class CountingGateway:
    def __init__(
        self,
        document: object | None = None,
        error: Exception | None = None,
        *,
        blocking: bool = False,
    ) -> None:
        self.document = document
        self.error = error
        self.calls = 0
        self.channels: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.blocking = blocking
        self._lock = threading.Lock()

    def fetch(self, channel: str = "beta") -> object | None:
        with self._lock:
            self.calls += 1
            self.channels.append(channel)
        self.entered.set()
        if self.blocking and not self.release.wait(timeout=2):
            raise TimeoutError("test gateway was not released")
        if self.error is not None:
            raise self.error
        return self.document


class CountingVerifier:
    def __init__(
        self,
        release: ReleaseSet | None = None,
        error: Exception | None = None,
    ) -> None:
        self.release = release
        self.error = error
        self.calls = 0
        self.documents: list[object] = []

    def verify(self, document: object) -> ReleaseSet:
        self.calls += 1
        self.documents.append(document)
        if self.error is not None:
            raise self.error
        if self.release is None:
            raise AssertionError("verifier has no configured release")
        return self.release


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
        channel="beta",
        release_sequence=sequence,
        release_id=f"release-{sequence}",
        mandatory=False,
        minimum_supported_sequence=1,
        components=(
            ComponentRelease(
                "launcher",
                "2.0.0",
                "launcher-artifact",
                "a" * 64,
                100,
                "b" * 64,
            ),
            ComponentRelease(
                "core",
                "2.0.0",
                "core-artifact",
                "c" * 64,
                100,
                "d" * 64,
            ),
        ),
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
    gateway: CountingGateway,
    verifier: CountingVerifier,
    provider: LocalProvider,
):
    return service_type()(gateway, verifier, provider)


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


def test_update_manifest_gateway_contract() -> None:
    signature = inspect.signature(ports.UpdateManifestGateway.fetch)
    assert tuple(signature.parameters) == ("self", "channel")
    assert signature.parameters["channel"].default == "beta"

    hints = get_type_hints(ports.UpdateManifestGateway.fetch)
    assert hints["channel"] is str
    assert hints["return"] == object | None


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


def test_service_public_method_contract() -> None:
    service_class = service_type()
    assert tuple(inspect.signature(service_class).parameters) == (
        "manifest_gateway",
        "verifier",
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
    release = remote_release(2)
    gateway = CountingGateway(release)
    verifier = CountingVerifier(release)
    provider = LocalProvider(local_release(1))
    service = make_service(gateway, verifier, provider)

    first = service.check_startup()
    second = service.check_startup()

    assert gateway.calls == 1
    assert first is second


def test_concurrent_startup_checks_are_single_flight() -> None:
    release = remote_release(2)
    gateway = CountingGateway(release, blocking=True)
    service = make_service(
        gateway,
        CountingVerifier(release),
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
    release = remote_release(2)
    gateway = CountingGateway(release)
    service = make_service(
        gateway,
        CountingVerifier(release),
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
    gateway = CountingGateway(None)
    verifier = CountingVerifier(error=AssertionError("must not be called"))
    provider = LocalProvider(error=AssertionError("must not be called"))
    result = make_service(gateway, verifier, provider).check_manual()

    assert result.state is UpdateState.UNAVAILABLE
    assert result.diagnostic_code is None
    assert_safe_empty_metadata(result)
    assert verifier.calls == 0
    assert provider.calls == 0


def test_coded_manifest_unavailable_maps_to_unavailable() -> None:
    gateway = CountingGateway(
        error=CodedError("MANIFEST_UNAVAILABLE", "unsafe detail"),
    )
    result = make_service(
        gateway,
        CountingVerifier(error=AssertionError("must not be called")),
        LocalProvider(error=AssertionError("must not be called")),
    ).check_manual()

    assert result.state is UpdateState.UNAVAILABLE
    assert result.diagnostic_code is UpdateDiagnosticCode.MANIFEST_UNAVAILABLE
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, "unsafe detail")


@pytest.mark.parametrize(
    ("source", "code"),
    (
        ("gateway", "MANIFEST_RESPONSE_INVALID"),
        ("verifier", "SIGNATURE_INVALID"),
    ),
)
def test_rejected_manifest_codes_map_to_manifest_rejected(
    source: str,
    code: str,
) -> None:
    release = remote_release(2)
    error = CodedError(code, "unsafe rejected detail")
    gateway = CountingGateway(
        release,
        error=error if source == "gateway" else None,
    )
    verifier = CountingVerifier(
        release,
        error=error if source == "verifier" else None,
    )
    result = make_service(
        gateway,
        verifier,
        LocalProvider(local_release(1)),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.MANIFEST_REJECTED
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, "unsafe rejected detail")


def test_available_launcher_only_update_has_safe_release_metadata() -> None:
    release = remote_release(2)
    result = make_service(
        CountingGateway(release),
        CountingVerifier(release),
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
    release = remote_release(1)
    result = make_service(
        CountingGateway(release),
        CountingVerifier(release),
        LocalProvider(local_release(2)),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.DOWNGRADE_REJECTED


def test_local_identity_failure_is_sanitized_before_metadata_exists() -> None:
    secret = "sentinel-local-identity-detail"
    release = remote_release(2)
    result = make_service(
        CountingGateway(release),
        CountingVerifier(release),
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
    gateway = CountingGateway(
        error=RuntimeError(secret),
        blocking=True,
    )
    service = make_service(
        gateway,
        CountingVerifier(error=AssertionError("must not be called")),
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
        CountingGateway(
            error=CodedError("NEW_UNTRUSTED_CODE", secret),
        ),
        CountingVerifier(error=AssertionError("must not be called")),
        LocalProvider(error=AssertionError("must not be called")),
    ).check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert (
        result.diagnostic_code
        is UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    )
    assert_safe_empty_metadata(result)
    assert_secret_absent(result, secret)


def test_verifier_runtime_error_does_not_leak_raw_document() -> None:
    secret = "sentinel-raw-manifest-document"
    document = {"payload": secret}
    result = make_service(
        CountingGateway(document),
        CountingVerifier(error=RuntimeError(repr(document))),
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
    gateway = CountingGateway(
        error=ExplodingCodeError("safe outer message"),
        blocking=True,
    )
    service = make_service(
        gateway,
        CountingVerifier(error=AssertionError("must not be called")),
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
        # Recover a broken pre-fix implementation so the regression test itself
        # cannot leave a worker blocked forever during RED verification.
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
