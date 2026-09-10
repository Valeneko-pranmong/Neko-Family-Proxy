from __future__ import annotations

import importlib
import json
import socket
import urllib.error
from dataclasses import asdict
from typing import Any

import pytest

MODULE_NAME = "neko_launcher.infrastructure.github_release"
API_URL = (
    "https://api.github.com/repos/Valeneko-pranmong/"
    "Neko-Family-Proxy/releases/latest"
)
DOWNLOAD_PREFIX = (
    "https://github.com/Valeneko-pranmong/"
    "Neko-Family-Proxy/releases/download/v5.1.0/"
)


def _module() -> Any:
    try:
        return importlib.import_module(MODULE_NAME)
    except ModuleNotFoundError:
        return None


def _valid_document() -> dict[str, object]:
    return {
        "id": 7,
        "tag_name": "v5.1.0",
        "draft": False,
        "prerelease": False,
        "zipball_url": "https://api.github.com/repos/ignored/source.zip",
        "tarball_url": "https://api.github.com/repos/ignored/source.tar.gz",
        "body": "ignored",
        "assets": [
            {
                "id": 11,
                "name": "release-v2.json",
                "size": 123,
                "browser_download_url": DOWNLOAD_PREFIX + "release-v2.json",
                "content_type": "application/json",
            }
        ],
    }


def _error_code(callable_: Any) -> str:
    with pytest.raises(ValueError) as exc_info:
        callable_()
    return exc_info.value.code


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.read_sizes: list[int] = []

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            data, self.body = self.body, b""
        else:
            data, self.body = self.body[:size], self.body[size:]
        return data


class FakeOpener:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[tuple[Any, float]] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result  # type: ignore[return-value]


def _gateway(monkeypatch: pytest.MonkeyPatch, result: object, timeout: float = 2.5):
    module = _module()
    assert module is not None, "Task 1 production module must exist"
    opener = FakeOpener(result)
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *handlers: opener)
    return module, module.GitHubLatestReleaseGateway(timeout=timeout), opener


def test_fixed_contract_and_valid_typed_subset_ignores_unknown_source_fields() -> None:
    module = _module()
    assert module is not None, "Task 1 production module must exist"
    assert module.GITHUB_RELEASE_OWNER == "Valeneko-pranmong"
    assert module.GITHUB_RELEASE_REPOSITORY == "Neko-Family-Proxy"
    assert module.GITHUB_RELEASE_API_URL == API_URL

    release = module.parse_github_release(_valid_document())

    assert asdict(release) == {
        "id": 7,
        "tag_name": "v5.1.0",
        "draft": False,
        "prerelease": False,
        "assets": (
            {
                "id": 11,
                "name": "release-v2.json",
                "size": 123,
                "browser_download_url": DOWNLOAD_PREFIX + "release-v2.json",
            },
        ),
    }
    assert [asset.name for asset in release.assets] == ["release-v2.json"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(id=True), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(id=0), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(id="7"), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(tag_name="5.1.0"), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(tag_name="v" + "a" * 65), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(tag_name="v5/1"), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(draft=0), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(prerelease=None), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(draft=True), "GITHUB_RELEASE_INELIGIBLE"),
        (lambda d: d.update(prerelease=True), "GITHUB_RELEASE_INELIGIBLE"),
        (lambda d: d.update(assets=[]), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(assets="assets"), "GITHUB_RELEASE_RESPONSE_INVALID"),
        (lambda d: d.update(assets=d["assets"] * 65), "GITHUB_RELEASE_RESPONSE_INVALID"),
    ],
)
def test_rejects_invalid_release_fields(mutate: Any, code: str) -> None:
    module = _module()
    assert module is not None, "Task 1 production module must exist"
    document = _valid_document()
    mutate(document)
    assert _error_code(lambda: module.parse_github_release(document)) == code


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", True),
        ("id", 0),
        ("id", "11"),
        ("name", ""),
        ("name", "bad name.exe"),
        ("name", "a" * 129),
        ("size", True),
        ("size", 0),
        ("size", 1_073_741_825),
        ("browser_download_url", 1),
        ("browser_download_url", "http://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v/a"),
        ("browser_download_url", "https://evil.example/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v/a"),
        ("browser_download_url", "https://github.com/other/repo/releases/download/v/a"),
        ("browser_download_url", "https://user@github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v/a"),
        ("browser_download_url", "https://github.com:444/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v/a"),
        ("browser_download_url", "https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v/a#fragment"),
    ],
)
def test_rejects_invalid_asset_fields(field: str, value: object) -> None:
    module = _module()
    assert module is not None, "Task 1 production module must exist"
    document = _valid_document()
    document["assets"][0][field] = value  # type: ignore[index]
    assert _error_code(lambda: module.parse_github_release(document)) == "GITHUB_RELEASE_RESPONSE_INVALID"


