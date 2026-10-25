from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from neko_launcher import __version__
from neko_launcher.application.errors import LauncherServiceError

PROXY_ME_PATH = "/v1/me"
IDENTITY_TOKEN_PATH = "/api/launcher/token"
CLIENT_ID = "neko-launcher"
HTTP_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 65_536
MAX_TOKEN_CHARS = 16_384
MAX_DISPLAY_NAME_CHARS = 120
MAX_STATUS_CHARS = 32
ALLOWED_ACCOUNT_STATUSES = frozenset({"pending", "active", "suspended", "closed"})

SHARED_ERROR_MESSAGES = {
    "invalid_token": "เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่",
    "token_expired": "เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่",
    "insufficient_scope": "โปรแกรมนี้ไม่มีสิทธิ์เชื่อมต่อระบบ กรุณาอัปเดตโปรแกรม",
    "identity_not_linked": (
        "บัญชี Discord นี้ยังไม่ได้เชื่อมกับบัญชี Neko Family "
        "กรุณาติดต่อฝ่ายบริการ"
    ),
    "account_pending": "บัญชีนี้อยู่ระหว่างการตรวจสอบ กรุณารอหรือติดต่อฝ่ายบริการ",
    "account_suspended": "บัญชีนี้ไม่สามารถใช้งานได้ กรุณาติดต่อฝ่ายบริการ",
    "license_expired": "สิทธิ์ใช้งานหมดอายุ กรุณาเติมวันหรือติดต่อฝ่ายบริการ",
    "session_conflict": (
        "บัญชีนี้ถูกใช้งานบนเครื่องอื่น กรุณาออกจากระบบบนเครื่องนั้นก่อน"
    ),
    "rate_limited": "ทำรายการบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่",
    "upstream_unavailable": "ระบบปลายทางไม่พร้อมใช้งาน กรุณาลองใหม่",
}

INTERNAL_ERROR_MESSAGES = {
    "invalid_grant": "เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่",
    "invalid_client": "โปรแกรมไม่ได้รับอนุญาต กรุณาอัปเดตโปรแกรม",
    "access_denied": "คุณยกเลิกการเข้าสู่ระบบ",
    "server_error": "ระบบล็อกอินขัดข้อง กรุณาลองใหม่",
    "network_error": "เชื่อมต่อระบบไม่ได้ กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองใหม่",
    "timeout": "เชื่อมต่อระบบนานเกินไป กรุณาลองใหม่",
    "invalid_response": "ระบบตอบกลับไม่ถูกต้อง กรุณาลองใหม่",
    "http_error": "ระบบขัดข้อง กรุณาลองใหม่",
    "credential_store_unavailable": "จัดเก็บข้อมูลล็อกอินไม่สำเร็จ กรุณาลองใหม่",
}

GENERIC_ERROR_MESSAGE = "เกิดข้อผิดพลาด กรุณาลองใหม่"

TERMINAL_AUTH_ERROR_CODES = frozenset(
    {
        "invalid_token",
        "token_expired",
        "invalid_grant",
        "invalid_client",
        "account_suspended",
        "insufficient_scope",
    }
)

_RETRYABLE_ERROR_CODES = frozenset(
    {"rate_limited", "upstream_unavailable", "network_error", "timeout"}
)


