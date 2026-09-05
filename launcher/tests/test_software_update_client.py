from __future__ import annotations

import importlib
import json
import urllib.error
import urllib.request
from datetime import datetime
from types import ModuleType
from typing import Callable

import pytest


MODULE_NAME = "neko_launcher.infrastructure.software_update_client"
ARTIFACT_ID = "launcher-win-x64-beta-0002"
GRANT_PATH = "/api/software-update/artifact-grant"
MANIFEST_PATH = "/api/software-update/manifest?channel=beta"
BASE_URL = "https://updates.example.test"
EXPIRES_AT = "2030-01-02T03:04:05Z"
SENTINEL_TOKEN = "SUPER_SECRET_SIGNED_QUERY_TOKEN"


def load_client_module() -> ModuleType:
    try:
        return importlib.import_module(MODULE_NAME)
    except ImportError as exc:
        pytest.fail(
            f"Required production module {MODULE_NAME!r} is missing or cannot "
            f"be imported: {exc}",
            pytrace=False,
        )


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.code = status

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            result = self._body
            self._body = b""
            return result
        result = self._body[:size]
        self._body = self._body[size:]
        return result

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class RecordingOpener:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(
        self,
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> FakeResponse:
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def install_opener(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    opener: RecordingOpener,
) -> None:
    def build_opener(*_handlers: object) -> RecordingOpener:
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    monkeypatch.setattr(urllib.request, "urlopen", opener.open)

    if hasattr(module, "build_opener"):
        monkeypatch.setattr(module, "build_opener", build_opener)
    if hasattr(module, "urlopen"):
        monkeypatch.setattr(module, "urlopen", opener.open)
    if hasattr(module, "_open_no_redirect"):
        monkeypatch.setattr(module, "_open_no_redirect", opener.open)
    if hasattr(module, "_opener"):
        monkeypatch.setattr(module, "_opener", opener)


def make_http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        f"{BASE_URL}/failure",
        status,
        "safe test status",
        hdrs=None,
        fp=None,
    )


def manifest_body_of_size(size: int) -> bytes:
    prefix = b'{"padding":"'
    suffix = b'"}'
    padding_size = size - len(prefix) - len(suffix)
    assert padding_size >= 0
    body = prefix + (b"x" * padding_size) + suffix
    assert len(body) == size
    return body


def grant_body(
    *,
    url: object = f"https://cdn.example.test/launcher.zip?token={SENTINEL_TOKEN}",
    expires_at: object = EXPIRES_AT,
    extra: dict[str, object] | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "url": url,
        "expires_at": expires_at,
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, separators=(",", ":")).encode()


def grant_body_of_size(size: int) -> bytes:
    fixed_prefix = b'{"url":"https://cdn.example.test/file?token='
    fixed_suffix = (
        b'","expires_at":"'
        + EXPIRES_AT.encode()
        + b'"}'
    )
    padding_size = size - len(fixed_prefix) - len(fixed_suffix)
    assert padding_size >= 1
    body = fixed_prefix + (b"x" * padding_size) + fixed_suffix
    assert len(body) == size
    assert set(json.loads(body)) == {"url", "expires_at"}
    return body


def assert_client_error(
    module: ModuleType,
    expected_code: str,
    operation: Callable[[], object],
    *,
    forbidden: tuple[str, ...] = (),
) -> None:
    with pytest.raises(module.SoftwareUpdateClientError) as caught:
        operation()

    error = caught.value
    assert error.code == expected_code
    assert str(error) == expected_code
    for value in forbidden:
        assert value not in str(error)
        assert value not in repr(error)


@pytest.mark.parametrize(
    "gateway_name",
    ["HttpUpdateManifestGateway", "HttpArtifactGrantGateway"],
)
@pytest.mark.parametrize(
    "base_url",
    [
        "http://updates.example.test",
        "ftp://updates.example.test",
        "updates.example.test",
    ],
)
def test_gateways_reject_non_https_base_urls(
    gateway_name: str,
    base_url: str,
) -> None:
    module = load_client_module()
    gateway_type = getattr(module, gateway_name)

    with pytest.raises((TypeError, ValueError)):
        gateway_type(base_url)


def test_manifest_sends_exact_get_request_with_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(b'{"version":"2.0.0"}'))
    install_opener(monkeypatch, module, opener)

    result = module.HttpUpdateManifestGateway(BASE_URL).fetch()

    assert result == {"version": "2.0.0"}
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.full_url == BASE_URL + MANIFEST_PATH
    assert request.get_method() == "GET"
    assert request.data is None
    assert timeout == 5.0


def test_manifest_honors_custom_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(b"{}"))
    install_opener(monkeypatch, module, opener)

    module.HttpUpdateManifestGateway(BASE_URL, timeout=1.25).fetch()

    assert opener.calls[0][1] == 1.25


