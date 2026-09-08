from __future__ import annotations

import inspect
import importlib
import io
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from neko_launcher.application.software_update_models import (
    LocalReleaseIdentity,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.application.software_update_policy import evaluate_release
from neko_launcher.application.software_update_service import UpdateCheckService
from neko_launcher.infrastructure.diagnostics_logger import DevelopmentLogger
from neko_launcher.infrastructure.software_update_apply import (
    SoftwareUpdateApplyError,
    SoftwareUpdateApplyService,
)
from neko_launcher.infrastructure.software_update_manifest import ReleaseManifestVerifier
try:
    from tests.software_update_helpers import (
        get_test_key_registry,
        signed_envelope,
        valid_release_document,
    )
except ImportError:
    from software_update_helpers import (  # type: ignore[no-redef]
        get_test_key_registry,
        signed_envelope,
        valid_release_document,
    )

PROXY_CREDENTIAL = "SENTINEL_PROXY_CREDENTIAL_42"
JWT_TOKEN = "eyJaaaaaa.bbbbbbb.ccccccc"
SIGNED_URL_TOKEN = "SENTINEL_SIGNED_URL_TOKEN_42"
SIGNED_URL = (
    "https://objects.example.invalid/a"
    f"?token={SIGNED_URL_TOKEN}&signature=abc"
)
BASE_URL = "https://updates.example.invalid"


def assert_secrets_absent(text: str, *secrets: str) -> None:
    for secret in secrets:
        assert secret not in text


def test_support_log_sanitizes_exception_secrets(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logger = DevelopmentLogger(logs_dir)
    message = (
        f"proxy failed credential={PROXY_CREDENTIAL}; "
        f"permit={JWT_TOKEN}; signed_url={SIGNED_URL}"
    )

    logger.record_exception(ValueError(message), stage="software-update")

    log_files = list(logs_dir.glob("*.log"))
    support_log = logs_dir / "support.log"
    timestamped_logs = [path for path in log_files if path != support_log]

    assert support_log.is_file()
    assert timestamped_logs

    for log_file in [support_log, *timestamped_logs]:
        contents = log_file.read_text(encoding="utf-8")
        assert_secrets_absent(
            contents,
            PROXY_CREDENTIAL,
            JWT_TOKEN,
            SIGNED_URL_TOKEN,
            SIGNED_URL,
        )
        assert "redact" in contents.lower()


RAW_PAYLOAD_SENTINEL = "SENTINEL_RAW_PAYLOAD_42"
SIGNATURE_SENTINEL = "SENTINEL_SIGNATURE_42"
PERMIT_SENTINEL = "SENTINEL_PERMIT_42"
RUNTIME_CONFIG_SENTINEL = "SENTINEL_RUNTIME_CONFIG_42"
TEST_PRIVATE_SEED_TEXT = "test-only-deterministic-key-0000"


class SecretFailingReleaseGateway:
    def resolve(self) -> Any:
        raise RuntimeError(
            " ".join(
                (
                    RAW_PAYLOAD_SENTINEL,
                    SIGNATURE_SENTINEL,
                    SIGNED_URL,
                    JWT_TOKEN,
                    PERMIT_SENTINEL,
                    RUNTIME_CONFIG_SENTINEL,
                    PROXY_CREDENTIAL,
                )
            )
        )


def _local_identity(sequence: int = 3) -> LocalReleaseIdentity:
    return LocalReleaseIdentity(
        release_sequence=sequence,
        release_id=f"release-{sequence}",
        launcher_version="5.1.0a1",
        launcher_installed_identity_sha256="1" * 64,
        core_version="5.0.0",
        core_installed_identity_sha256="2" * 64,
    )


def test_distributable_source_contains_no_ed25519_private_key_material() -> None:
    package_root = Path(__file__).resolve().parents[1] / "src" / "neko_launcher"
    production_source = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in sorted(package_root.rglob("*.py"))
    )

    forbidden_patterns = (
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN ED25519 PRIVATE KEY-----",
        "Ed25519PrivateKey",
        ".from_private_bytes(",
        TEST_PRIVATE_SEED_TEXT,
    )
    for pattern in forbidden_patterns:
        assert pattern not in production_source


def test_test_private_key_material_is_not_importable_from_production_package() -> None:
    package = importlib.import_module("neko_launcher")
    verifier_module = importlib.import_module(
        "neko_launcher.infrastructure.software_update_manifest"
    )

    for module in (package, verifier_module):
        assert not hasattr(module, "TEST_PRIVATE_SEED")
        assert not hasattr(module, "TEST_PRIVATE_KEY")
        assert not hasattr(module, "Ed25519PrivateKey")


def test_service_result_and_support_log_omit_update_secret_sentinels(
    tmp_path: Path,
) -> None:
    service = UpdateCheckService(
        SecretFailingReleaseGateway(),
        lambda: _local_identity(),
    )

    result = service.check_manual()

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE
    forbidden = (
        RAW_PAYLOAD_SENTINEL,
        SIGNATURE_SENTINEL,
        SIGNED_URL,
        SIGNED_URL_TOKEN,
        JWT_TOKEN,
        PERMIT_SENTINEL,
        RUNTIME_CONFIG_SENTINEL,
        PROXY_CREDENTIAL,
    )
    assert_secrets_absent(repr(result), *forbidden)

    logger = DevelopmentLogger(tmp_path / "logs")
    logger.record_stage(
        "SOFTWARE_UPDATE_CHECK",
        state=result.state.value,
        release_sequence=result.release_sequence,
        changed_components=",".join(result.changed_components),
        diagnostic_code=result.diagnostic_code.value,
    )
    for log_file in (tmp_path / "logs").glob("*.log"):
        assert_secrets_absent(log_file.read_text(encoding="utf-8"), *forbidden)


def test_unknown_update_signing_key_is_rejected_without_echoing_key_id() -> None:
    envelope = signed_envelope(valid_release_document())
    unknown_key_id = "SENTINEL_UNKNOWN_KEY_42"
    envelope["key_id"] = unknown_key_id
    verifier = ReleaseManifestVerifier(get_test_key_registry())

    with pytest.raises(ValueError) as caught:
        verifier.verify(envelope)

    assert type(caught.value).__name__ == "ManifestVerificationError"
    assert caught.value.code == "UNKNOWN_KEY_ID"
    assert str(caught.value) == "UNKNOWN_KEY_ID"
    assert unknown_key_id not in repr(caught.value)


def test_apply_service_has_no_capability_seam_and_sanitizes_resolver_failure(
    tmp_path: Path,
) -> None:
    sig = inspect.signature(SoftwareUpdateApplyService.__init__)
    params = set(sig.parameters)
    assert "distribution_capability_provider" not in params
    assert "grant_gateway" not in params
    assert "manifest_gateway" not in params

    service = SoftwareUpdateApplyService(
        root_dir=tmp_path,
        release_gateway=SecretFailingReleaseGateway(),
        asset_downloader=None,  # type: ignore[arg-type]
    )

    with pytest.raises(SoftwareUpdateApplyError) as caught:
        service.prepare()

    error = caught.value
    assert error.code == "MANIFEST_VERIFY_FAILED"
    assert str(error) == "MANIFEST_VERIFY_FAILED"

    forbidden = (
        RAW_PAYLOAD_SENTINEL,
        SIGNATURE_SENTINEL,
        SIGNED_URL,
        SIGNED_URL_TOKEN,
        JWT_TOKEN,
        PERMIT_SENTINEL,
        RUNTIME_CONFIG_SENTINEL,
        PROXY_CREDENTIAL,
    )
    assert_secrets_absent(str(error), *forbidden)
    assert_secrets_absent(repr(error), *forbidden)
    assert_secrets_absent(repr(service), *forbidden)

    logger = DevelopmentLogger(tmp_path / "logs")
    logger.record_exception(error, stage="software-update-apply")
    for log_file in (tmp_path / "logs").glob("*.log"):
        assert_secrets_absent(log_file.read_text(encoding="utf-8"), *forbidden)


def test_apply_service_sanitizes_download_failure(tmp_path: Path) -> None:
    try:
        from tests.test_software_update_apply import (
            FakeChannel,
            FakeReleaseGateway,
            FakeSpawner,
            make_resolved_release,
        )
    except ImportError:
        from test_software_update_apply import (  # type: ignore[no-redef]
            FakeChannel,
            FakeReleaseGateway,
            FakeSpawner,
            make_resolved_release,
        )

    class SecretFailingDownloader:
        def download(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(
                f"leaked secret={SIGNED_URL_TOKEN} cdn={CDN_QUERY_TOKEN_TASK3} auth={PROXY_CREDENTIAL}"
            )

    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = SecretFailingDownloader()
    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": "req-privacy-dl",
                    "transaction_id": "tx-privacy-dl",
                    "changed": {"launcher": True, "core": True},
                    "error": None,
                },
            }
        ]
    )

    service = SoftwareUpdateApplyService(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,  # type: ignore[arg-type]
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    with pytest.raises(SoftwareUpdateApplyError) as exc_info:
        service.prepare()

    error = exc_info.value
    assert error.code == "DOWNLOAD_FAILED"
    assert str(error) == "DOWNLOAD_FAILED"

    forbidden = (
        SIGNED_URL_TOKEN,
        CDN_QUERY_TOKEN_TASK3,
        PROXY_CREDENTIAL,
    )
    assert_secrets_absent(str(error), *forbidden)
    assert_secrets_absent(repr(error), *forbidden)
    assert_secrets_absent(repr(service), *forbidden)

    logger = DevelopmentLogger(tmp_path / "logs")
    logger.record_exception(error, stage="software-update-apply")
    for log_file in (tmp_path / "logs").glob("*.log"):
        assert_secrets_absent(log_file.read_text(encoding="utf-8"), *forbidden)


def test_downgrade_policy_rejects_remote_release_without_secret_fields() -> None:
    remote_document = valid_release_document()
    remote_document["release_sequence"] = 2
    remote_document["release_id"] = "release-2"
    remote_document["minimum_supported_sequence"] = 1
    verifier = ReleaseManifestVerifier(get_test_key_registry())
    remote = verifier.verify(signed_envelope(remote_document))

    result = evaluate_release(
        _local_identity(sequence=3),
        remote,
        UpdateInvocationReason.MANUAL,
    )

    assert result.state is UpdateState.VERIFY_FAILED
    assert result.diagnostic_code is UpdateDiagnosticCode.DOWNGRADE_REJECTED
    assert result.changed_components == ()
    assert result.mandatory is False


CDN_QUERY_TOKEN_TASK3 = "SENTINEL_CDN_QUERY_TOKEN_TASK3_42"
CDN_SIG_TOKEN_TASK3 = "SENTINEL_CDN_SIG_TOKEN_TASK3_42"
CDN_COOKIE_TOKEN_TASK3 = "SENTINEL_CDN_COOKIE_TOKEN_TASK3_42"
QUERY_BEARING_CDN_URL = (
    "https://objects.githubusercontent.com/storage/v1/release-asset"
    f"?token={CDN_QUERY_TOKEN_TASK3}&signature={CDN_SIG_TOKEN_TASK3}"
)


class _PrivacyFakeResponse:
    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        headers: dict[str, Any] | None = None,
    ) -> None:
        self.stream = io.BytesIO(body)
        self.status = status
        self.code = status
        self._headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def getcode(self) -> int:
        return self.status

    def info(self) -> Any:
        return self

    @property
    def headers(self) -> Any:
        return self

    def get(self, name: str, default: Any = None) -> Any:
        for k, v in self._headers.items():
            if k.lower() == name.lower():
                return v
        return default

    def get_all(self, name: str, default: Any = None) -> Any:
        matches = [v for k, v in self._headers.items() if k.lower() == name.lower()]
        if not matches:
            return default
        results: list[Any] = []
        for match in matches:
            if isinstance(match, (list, tuple)):
                results.extend(match)
            else:
                results.append(match)
        return results

    def __enter__(self) -> _PrivacyFakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def close(self) -> None:
        pass