class ProxyApiError(LauncherServiceError):
    """Sanitized Proxy API failure that never carries credentials."""

    def __init__(
        self,
        code: str,
        *,
        status: int | None = None,
        request_id: str | None = None,
        retryable: bool | None = None,
        user_message: str | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.request_id = _safe_request_id(request_id)
        self.retryable = (
            _default_retryable(code, status) if retryable is None else bool(retryable)
        )
        self.user_message = user_message or _message_for_code(code)
        super().__init__(self.user_message)

    @property
    def is_terminal_auth(self) -> bool:
        return self.code in TERMINAL_AUTH_ERROR_CODES


class ProxyApiTransportError(RuntimeError):
    """Transport-level failure; contains no request or response material."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProxyApiHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    document: dict[str, object] | None


@dataclass(frozen=True)
class ProxyApiTokenSet:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    token_type: str = "Bearer"
    scope: str = ""


@dataclass(frozen=True)
class ProxyAccountStatus:
    identity_user_id: str
    proxy_account_id: str
    status: str
    display_name: str

    def require_active(self) -> None:
        if self.status == "active":
            return
        if self.status == "pending":
            raise ProxyApiError("account_pending")
        raise ProxyApiError("account_suspended")


class ProxyApiTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object] | None,
        timeout: float,
    ) -> ProxyApiHttpResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UrllibProxyApiTransport:
    """HTTPS-only JSON transport with bounded response and no redirects."""

    def __init__(self, *, max_response_bytes: int = MAX_RESPONSE_BYTES) -> None:
        self._max_response_bytes = max_response_bytes
        self._opener = build_opener(_NoRedirectHandler())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object] | None,
        timeout: float,
    ) -> ProxyApiHttpResponse:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Proxy API transport requires HTTPS")
        body = None
        if payload is not None:
            body = json.dumps(
                payload, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                response_headers = {
                    str(key).lower(): str(value)
                    for key, value in response.headers.items()
                }
                raw = response.read(self._max_response_bytes + 1)
        except HTTPError as error:
            status = int(error.code)
            response_headers = (
                {str(key).lower(): str(value) for key, value in error.headers.items()}
                if error.headers is not None
                else {}
            )
            raw = error.read(self._max_response_bytes + 1)
        except (TimeoutError, socket.timeout) as error:
            raise ProxyApiTransportError("timeout") from error
        except URLError as error:
            reason = getattr(error, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise ProxyApiTransportError("timeout") from error
            raise ProxyApiTransportError("network_error") from error
        except (HTTPException, OSError) as error:
            raise ProxyApiTransportError("network_error") from error

        if len(raw) > self._max_response_bytes:
            raise ProxyApiTransportError("response_too_large")
        document: dict[str, object] | None = None
        if raw:
            try:
                parsed_document = json.loads(raw.decode("utf-8"))
                if isinstance(parsed_document, dict):
                    document = parsed_document
            except (UnicodeDecodeError, json.JSONDecodeError):
                document = None
        return ProxyApiHttpResponse(
            status=status,
            headers=response_headers,
            body=raw,
            document=document,
        )


class ProxyApiGateway:
    """Neko Proxy API v1 client plus identity refresh-token exchange."""

    def __init__(
        self,
        *,
        proxy_api_base_url: str,
        identity_base_url: str,
        timeout: float = HTTP_TIMEOUT_SECONDS,
        transport: ProxyApiTransport | None = None,
    ) -> None:
        self._proxy_api_base_url = _require_https_origin(
            proxy_api_base_url, "NEKO_PROXY_API_URL"
        )
        self._identity_base_url = _require_https_origin(
            identity_base_url, "NEKO_IDENTITY_BASE_URL"
        )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a positive number")
        if not 0 < float(timeout) <= 60:
            raise ValueError("timeout must be a positive number no greater than 60")
        self._timeout = float(timeout)
        self._transport = transport or UrllibProxyApiTransport()

    def get_me(self, access_token: str) -> ProxyAccountStatus:
        token = _require_bearer_value(access_token, "invalid_token")
        response = self._request(
            "GET",
            f"{self._proxy_api_base_url}{PROXY_ME_PATH}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status != 200:
            raise _error_from_response(response)
        return _parse_account_status(response)

    def refresh_access_token(self, refresh_token: str) -> ProxyApiTokenSet:
        token = _require_bearer_value(refresh_token, "invalid_grant")
        response = self._request(
            "POST",
            f"{self._identity_base_url}{IDENTITY_TOKEN_PATH}",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            payload={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": token,
            },
        )
        if response.status != 200:
            raise _error_from_response(response)
        return _parse_token_set(response)

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object] | None = None,
    ) -> ProxyApiHttpResponse:
        request_headers = {
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "User-Agent": f"NekoLauncher/{__version__}",
            **dict(headers),
        }
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        try:
            response = self._transport.request(
                method,
                url,
                headers=request_headers,
                payload=payload,
                timeout=self._timeout,
            )
        except ProxyApiTransportError as error:
            code = (
                error.code
                if error.code in {"timeout", "network_error"}
                else "network_error"
            )
            raise ProxyApiError(code, retryable=True) from None
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise ProxyApiError("invalid_response")
        return response


def _require_https_origin(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an HTTPS origin")
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{name} must be an HTTPS origin")
    return value.strip().rstrip("/")


def _require_bearer_value(value: object, invalid_code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_TOKEN_CHARS
        or not value.isascii()
    ):
        raise ProxyApiError(invalid_code)
    return value


def _parse_account_status(response: ProxyApiHttpResponse) -> ProxyAccountStatus:
    document = response.document
    if not isinstance(document, dict):
        raise ProxyApiError("invalid_response")
    identity_user_id = _required_text(
        document.get("identity_user_id"), 128
    )
    proxy_account_id = _required_text(
        document.get("proxy_account_id"), 128
    )
    status = _required_text(document.get("status"), MAX_STATUS_CHARS).lower()
    if status not in ALLOWED_ACCOUNT_STATUSES:
        raise ProxyApiError("invalid_response")
    display_name = _required_display_name(document.get("display_name"))
    return ProxyAccountStatus(
        identity_user_id=identity_user_id,
        proxy_account_id=proxy_account_id,
        status=status,
        display_name=display_name,
    )


def _parse_token_set(response: ProxyApiHttpResponse) -> ProxyApiTokenSet:
    document = response.document
    if not isinstance(document, dict):
        raise ProxyApiError("invalid_response")
    token_type = document.get("token_type")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise ProxyApiError("invalid_response")
    access_token = _required_token(document.get("access_token"))
    refresh_token = _required_token(document.get("refresh_token"))
    expires_in = document.get("expires_in")
    if (
        type(expires_in) is not int
        or expires_in <= 0
        or expires_in > 3_600
    ):
        raise ProxyApiError("invalid_response")
    scope = document.get("scope", "")
    if not isinstance(scope, str) or len(scope) > 512:
        raise ProxyApiError("invalid_response")
    return ProxyApiTokenSet(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        token_type="Bearer",
        scope=scope,
    )


def _required_token(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_TOKEN_CHARS
        or not value.isascii()
    ):
        raise ProxyApiError("invalid_response")
    return value


def _required_text(value: object, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
        or not value.isascii()
    ):
        raise ProxyApiError("invalid_response")
    return value.strip()


def _required_display_name(value: object) -> str:
    if not isinstance(value, str):
        raise ProxyApiError("invalid_response")
    display_name = value.strip()
    if (
        not display_name
        or len(display_name) > MAX_DISPLAY_NAME_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in display_name)
    ):
        raise ProxyApiError("invalid_response")
    return display_name


def _error_from_response(response: ProxyApiHttpResponse) -> ProxyApiError:
    document = response.document or {}
    code: str | None = None
    request_id: str | None = None
    retryable: bool | None = None
    error_value = document.get("error")
    if isinstance(error_value, dict):
        raw_code = error_value.get("code")
        if isinstance(raw_code, str) and raw_code:
            code = raw_code
        raw_request_id = error_value.get("request_id")
        if isinstance(raw_request_id, str):
            request_id = raw_request_id
        raw_retryable = error_value.get("retryable")
        if isinstance(raw_retryable, bool):
            retryable = raw_retryable
    elif isinstance(error_value, str) and error_value:
        code = error_value
    if code is None:
        code = _status_fallback_code(response.status)
    return ProxyApiError(
        code,
        status=response.status,
        request_id=request_id,
        retryable=retryable,
    )


def _status_fallback_code(status: int) -> str:
    if status == 401:
        return "invalid_token"
    if status == 403:
        return "insufficient_scope"
    if status == 429:
        return "rate_limited"
    if 500 <= status <= 599:
        return "upstream_unavailable"
    return "http_error"


def _default_retryable(code: str, status: int | None) -> bool:
    if code in _RETRYABLE_ERROR_CODES:
        return True
    return bool(status is not None and 500 <= status <= 599)


def _message_for_code(code: str) -> str:
    return (
        SHARED_ERROR_MESSAGES.get(code)
        or INTERNAL_ERROR_MESSAGES.get(code)
        or GENERIC_ERROR_MESSAGE
    )


def _safe_request_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    if not 1 <= len(value) <= 200:
        return None
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        return None
    return value
