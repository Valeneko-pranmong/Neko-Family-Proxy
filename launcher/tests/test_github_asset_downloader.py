from __future__ import annotations

import hashlib
import importlib
import io
import socket
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from neko_launcher.infrastructure.github_release import GitHubReleaseAsset

MODULE_NAME = "neko_launcher.infrastructure.github_asset_downloader"

INITIAL_MANIFEST_URL = (
    "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/"
    "v5.1.0/release-v2.json"
)
INITIAL_PRODUCT_URL = (
    "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/"
    "v5.1.0/NekoLauncher.exe"
)


def _module() -> Any:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError:
        return None


class FakeResponse:
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
        self.read_calls: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_calls.append(size)
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

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def close(self) -> None:
        pass


class FakeOpener:
    def __init__(
        self,
        routes: dict[str, Any] | None = None,
        default_result: Any = None,
    ) -> None:
        self.routes = routes or {}
        self.default_result = default_result
        self.requests: list[tuple[Any, float]] = []

    def open(self, request: Any, timeout: float = 15.0) -> Any:
        self.requests.append((request, timeout))
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url in self.routes:
            result = self.routes[url]
        elif self.default_result is not None:
            result = self.default_result
        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

        if isinstance(result, BaseException):
            raise result
        if callable(result):
            res = result(request)
            if isinstance(res, BaseException):
                raise res
            return res
        return result


def _error_code(callable_: Any) -> str:
    with pytest.raises(ValueError) as exc_info:
        callable_()
    return getattr(exc_info.value, "code", "")


# ---------------------------------------------------------------------------
# 1. Interface, constants, dataclasses, error hierarchy
# ---------------------------------------------------------------------------


def test_interfaces_and_constants() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    assert module.MANIFEST_MAX_BYTES == 65_536

    manifest = module.DownloadedManifest(
        exact_bytes=b'{"channel":"stable"}',
        document={"channel": "stable"},
        actual_size=20,
    )
    assert manifest.exact_bytes == b'{"channel":"stable"}'
    assert manifest.document == {"channel": "stable"}
    assert manifest.actual_size == 20

    artifact = module.DownloadedArtifact(size=123, sha256="abc")
    assert artifact.size == 123
    assert artifact.sha256 == "abc"

    error = module.GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE")
    assert isinstance(error, ValueError)
    assert error.code == "DOWNLOAD_UNAVAILABLE"
    assert str(error) == "DOWNLOAD_UNAVAILABLE"
    assert "DOWNLOAD_UNAVAILABLE" in repr(error)


# ---------------------------------------------------------------------------
# 2. Initial URL validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/release-v2.json",
        "https://evil.example/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/release-v2.json",
        "https://objects.githubusercontent.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/release-v2.json",
        "https://github.com:8443/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/release-v2.json",
        "https://user:pass@github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/release-v2.json",
        "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/release-v2.json#section",
        "https://github.com/other-org/Neko-Family-Proxy/releases/download/v5.1.0/release-v2.json",
        "https://github.com/Valeneko-pranmong/other-repo/releases/download/v5.1.0/release-v2.json",
        "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/",
    ],
)
def test_manifest_download_rejects_invalid_initial_url(invalid_url: str) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=10,
        browser_download_url=invalid_url,
    )
    downloader = module.GitHubManifestDownloader()
    assert _error_code(lambda: downloader.download(asset)) == "DOWNLOAD_REDIRECT_INVALID"


@pytest.mark.parametrize(
    "invalid_url",
    [
        "http://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/NekoLauncher.exe",
        "https://evil.example/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/NekoLauncher.exe",
        "https://github.com:8443/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/NekoLauncher.exe",
        "https://user:pass@github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/NekoLauncher.exe",
        "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/NekoLauncher.exe#frag",
        "https://github.com/other-org/Neko-Family-Proxy/releases/download/v5.1.0/NekoLauncher.exe",
        "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/",
    ],
)
def test_product_download_rejects_invalid_initial_url(tmp_path: Path, invalid_url: str) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    downloader = module.GitHubAssetDownloader()
    destination = tmp_path / "NekoLauncher.exe"
    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=invalid_url,
                destination=destination,
                expected_size=10,
                expected_sha256="a" * 64,
            )
        )
        == "DOWNLOAD_REDIRECT_INVALID"
    )