@pytest.mark.parametrize("duplicate", ["id", "exact_name", "casefold_name"])
def test_rejects_duplicate_asset_identity(duplicate: str) -> None:
    module = _module()
    assert module is not None, "Task 1 production module must exist"
    document = _valid_document()
    second = {
        "id": 12,
        "name": "NekoLauncher.exe",
        "size": 456,
        "browser_download_url": DOWNLOAD_PREFIX + "NekoLauncher.exe",
    }
    if duplicate == "id":
        second["id"] = 11
    elif duplicate == "exact_name":
        second["name"] = "release-v2.json"
    else:
        second["name"] = "RELEASE-V2.JSON"
    document["assets"].append(second)  # type: ignore[union-attr]
    assert _error_code(lambda: module.parse_github_release(document)) == "GITHUB_RELEASE_RESPONSE_INVALID"


def test_gateway_exact_get_safe_headers_no_redirect_and_bounded_read(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(_valid_document()).encode("utf-8")
    response = FakeResponse(body)
    module, gateway, opener = _gateway(monkeypatch, response)

    release = gateway.fetch()

    assert release.id == 7
    assert response.read_sizes == [262_145]
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    assert request.full_url == API_URL
    assert request.get_method() == "GET"
    assert timeout == 2.5
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers == {
        "accept": "application/vnd.github+json",
        "user-agent": module.GITHUB_RELEASE_USER_AGENT,
        "x-github-api-version": "2022-11-28",
    }
    assert "authorization" not in headers
    assert "cookie" not in headers


@pytest.mark.parametrize(
    "body",
    [
        b"{not-json",
        b'\xff',
        b'{"id":7,"id":8,"tag_name":"v5","draft":false,"prerelease":false,"assets":[]}',
        b"x" * 262_145,
    ],
    ids=["malformed-json", "invalid-utf8", "duplicate-key", "oversized"],
)
def test_gateway_rejects_malformed_duplicate_or_oversized_response(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    _, gateway, _ = _gateway(monkeypatch, FakeResponse(body))
    assert _error_code(gateway.fetch) == "GITHUB_RELEASE_RESPONSE_INVALID"


def test_gateway_404_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(API_URL, 404, "secret URL detail", {}, None)
    _, gateway, _ = _gateway(monkeypatch, error)
    assert gateway.fetch() is None


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(API_URL, 403, "rate limited secret", {}, None),
        urllib.error.HTTPError(API_URL, 500, "upstream secret", {}, None),
        urllib.error.URLError(socket.timeout("secret timeout")),
        urllib.error.URLError(OSError("secret network URL")),
        TimeoutError("secret timeout"),
    ],
)
def test_gateway_maps_non_200_timeout_and_network_to_closed_unavailable(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    _, gateway, _ = _gateway(monkeypatch, error)
    with pytest.raises(ValueError) as exc_info:
        gateway.fetch()
    assert exc_info.value.code == "GITHUB_RELEASE_UNAVAILABLE"
    assert str(exc_info.value) == "GITHUB_RELEASE_UNAVAILABLE"


def test_gateway_rejects_api_redirect_without_following(monkeypatch: pytest.MonkeyPatch) -> None:
    redirect = urllib.error.HTTPError(API_URL, 302, "redirect secret", {"Location": "https://evil.example"}, None)
    _, gateway, opener = _gateway(monkeypatch, redirect)
    assert _error_code(gateway.fetch) == "GITHUB_RELEASE_UNAVAILABLE"
    assert len(opener.requests) == 1

def test_gateway_exact_get_by_id_accepts_prerelease_not_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _valid_document()
    document["id"] = 12345
    document["prerelease"] = True
    body = json.dumps(document).encode("utf-8")
    response = FakeResponse(body)
    module, gateway, opener = _gateway(monkeypatch, response)

    release = gateway.fetch_by_id(12345)

    assert release.id == 12345
    assert release.prerelease is True
    assert release.draft is False
    assert len(opener.requests) == 1
    request, _ = opener.requests[0]
    expected_url = (
        "https://api.github.com/repos/Valeneko-pranmong/"
        "Neko-Family-Proxy/releases/12345"
    )
    assert request.full_url == expected_url


def test_gateway_fetch_by_id_rejects_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _valid_document()
    document["id"] = 12345
    document["draft"] = True
    body = json.dumps(document).encode("utf-8")
    response = FakeResponse(body)
    module, gateway, opener = _gateway(monkeypatch, response)

    assert _error_code(lambda: gateway.fetch_by_id(12345)) == "GITHUB_RELEASE_INELIGIBLE"
