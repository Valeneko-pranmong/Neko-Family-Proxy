from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, TypeAlias


_MANIFEST_MAX_BYTES: Final = 65_536
_GRANT_MAX_BYTES: Final = 16_384

_MANIFEST_UNAVAILABLE: Final = "MANIFEST_UNAVAILABLE"
_MANIFEST_RESPONSE_INVALID: Final = "MANIFEST_RESPONSE_INVALID"
_GRANT_UNAVAILABLE: Final = "GRANT_UNAVAILABLE"
_GRANT_RESPONSE_INVALID: Final = "GRANT_RESPONSE_INVALID"

ErrorCode: TypeAlias = Literal[
    "MANIFEST_UNAVAILABLE",
    "MANIFEST_RESPONSE_INVALID",
    "GRANT_UNAVAILABLE",
    "GRANT_RESPONSE_INVALID",
]

_SAFE_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        _MANIFEST_UNAVAILABLE,
        _MANIFEST_RESPONSE_INVALID,
        _GRANT_UNAVAILABLE,
        _GRANT_RESPONSE_INVALID,
    }
)

_RFC3339_PATTERN: Final = re.compile(
    r"\A"
    r"\d{4}-\d{2}-\d{2}"
    r"T"
    r"\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})"
    r"\Z"
)


class SoftwareUpdateClientError(ValueError):
    def __init__(self, code: ErrorCode) -> None:
        if code not in _SAFE_ERROR_CODES:
            raise ValueError("invalid software update client error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ArtifactGrant:
    url: str
    expires_at: datetime

    def __repr__(self) -> str:
        try:
            parsed = urllib.parse.urlsplit(self.url)
            redacted_url = urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    "<redacted>" if parsed.query else "",
                    "",
                )
            )
        except ValueError:
            redacted_url = "<redacted>"
        return (
            f"{type(self).__name__}("
            f"url={redacted_url!r}, expires_at={self.expires_at!r})"
        )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


_open_no_redirect = urllib.request.build_opener(_NoRedirectHandler()).open


def _normalize_base_url(base_url: str) -> str:
    if type(base_url) is not str:
        raise ValueError("base_url must be an HTTPS URL")

    try:
        parsed = urllib.parse.urlsplit(base_url)
        hostname = parsed.hostname
    except ValueError as error:
        raise ValueError("base_url must be an HTTPS URL") from error

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an HTTPS URL")

    return base_url.rstrip("/")


def _response_status(response: object) -> int | None:
    status = getattr(response, "status", None)
    if status is not None:
        return status

    getcode = getattr(response, "getcode", None)
    if getcode is None:
        return None
    return getcode()


def _read_limited(response: object, maximum: int) -> bytes:
    data = response.read(maximum + 1)
    if type(data) is not bytes or len(data) > maximum:
        raise ValueError("response invalid")
    return data


def _decode_json(data: bytes) -> object:
    text = data.decode("utf-8")
    return json.loads(text)


def _parse_expiration(value: str) -> datetime:
    if _RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError("expiration invalid")

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    expires_at = datetime.fromisoformat(normalized)
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expiration invalid")
    return expires_at


def _validate_grant_url(value: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("grant URL invalid") from error

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("grant URL invalid")

    if port is not None and not 0 < port <= 65_535:
        raise ValueError("grant URL invalid")


class HttpUpdateManifestGateway:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._timeout = timeout

    def fetch(self, channel: str = "beta") -> object | None:
        query = urllib.parse.urlencode({"channel": channel})
        request = urllib.request.Request(
            f"{self._base_url}/api/software-update/manifest?{query}",
            headers={"Accept": "application/json"},
            method="GET",
        )

        try:
            with _open_no_redirect(request, timeout=self._timeout) as response:
                if _response_status(response) != 200:
                    raise SoftwareUpdateClientError(_MANIFEST_UNAVAILABLE)
                try:
                    payload = _decode_json(
                        _read_limited(response, _MANIFEST_MAX_BYTES)
                    )
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    ValueError,
                    TypeError,
                ) as error:
                    raise SoftwareUpdateClientError(
                        _MANIFEST_RESPONSE_INVALID
                    ) from error
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise SoftwareUpdateClientError(_MANIFEST_UNAVAILABLE) from error
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as error:
            raise SoftwareUpdateClientError(_MANIFEST_UNAVAILABLE) from error

        if type(payload) is not dict:
            raise SoftwareUpdateClientError(_MANIFEST_RESPONSE_INVALID)
        return payload


class HttpArtifactGrantGateway:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._timeout = timeout

    def grant(self, artifact_id: str) -> ArtifactGrant:
        body = json.dumps(
            {"artifact_id": artifact_id},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/api/software-update/artifact-grant",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with _open_no_redirect(request, timeout=self._timeout) as response:
                if _response_status(response) != 200:
                    raise SoftwareUpdateClientError(_GRANT_UNAVAILABLE)
                try:
                    payload = _decode_json(_read_limited(response, _GRANT_MAX_BYTES))
                except (
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    ValueError,
                    TypeError,
                ) as error:
                    raise SoftwareUpdateClientError(
                        _GRANT_RESPONSE_INVALID
                    ) from error
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as error:
            raise SoftwareUpdateClientError(_GRANT_UNAVAILABLE) from error

        if type(payload) is not dict or set(payload) != {"url", "expires_at"}:
            raise SoftwareUpdateClientError(_GRANT_RESPONSE_INVALID)

        url = payload["url"]
        expires_at_value = payload["expires_at"]
        if type(url) is not str or type(expires_at_value) is not str:
            raise SoftwareUpdateClientError(_GRANT_RESPONSE_INVALID)

        try:
            _validate_grant_url(url)
            expires_at = _parse_expiration(expires_at_value)
        except (ValueError, OverflowError) as error:
            raise SoftwareUpdateClientError(_GRANT_RESPONSE_INVALID) from error

        return ArtifactGrant(url=url, expires_at=expires_at)