# ---------------------------------------------------------------------------
# 3. Manual redirect handling & redirect allowlist (shared semantics)
# ---------------------------------------------------------------------------


def test_direct_200_ok_succeeds_without_redirect() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    body = b'{"channel":"stable"}'
    opener = FakeOpener({INITIAL_MANIFEST_URL: FakeResponse(body=body, status=200)})
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(body),
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    manifest = downloader.download(asset)
    assert manifest.exact_bytes == body
    assert manifest.actual_size == len(body)
    assert len(opener.requests) == 1


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
def test_all_redirect_status_codes_are_accepted(status_code: int) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    target_url = "https://objects.githubusercontent.com/production/release-v2.json"
    body = b'{"channel":"stable"}'
    routes = {
        INITIAL_MANIFEST_URL: FakeResponse(
            status=status_code,
            headers={"Location": target_url},
        ),
        target_url: FakeResponse(body=body, status=200),
    }
    downloader = module.GitHubManifestDownloader(_opener=FakeOpener(routes))
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(body),
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    manifest = downloader.download(asset)
    assert manifest.exact_bytes == body


def test_relative_redirect_resolution() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    body = b'{"channel":"stable"}'
    resolved_target = "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/target.json"
    routes = {
        INITIAL_MANIFEST_URL: FakeResponse(
            status=302,
            headers={"Location": "/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/target.json"},
        ),
        resolved_target: FakeResponse(body=body, status=200),
    }
    downloader = module.GitHubManifestDownloader(_opener=FakeOpener(routes))
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(body),
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    manifest = downloader.download(asset)
    assert manifest.exact_bytes == body


def test_five_hops_pass_sixth_hop_rejects() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    body = b'{"channel":"stable"}'

    # Case 1: Exactly 5 hops (initial -> hop1 -> hop2 -> hop3 -> hop4 -> 200 on hop5)
    hop_urls = [
        INITIAL_MANIFEST_URL,
        "https://objects.githubusercontent.com/hop1",
        "https://objects.githubusercontent.com/hop2",
        "https://objects.githubusercontent.com/hop3",
        "https://objects.githubusercontent.com/hop4",
        "https://objects.githubusercontent.com/final_200",
    ]
    routes_5 = {}
    for i in range(5):
        routes_5[hop_urls[i]] = FakeResponse(
            status=302,
            headers={"Location": hop_urls[i + 1]},
        )
    routes_5[hop_urls[5]] = FakeResponse(body=body, status=200)

    downloader_5 = module.GitHubManifestDownloader(_opener=FakeOpener(routes_5))
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(body),
        browser_download_url=INITIAL_MANIFEST_URL,
    )
    result = downloader_5.download(asset)
    assert result.exact_bytes == body

    # Case 2: 6th hop rejected
    hop6_url = "https://objects.githubusercontent.com/hop6"
    routes_6 = dict(routes_5)
    routes_6[hop_urls[5]] = FakeResponse(
        status=302,
        headers={"Location": hop6_url},
    )
    routes_6[hop6_url] = FakeResponse(body=body, status=200)

    downloader_6 = module.GitHubManifestDownloader(_opener=FakeOpener(routes_6))
    assert _error_code(lambda: downloader_6.download(asset)) == "DOWNLOAD_REDIRECT_INVALID"


def test_redirect_loop_is_rejected() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    url_a = INITIAL_MANIFEST_URL
    url_b = "https://objects.githubusercontent.com/path_b"
    routes = {
        url_a: FakeResponse(status=302, headers={"Location": url_b}),
        url_b: FakeResponse(status=302, headers={"Location": url_a}),
    }
    downloader = module.GitHubManifestDownloader(_opener=FakeOpener(routes))
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=10,
        browser_download_url=INITIAL_MANIFEST_URL,
    )
    assert _error_code(lambda: downloader.download(asset)) == "DOWNLOAD_REDIRECT_INVALID"