def _downloader_module() -> Any:
    try:
        return importlib.import_module("neko_launcher.infrastructure.github_asset_downloader")
    except ModuleNotFoundError:
        return None


def test_github_manifest_downloader_privacy_omits_secrets_in_errors_and_repr(
    tmp_path: Path,
) -> None:
    module = _downloader_module()
    assert module is not None, "Task 3 production module must exist"
    from neko_launcher.infrastructure.github_release import GitHubReleaseAsset

    initial_url = (
        "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/"
        "v5.1.0/release-v2.json"
    )
    routes = {
        initial_url: _PrivacyFakeResponse(
            status=302,
            headers={"Location": QUERY_BEARING_CDN_URL},
        ),
        QUERY_BEARING_CDN_URL: urllib.error.URLError(
            f"network error with secret={CDN_QUERY_TOKEN_TASK3}"
        ),
    }

    class FakeRouteOpener:
        def open(self, request: Any, timeout: float = 15.0) -> Any:
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            res = routes.get(url)
            if isinstance(res, BaseException):
                raise res
            return res

    downloader = module.GitHubManifestDownloader(_opener=FakeRouteOpener())
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=100,
        browser_download_url=initial_url,
    )

    with pytest.raises(module.GitHubAssetDownloadError) as caught:
        downloader.download(asset)

    error = caught.value
    assert error.code == "DOWNLOAD_UNAVAILABLE"
    assert str(error) == "DOWNLOAD_UNAVAILABLE"

    forbidden = (
        CDN_QUERY_TOKEN_TASK3,
        CDN_SIG_TOKEN_TASK3,
        "token=",
        "signature=",
    )
    assert_secrets_absent(str(error), *forbidden)
    assert_secrets_absent(repr(error), *forbidden)
    assert_secrets_absent(repr(downloader), *forbidden)

    logger = DevelopmentLogger(tmp_path / "logs")
    logger.record_exception(error, stage="software-update-manifest")
    for log_file in (tmp_path / "logs").glob("*.log"):
        assert_secrets_absent(log_file.read_text(encoding="utf-8"), *forbidden)