def test_manifest_url_encodes_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(b"{}"))
    install_opener(monkeypatch, module, opener)

    module.HttpUpdateManifestGateway(BASE_URL).fetch("beta candidate/1")

    request, _ = opener.calls[0]
    assert request.full_url == (
        BASE_URL
        + "/api/software-update/manifest?channel=beta+candidate%2F1"
    )


def test_manifest_returns_decoded_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    expected = {
        "version": "2.0.0",
        "signature": {"unexpected": "shape is not validated here"},
    }
    opener = RecordingOpener(
        FakeResponse(json.dumps(expected, separators=(",", ":")).encode())
    )
    install_opener(monkeypatch, module, opener)

    assert module.HttpUpdateManifestGateway(BASE_URL).fetch() == expected


def test_manifest_accepts_body_exactly_65536_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    body = manifest_body_of_size(65_536)
    opener = RecordingOpener(FakeResponse(body))
    install_opener(monkeypatch, module, opener)

    result = module.HttpUpdateManifestGateway(BASE_URL).fetch()

    assert isinstance(result, dict)
    assert result["padding"] == "x" * (65_536 - len(b'{"padding":""}'))


def test_manifest_rejects_body_larger_than_65536_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(manifest_body_of_size(65_537)))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpUpdateManifestGateway(BASE_URL)

    assert_client_error(
        module,
        "MANIFEST_RESPONSE_INVALID",
        gateway.fetch,
    )


def test_manifest_http_404_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(error=make_http_error(404))
    install_opener(monkeypatch, module, opener)

    assert module.HttpUpdateManifestGateway(BASE_URL).fetch() is None


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 500, 503])
def test_manifest_non_404_http_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(error=make_http_error(status))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpUpdateManifestGateway(BASE_URL)

    assert_client_error(module, "MANIFEST_UNAVAILABLE", gateway.fetch)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("offline"),
        TimeoutError("timed out"),
        OSError("socket failed"),
    ],
)
def test_manifest_network_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(error=error)
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpUpdateManifestGateway(BASE_URL)

    assert_client_error(module, "MANIFEST_UNAVAILABLE", gateway.fetch)


@pytest.mark.parametrize("status", [300, 301, 302, 307, 308, 500])
def test_manifest_non_200_response_status_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(b"{}", status=status))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpUpdateManifestGateway(BASE_URL)

    assert_client_error(module, "MANIFEST_UNAVAILABLE", gateway.fetch)


def test_shared_no_redirect_handler_rejects_http_302_redirect() -> None:
    module = load_client_module()

    assert issubclass(
        module._NoRedirectHandler,
        urllib.request.HTTPRedirectHandler,
    )

    handler = module._NoRedirectHandler()
    request = urllib.request.Request(BASE_URL + MANIFEST_PATH)

    assert handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://redirect.example.test/manifest",
    ) is None


@pytest.mark.parametrize(
    "body",
    [
        b"\xff",
        b'{"broken":',
        b"null",
        b"[]",
        b'"text"',
        b"123",
        b"true",
    ],
)
def test_manifest_rejects_invalid_or_non_object_json(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(body))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpUpdateManifestGateway(BASE_URL)

    assert_client_error(
        module,
        "MANIFEST_RESPONSE_INVALID",
        gateway.fetch,
    )


def test_grant_sends_exact_compact_json_post_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(grant_body()))
    install_opener(monkeypatch, module, opener)

    module.HttpArtifactGrantGateway(BASE_URL).grant(ARTIFACT_ID)

    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.full_url == BASE_URL + GRANT_PATH
    assert request.get_method() == "POST"
    assert request.data == (
        b'{"artifact_id":"launcher-win-x64-beta-0002"}'
    )
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Accept") == "application/json"
    assert timeout == 5.0


def test_grant_honors_custom_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(grant_body()))
    install_opener(monkeypatch, module, opener)

    module.HttpArtifactGrantGateway(BASE_URL, timeout=2.75).grant(ARTIFACT_ID)

    assert opener.calls[0][1] == 2.75


def test_grant_returns_https_url_and_aware_expiration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    url = "https://cdn.example.test/launcher.zip"
    opener = RecordingOpener(FakeResponse(grant_body(url=url)))
    install_opener(monkeypatch, module, opener)

    grant = module.HttpArtifactGrantGateway(BASE_URL).grant(ARTIFACT_ID)

    assert isinstance(grant, module.ArtifactGrant)
    assert grant.url == url
    assert isinstance(grant.expires_at, datetime)
    assert grant.expires_at.tzinfo is not None
    assert grant.expires_at.utcoffset() is not None
    assert grant.expires_at.isoformat() == "2030-01-02T03:04:05+00:00"