@pytest.mark.parametrize(
    "headers",
    [
        {},  # missing Location
        {"Location": ""},  # empty Location
        {"Location": "   "},  # whitespace Location
        {"Location": ["https://objects.githubusercontent.com/1", "https://objects.githubusercontent.com/2"]},  # multiple
    ],
)
def test_missing_multiple_or_invalid_location_rejected(headers: dict[str, Any]) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    routes = {
        INITIAL_MANIFEST_URL: FakeResponse(status=302, headers=headers),
    }
    downloader = module.GitHubManifestDownloader(_opener=FakeOpener(routes))
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=10,
        browser_download_url=INITIAL_MANIFEST_URL,
    )
    assert _error_code(lambda: downloader.download(asset)) == "DOWNLOAD_REDIRECT_INVALID"


@pytest.mark.parametrize(
    "target_url",
    [
        "https://github.com/some/redirected/asset",
        "https://objects.githubusercontent.com/github-production-release-asset-2e65be/123?token=safe",
        "https://release-assets.githubusercontent.com/releases/download/v5.1.0/asset",
    ],
)
def test_allowed_redirect_hosts_accepted(target_url: str) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    body = b'{"channel":"stable"}'
    routes = {
        INITIAL_MANIFEST_URL: FakeResponse(status=302, headers={"Location": target_url}),
        target_url: FakeResponse(body=body, status=200),
    }
    downloader = module.GitHubManifestDownloader(_opener=FakeOpener(routes))
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(body),
        browser_download_url=INITIAL_MANIFEST_URL,
    )
    assert downloader.download(asset).exact_bytes == body


@pytest.mark.parametrize(
    "disallowed_target",
    [
        "http://objects.githubusercontent.com/insecure",  # non-https scheme
        "ftp://objects.githubusercontent.com/ftp",  # non-https scheme
        "https://objects.githubusercontent.com:8443/port",  # non-default port
        "https://user:pass@objects.githubusercontent.com/creds",  # userinfo
        "https://objects.githubusercontent.com/asset#fragment",  # fragment
        "https://raw.githubusercontent.com/Valeneko-pranmong/Neko-Family-Proxy/main/release-v2.json",  # disallowed host
        "https://api.github.com/repos/Valeneko-pranmong/Neko-Family-Proxy/releases/assets/1",  # disallowed host
        "https://evil.example/cdn",  # disallowed host
        "https://objects.githubusercontent.com.attacker.com/fake",  # prefix mismatch
    ],
)
def test_disallowed_redirect_target_policy_rejected(disallowed_target: str) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    routes = {
        INITIAL_MANIFEST_URL: FakeResponse(status=302, headers={"Location": disallowed_target}),
    }
    downloader = module.GitHubManifestDownloader(_opener=FakeOpener(routes))
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=10,
        browser_download_url=INITIAL_MANIFEST_URL,
    )
    assert _error_code(lambda: downloader.download(asset)) == "DOWNLOAD_REDIRECT_INVALID"


def test_fresh_get_per_hop_and_no_authorization_or_cookie_forwarding() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    target_url = "https://objects.githubusercontent.com/cdn/asset"
    body = b'{"channel":"stable"}'
    routes = {
        INITIAL_MANIFEST_URL: FakeResponse(
            status=302,
            headers={
                "Location": target_url,
                "Set-Cookie": "session=secret123; Path=/",
            },
        ),
        target_url: FakeResponse(body=body, status=200),
    }
    opener = FakeOpener(routes)
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(body),
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    downloader.download(asset)

    assert len(opener.requests) == 2
    for req, _timeout in opener.requests:
        assert req.get_method() == "GET"
        assert req.get_header("User-agent") is not None
        assert req.get_header("Accept") is not None
        assert req.get_header("Authorization") is None
        assert req.get_header("Cookie") is None


# ---------------------------------------------------------------------------
# 4. Transport errors & HTTP status failures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 403, 404, 500, 502, 503])
def test_transport_non_200_non_redirect_raises_unavailable(status_code: int) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    opener = FakeOpener(
        {INITIAL_MANIFEST_URL: urllib.error.HTTPError(INITIAL_MANIFEST_URL, status_code, "Error", {}, None)}  # type: ignore[arg-type]
    )
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=10,
        browser_download_url=INITIAL_MANIFEST_URL,
    )
    assert _error_code(lambda: downloader.download(asset)) == "DOWNLOAD_UNAVAILABLE"