def test_github_asset_downloader_privacy_omits_query_tokens_and_secrets(
    tmp_path: Path,
) -> None:
    module = _downloader_module()
    assert module is not None, "Task 3 production module must exist"

    initial_url = (
        "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/"
        "v5.1.0/NekoLauncher.exe"
    )
    # 302 to query-bearing CDN URL, which returns wrong hash
    routes = {
        initial_url: _PrivacyFakeResponse(
            status=302,
            headers={"Location": QUERY_BEARING_CDN_URL},
        ),
        QUERY_BEARING_CDN_URL: _PrivacyFakeResponse(
            body=b"mismatched content",
            status=200,
        ),
    }

    class FakeRouteOpener:
        def open(self, request: Any, timeout: float = 15.0) -> Any:
            del timeout
            url = request.full_url if hasattr(request, "full_url") else str(request)
            res = routes.get(url)
            if isinstance(res, BaseException):
                raise res
            return res

    downloader = module.GitHubAssetDownloader(_opener=FakeRouteOpener())
    destination = tmp_path / "NekoLauncher.exe"

    with pytest.raises(module.GitHubAssetDownloadError) as caught:
        downloader.download(
            initial_url=initial_url,
            destination=destination,
            expected_size=len(b"mismatched content"),
            expected_sha256="0" * 64,
        )

    error = caught.value
    assert error.code == "DOWNLOAD_HASH_MISMATCH"
    assert str(error) == "DOWNLOAD_HASH_MISMATCH"

    forbidden = (
        CDN_QUERY_TOKEN_TASK3,
        CDN_SIG_TOKEN_TASK3,
        "token=",
        "signature=",
    )
    assert_secrets_absent(str(error), *forbidden)
    assert_secrets_absent(repr(error), *forbidden)
    assert_secrets_absent(repr(downloader), *forbidden)

    logger = DevelopmentLogger(tmp_path / "logs")
    logger.record_exception(error, stage="software-update-artifact")
    for log_file in (tmp_path / "logs").glob("*.log"):
        assert_secrets_absent(log_file.read_text(encoding="utf-8"), *forbidden)