@pytest.mark.parametrize(
    "body",
    [
        b"\xff",
        b'{"url":',
        b"null",
        b"[]",
        b'"text"',
        b"123",
        grant_body(extra={"unexpected": True}),
        json.dumps({"url": "https://cdn.example.test/file"}).encode(),
        json.dumps({"expires_at": EXPIRES_AT}).encode(),
        grant_body(url=123),
        grant_body(expires_at=123),
        grant_body(url="http://cdn.example.test/file"),
        grant_body(url="ftp://cdn.example.test/file"),
        grant_body(url="/relative/file"),
        grant_body(expires_at="2030-01-02T03:04:05"),
        grant_body(expires_at="not-a-timestamp"),
    ],
)
def test_grant_rejects_invalid_response_shapes_and_values(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(body))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpArtifactGrantGateway(BASE_URL)

    assert_client_error(
        module,
        "GRANT_RESPONSE_INVALID",
        lambda: gateway.grant(ARTIFACT_ID),
    )


def test_grant_accepts_body_exactly_16384_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(grant_body_of_size(16_384)))
    install_opener(monkeypatch, module, opener)

    grant = module.HttpArtifactGrantGateway(BASE_URL).grant(ARTIFACT_ID)

    assert grant.url.startswith("https://")
    assert grant.expires_at.tzinfo is not None


def test_grant_rejects_body_larger_than_16384_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(grant_body_of_size(16_385)))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpArtifactGrantGateway(BASE_URL)

    assert_client_error(
        module,
        "GRANT_RESPONSE_INVALID",
        lambda: gateway.grant(ARTIFACT_ID),
    )


@pytest.mark.parametrize("status", [300, 301, 302, 307, 308, 400, 404, 500, 503])
def test_grant_http_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(error=make_http_error(status))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpArtifactGrantGateway(BASE_URL)

    assert_client_error(
        module,
        "GRANT_UNAVAILABLE",
        lambda: gateway.grant(ARTIFACT_ID),
    )


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("offline"),
        TimeoutError("timed out"),
        OSError("socket failed"),
    ],
)
def test_grant_network_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(error=error)
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpArtifactGrantGateway(BASE_URL)

    assert_client_error(
        module,
        "GRANT_UNAVAILABLE",
        lambda: gateway.grant(ARTIFACT_ID),
    )


@pytest.mark.parametrize("status", [300, 301, 302, 307, 308, 404, 500])
def test_grant_non_200_response_status_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    module = load_client_module()
    opener = RecordingOpener(FakeResponse(grant_body(), status=status))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpArtifactGrantGateway(BASE_URL)

    assert_client_error(
        module,
        "GRANT_UNAVAILABLE",
        lambda: gateway.grant(ARTIFACT_ID),
    )


def test_grant_accepts_signed_url_but_repr_redacts_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    raw_query = f"token={SENTINEL_TOKEN}&signature=abc123"
    url = f"https://cdn.example.test/launcher.zip?{raw_query}"
    opener = RecordingOpener(FakeResponse(grant_body(url=url)))
    install_opener(monkeypatch, module, opener)

    grant = module.HttpArtifactGrantGateway(BASE_URL).grant(ARTIFACT_ID)
    rendered = repr(grant)

    assert grant.url == url
    assert SENTINEL_TOKEN not in rendered
    assert raw_query not in rendered
    assert "signature=abc123" not in rendered


def test_invalid_grant_error_never_exposes_returned_url_or_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    returned_url = (
        f"http://unsafe.example.test/file?token={SENTINEL_TOKEN}"
    )
    opener = RecordingOpener(
        FakeResponse(grant_body(url=returned_url, extra={"bad": True}))
    )
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpArtifactGrantGateway(BASE_URL)

    assert_client_error(
        module,
        "GRANT_RESPONSE_INVALID",
        lambda: gateway.grant(ARTIFACT_ID),
        forbidden=(returned_url, SENTINEL_TOKEN, "token="),
    )


def test_invalid_manifest_error_exposes_only_safe_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    secret_body = f'{{"token":"{SENTINEL_TOKEN}"'.encode()
    opener = RecordingOpener(FakeResponse(secret_body))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpUpdateManifestGateway(BASE_URL)

    assert_client_error(
        module,
        "MANIFEST_RESPONSE_INVALID",
        gateway.fetch,
        forbidden=(SENTINEL_TOKEN, secret_body.decode()),
    )


def test_invalid_grant_error_exposes_only_safe_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_client_module()
    secret_body = f'{{"token":"{SENTINEL_TOKEN}"'.encode()
    opener = RecordingOpener(FakeResponse(secret_body))
    install_opener(monkeypatch, module, opener)
    gateway = module.HttpArtifactGrantGateway(BASE_URL)

    assert_client_error(
        module,
        "GRANT_RESPONSE_INVALID",
        lambda: gateway.grant(ARTIFACT_ID),
        forbidden=(SENTINEL_TOKEN, secret_body.decode()),
    )