@pytest.mark.parametrize(
    "exception",
    [
        urllib.error.URLError("Connection refused"),
        socket.timeout("timed out"),
        TimeoutError("timed out"),
        OSError("Network unreachable"),
    ],
)
def test_transport_network_and_timeout_errors_raise_unavailable(exception: Exception) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    opener = FakeOpener({INITIAL_MANIFEST_URL: exception})
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=10,
        browser_download_url=INITIAL_MANIFEST_URL,
    )
    assert _error_code(lambda: downloader.download(asset)) == "DOWNLOAD_UNAVAILABLE"


# ---------------------------------------------------------------------------
# 5. Manifest download specifics (GitHubManifestDownloader)
# ---------------------------------------------------------------------------


def test_manifest_downloader_requires_exact_release_v2_json_name() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    downloader = module.GitHubManifestDownloader()
    for bad_name in ("NekoLauncher.exe", "manifest.json", "RELEASE-V2.JSON", "release-v2.json.bak"):
        asset = GitHubReleaseAsset(
            id=1,
            name=bad_name,
            size=10,
            browser_download_url=f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v5.1.0/{bad_name}",
        )
        assert _error_code(lambda: downloader.download(asset)) == "MANIFEST_RESPONSE_INVALID"


def test_manifest_downloader_exact_65536_passes() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    # Construct canonical JSON of exactly 65,536 bytes
    # {"channel":"stable","padding":"..."}
    # prefix: '{"channel":"stable","padding":"' (31 bytes)
    # suffix: '"}' (2 bytes)
    # padding length needed: 65,536 - 33 = 65,503 bytes
    padding = "a" * (65_536 - 33)
    exact_bytes = f'{{"channel":"stable","padding":"{padding}"}}'.encode("utf-8")
    assert len(exact_bytes) == 65_536

    opener = FakeOpener({INITIAL_MANIFEST_URL: FakeResponse(body=exact_bytes, status=200)})
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=65_536,
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    manifest = downloader.download(asset)
    assert manifest.exact_bytes == exact_bytes
    assert manifest.actual_size == 65_536


def test_manifest_downloader_overrun_by_one_byte_rejects() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    # Construct 65,537 bytes (one byte overrun)
    padding = "a" * (65_537 - 33)
    overrun_bytes = f'{{"channel":"stable","padding":"{padding}"}}'.encode("utf-8")
    assert len(overrun_bytes) == 65_537

    opener = FakeOpener({INITIAL_MANIFEST_URL: FakeResponse(body=overrun_bytes, status=200)})
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=65_537,
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    assert _error_code(lambda: downloader.download(asset)) == "MANIFEST_TOO_LARGE"


def test_manifest_downloader_untrusted_api_size_mismatch_rejects() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    body = b'{"channel":"stable"}'
    opener = FakeOpener({INITIAL_MANIFEST_URL: FakeResponse(body=body, status=200)})
    downloader = module.GitHubManifestDownloader(_opener=opener)
    # asset.size reports 999 while actual byte count is len(body)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=999,
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    assert _error_code(lambda: downloader.download(asset)) == "MANIFEST_RESPONSE_INVALID"


@pytest.mark.parametrize(
    "invalid_content",
    [
        b'{\n  "channel": "stable"\n}',  # noncanonical whitespace
        b'{"channel": "stable"}',  # noncanonical space after colon
        b'{"z":1,"a":2}',  # noncanonical key ordering (z before a)
        b'{"a":1,"a":2}',  # duplicate keys
        b'{"channel":"stable\xff"}',  # invalid UTF-8
        b'{"channel":"stable",}',  # trailing comma invalid JSON
        b"",  # empty body
    ],
)
def test_manifest_downloader_rejects_noncanonical_or_invalid_json(invalid_content: bytes) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    opener = FakeOpener({INITIAL_MANIFEST_URL: FakeResponse(body=invalid_content, status=200)})
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(invalid_content),
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    assert _error_code(lambda: downloader.download(asset)) == "MANIFEST_RESPONSE_INVALID"