def test_github_downloaders_request_privacy_and_no_cookie_replay() -> None:
    module = _downloader_module()
    assert module is not None, "Task 3 production module must exist"
    from neko_launcher.infrastructure.github_release import GitHubReleaseAsset

    initial_url = (
        "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/"
        "v5.1.0/release-v2.json"
    )
    cdn_hop1 = "https://objects.githubusercontent.com/hop1"
    cdn_hop2 = "https://release-assets.githubusercontent.com/hop2"
    body = b'{"channel":"stable"}'

    captured_requests: list[Any] = []

    class MultiHopOpener:
        def open(self, request: Any, timeout: float = 15.0) -> Any:
            del timeout
            captured_requests.append(request)
            url = request.full_url
            if url == initial_url:
                return _PrivacyFakeResponse(
                    status=302,
                    headers={
                        "Location": cdn_hop1,
                        "Set-Cookie": f"auth={CDN_COOKIE_TOKEN_TASK3}; Path=/",
                    },
                )
            if url == cdn_hop1:
                return _PrivacyFakeResponse(
                    status=302,
                    headers={
                        "Location": cdn_hop2,
                        "Set-Cookie": "track=secret; Path=/",
                    },
                )
            if url == cdn_hop2:
                return _PrivacyFakeResponse(body=body, status=200)
            raise AssertionError(f"unexpected request url: {url}")

    downloader = module.GitHubManifestDownloader(_opener=MultiHopOpener())
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(body),
        browser_download_url=initial_url,
    )

    downloader.download(asset)

    assert len(captured_requests) == 3
    for req in captured_requests:
        assert req.get_header("Authorization") is None
        assert req.get_header("Cookie") is None
