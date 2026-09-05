from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from neko_launcher.infrastructure import software_update_client
from neko_launcher.infrastructure.diagnostics_logger import DevelopmentLogger
from neko_launcher.infrastructure.software_update_client import (
    HttpArtifactGrantGateway,
    HttpUpdateManifestGateway,
    SoftwareUpdateClientError,
)

PROXY_CREDENTIAL = "SENTINEL_PROXY_CREDENTIAL_42"
JWT_TOKEN = "eyJaaaaaa.bbbbbbb.ccccccc"
SIGNED_URL_TOKEN = "SENTINEL_SIGNED_URL_TOKEN_42"
SIGNED_URL = (
    "https://objects.example.invalid/a"
    f"?token={SIGNED_URL_TOKEN}&signature=abc"
)
BASE_URL = "https://updates.example.invalid"


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self.body
        return self.body[:size]


class FakeOpener:
    def __init__(
        self,
        *,
        response: FakeResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error

    def __call__(self, request: Any, *, timeout: float) -> FakeResponse:
        del request, timeout
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


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


def test_manifest_client_retains_only_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reason = (
        f"proxy authentication failed credential={PROXY_CREDENTIAL}; "
        f"permit={JWT_TOKEN}"
    )
    opener = FakeOpener(error=urllib.error.URLError(reason))
    monkeypatch.setattr(software_update_client, "_open_no_redirect", opener)
    gateway = HttpUpdateManifestGateway(BASE_URL)

    with pytest.raises(SoftwareUpdateClientError) as caught:
        gateway.fetch()

    error = caught.value
    assert error.code == "MANIFEST_UNAVAILABLE"
    assert str(error) == "MANIFEST_UNAVAILABLE"
    assert_secrets_absent(
        str(error),
        PROXY_CREDENTIAL,
        JWT_TOKEN,
    )
    assert_secrets_absent(
        repr(error),
        PROXY_CREDENTIAL,
        JWT_TOKEN,
    )


def test_grant_client_retains_only_safe_invalid_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps(
        {
            "url": SIGNED_URL,
            "credential": PROXY_CREDENTIAL,
        }
    ).encode()
    opener = FakeOpener(response=FakeResponse(body))
    monkeypatch.setattr(software_update_client, "_open_no_redirect", opener)
    gateway = HttpArtifactGrantGateway(BASE_URL)

    with pytest.raises(SoftwareUpdateClientError) as caught:
        gateway.grant("artifact-42")

    error = caught.value
    assert error.code == "GRANT_RESPONSE_INVALID"
    assert str(error) == "GRANT_RESPONSE_INVALID"
    assert_secrets_absent(
        str(error),
        SIGNED_URL,
        SIGNED_URL_TOKEN,
        PROXY_CREDENTIAL,
    )
    assert_secrets_absent(
        repr(error),
        SIGNED_URL,
        SIGNED_URL_TOKEN,
        PROXY_CREDENTIAL,
    )