def test_manifest_downloader_preserves_exact_bytes_unchanged() -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    exact = b'{"channel":"stable","release_sequence":42}'
    opener = FakeOpener({INITIAL_MANIFEST_URL: FakeResponse(body=exact, status=200)})
    downloader = module.GitHubManifestDownloader(_opener=opener)
    asset = GitHubReleaseAsset(
        id=1,
        name="release-v2.json",
        size=len(exact),
        browser_download_url=INITIAL_MANIFEST_URL,
    )

    manifest = downloader.download(asset)
    assert manifest.exact_bytes == exact
    assert manifest.exact_bytes is not exact or manifest.exact_bytes == exact
    assert manifest.document == {"channel": "stable", "release_sequence": 42}


# ---------------------------------------------------------------------------
# 6. Product download specifics (GitHubAssetDownloader)
# ---------------------------------------------------------------------------


def test_product_downloader_success_with_exact_size_and_sha256(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    content = b"Simulated PE content for NekoLauncher.exe" * 100
    expected_size = len(content)
    expected_sha256 = hashlib.sha256(content).hexdigest()

    destination = tmp_path / "NekoLauncher.exe"
    opener = FakeOpener({INITIAL_PRODUCT_URL: FakeResponse(body=content, status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    artifact = downloader.download(
        initial_url=INITIAL_PRODUCT_URL,
        destination=destination,
        expected_size=expected_size,
        expected_sha256=expected_sha256.upper(),  # case-insensitive check
    )

    assert artifact.size == expected_size
    assert artifact.sha256 == expected_sha256.lower()
    assert destination.is_file()
    assert destination.read_bytes() == content


def test_product_downloader_requires_existing_parent(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    content = b"content"
    destination = tmp_path / "nonexistent_dir" / "NekoLauncher.exe"
    opener = FakeOpener({INITIAL_PRODUCT_URL: FakeResponse(body=content, status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=INITIAL_PRODUCT_URL,
                destination=destination,
                expected_size=len(content),
                expected_sha256=hashlib.sha256(content).hexdigest(),
            )
        )
        == "DOWNLOAD_WRITE_FAILED"
    )
    assert not destination.exists()


def test_product_downloader_exclusive_create_collision_preserves_existing_file(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    destination = tmp_path / "NekoLauncher.exe"
    original_bytes = b"PRE-EXISTING CONTENT DO NOT TOUCH"
    destination.write_bytes(original_bytes)

    content = b"new content"
    opener = FakeOpener({INITIAL_PRODUCT_URL: FakeResponse(body=content, status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=INITIAL_PRODUCT_URL,
                destination=destination,
                expected_size=len(content),
                expected_sha256=hashlib.sha256(content).hexdigest(),
            )
        )
        == "DOWNLOAD_WRITE_FAILED"
    )
    # Existing file must NOT be deleted or mutated
    assert destination.is_file()
    assert destination.read_bytes() == original_bytes


def test_product_downloader_overrun_cleans_incomplete_destination(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    actual_content = b"0123456789" + b"extra_byte"
    expected_size = 10
    destination = tmp_path / "NekoLauncher.exe"

    opener = FakeOpener({INITIAL_PRODUCT_URL: FakeResponse(body=actual_content, status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=INITIAL_PRODUCT_URL,
                destination=destination,
                expected_size=expected_size,
                expected_sha256="a" * 64,
            )
        )
        == "DOWNLOAD_SIZE_MISMATCH"
    )
    assert not destination.exists(), "Incomplete destination must be removed on failure"


def test_product_downloader_underrun_cleans_incomplete_destination(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    actual_content = b"short"
    expected_size = 100
    destination = tmp_path / "NekoLauncher.exe"

    opener = FakeOpener({INITIAL_PRODUCT_URL: FakeResponse(body=actual_content, status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=INITIAL_PRODUCT_URL,
                destination=destination,
                expected_size=expected_size,
                expected_sha256="a" * 64,
            )
        )
        == "DOWNLOAD_SIZE_MISMATCH"
    )
    assert not destination.exists(), "Incomplete destination must be removed on failure"


def test_product_downloader_hash_mismatch_cleans_incomplete_destination(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    content = b"Exact byte size matching content"
    expected_size = len(content)
    wrong_hash = "0" * 64
    destination = tmp_path / "NekoLauncher.exe"

    opener = FakeOpener({INITIAL_PRODUCT_URL: FakeResponse(body=content, status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=INITIAL_PRODUCT_URL,
                destination=destination,
                expected_size=expected_size,
                expected_sha256=wrong_hash,
            )
        )
        == "DOWNLOAD_HASH_MISMATCH"
    )
    assert not destination.exists(), "Incomplete destination must be removed on failure"


def test_product_downloader_timeout_during_streaming_cleans_destination(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    destination = tmp_path / "NekoLauncher.exe"

    class FailingResponse(FakeResponse):
        def read(self, size: int = -1) -> bytes:
            raise socket.timeout("timed out mid-stream")

    opener = FakeOpener({INITIAL_PRODUCT_URL: FailingResponse(body=b"header", status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=INITIAL_PRODUCT_URL,
                destination=destination,
                expected_size=100,
                expected_sha256="a" * 64,
            )
        )
        == "DOWNLOAD_UNAVAILABLE"
    )
    assert not destination.exists()


def test_product_downloader_write_failure_cleans_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    content = b"some content"
    destination = tmp_path / "NekoLauncher.exe"
    opener = FakeOpener({INITIAL_PRODUCT_URL: FakeResponse(body=content, status=200)})
    downloader = module.GitHubAssetDownloader(_opener=opener)

    real_open = Path.open

    def failing_open(path_obj: Path, *args: Any, **kwargs: Any) -> Any:
        handle = real_open(path_obj, *args, **kwargs)
        if path_obj == destination:

            class FailingWriter:
                def write(self, data: bytes) -> int:
                    raise OSError("Disk full")

                def flush(self) -> None:
                    handle.flush()

                def fileno(self) -> int:
                    return handle.fileno()

                def close(self) -> None:
                    handle.close()

            return FailingWriter()
        return handle

    monkeypatch.setattr(Path, "open", failing_open)

    assert (
        _error_code(
            lambda: downloader.download(
                initial_url=INITIAL_PRODUCT_URL,
                destination=destination,
                expected_size=len(content),
                expected_sha256=hashlib.sha256(content).hexdigest(),
            )
        )
        == "DOWNLOAD_WRITE_FAILED"
    )
    assert not destination.exists()


def test_product_downloader_streams_large_file_in_1mib_chunks(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    # 2.5 MiB content to prove streaming in chunks
    chunk_1m = b"A" * (1024 * 1024)
    content = chunk_1m + chunk_1m + b"B" * (512 * 1024)
    expected_size = len(content)
    expected_sha256 = hashlib.sha256(content).hexdigest()

    fake_response = FakeResponse(body=content, status=200)
    opener = FakeOpener({INITIAL_PRODUCT_URL: fake_response})
    downloader = module.GitHubAssetDownloader(_opener=opener)
    destination = tmp_path / "NekoLauncher.exe"

    artifact = downloader.download(
        initial_url=INITIAL_PRODUCT_URL,
        destination=destination,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )

    assert artifact.size == expected_size
    assert artifact.sha256 == expected_sha256
    assert destination.read_bytes() == content
    # Verify read chunk size was 1 MiB (1,048,576)
    assert all(size == 1024 * 1024 for size in fake_response.read_calls[:-1])


def test_product_downloader_ignores_http_content_length_etag_digest(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "Task 3 production module must exist"

    content = b"product binary"
    expected_size = len(content)
    expected_sha256 = hashlib.sha256(content).hexdigest()

    destination = tmp_path / "NekoLauncher.exe"
    # HTTP metadata carries conflicting values
    fake_response = FakeResponse(
        body=content,
        status=200,
        headers={
            "Content-Length": "999999",
            "ETag": '"conflicting-etag"',
            "Digest": "sha-256=wrong",
        },
    )
    downloader = module.GitHubAssetDownloader(_opener=FakeOpener({INITIAL_PRODUCT_URL: fake_response}))

    artifact = downloader.download(
        initial_url=INITIAL_PRODUCT_URL,
        destination=destination,
        expected_size=expected_size,
        expected_sha256=expected_sha256,
    )
    assert artifact.size == expected_size
    assert artifact.sha256 == expected_sha256
