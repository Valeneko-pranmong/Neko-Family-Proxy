from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from neko_launcher.application.diagnostics import (
    SupportEventSink,
    safe_exception_fields,
)
from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.domain.models import AuthPhase
from neko_launcher.infrastructure.auth.proxy_api_gateway import (
    PROXY_CLAIM_PATH,
    PROXY_LAUNCHER_CLIENT_ID,
    PROXY_ME_PATH,
)

DEFAULT_IDENTITY_BASE_URL = "https://neko-network-id.vercel.app"
AUTHORIZE_PATH = "/launcher/authorize"
TOKEN_PATH = "/api/launcher/token"
LEGACY_LAUNCHER_CLIENT_ID = "neko-launcher"
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 53682
LOOPBACK_PATH = "/auth/callback"
CALLBACK_TIMEOUT_SECONDS = 120.0
HTTP_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 65_536
MAX_OPAQUE_CODE_CHARS = 4096
MAX_TOKEN_CHARS = 16_384
PREWARM_TIMEOUT_SECONDS = 3.0
PREWARM_MAX_RESPONSE_BYTES = 4096

T = TypeVar("T")


class WebAuthError(LauncherServiceError):
    """User-safe web authentication failure."""

    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class PkceChallenge:
    verifier: str
    challenge: str
    state: str


@dataclass(frozen=True)
class CallbackResult:
    code: str | None
    error: str | None


@dataclass(frozen=True)
class BridgeSession:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


@dataclass(frozen=True)
class IdentityTokenSet:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    token_type: str = "Bearer"
    scope: str = ""


@dataclass(frozen=True)
class JsonResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    document: dict[str, Any] | None


class JsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float,
    ) -> JsonResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class UrllibJsonTransport:
    """HTTPS JSON transport with a bounded response and no redirect following."""

    def __init__(self, *, max_response_bytes: int = MAX_RESPONSE_BYTES) -> None:
        self._max_response_bytes = max_response_bytes
        self._opener = build_opener(_NoRedirectHandler())

    def post_json(
        self,
        url: str,
        payload: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float,
    ) -> JsonResponse:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise WebAuthError(
                "การเข้าสู่ระบบต้องใช้การเชื่อมต่อที่ปลอดภัย",
                code="insecure_endpoint",
            )
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "User-Agent": "NekoLauncherWebAuth/1",
            **dict(headers),
        }
        request = Request(url, data=body, headers=request_headers, method="POST")
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
        except (URLError, TimeoutError, OSError) as error:
            raise WebAuthError(
                "เชื่อมต่อระบบไม่ได้ กรุณาตรวจสอบอินเทอร์เน็ตแล้วลองใหม่",
                code="network_error",
                retryable=True,
            ) from error

        if len(raw) > self._max_response_bytes:
            raise WebAuthError(
                "ระบบตอบกลับไม่สมบูรณ์ กรุณาลองใหม่",
                code="response_too_large",
            )
        document: dict[str, Any] | None = None
        if raw:
            try:
                parsed_document = json.loads(raw.decode("utf-8"))
                if isinstance(parsed_document, dict):
                    document = parsed_document
            except (UnicodeDecodeError, json.JSONDecodeError):
                document = None
        return JsonResponse(
            status=status,
            headers=response_headers,
            body=raw,
            document=document,
        )


def generate_pkce() -> PkceChallenge:
    verifier = secrets.token_urlsafe(64)
    if not 43 <= len(verifier) <= 128:
        raise WebAuthError("เตรียมการเข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่", code="pkce_error")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(32)
    return PkceChallenge(verifier=verifier, challenge=challenge, state=state)


def build_authorize_url(
    identity_base_url: str,
    redirect_uri: str,
    pkce: PkceChallenge,
    *,
    client_id: str,
) -> str:
    base = _normalized_https_base(identity_base_url)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": pkce.state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{base}{AUTHORIZE_PATH}?{query}"


def _normalized_https_base(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise WebAuthError(
            "ระบบตั้งค่าการเข้าสู่ระบบไม่ถูกต้อง กรุณาติดต่อผู้ดูแล",
            code="identity_endpoint_invalid",
        )
    return value.rstrip("/")


def _prewarm_targets(
    identity_base_url: str,
    proxy_api_base_url: str,
) -> list[tuple[str, str, bytes | None]]:
    try:
        identity_base = _normalized_https_base(identity_base_url)
    except WebAuthError:
        return []
    targets: list[tuple[str, str, bytes | None]] = [
        (f"{identity_base}{TOKEN_PATH}", "POST", b"{}"),
    ]
    if proxy_api_base_url:
        parsed = urlparse(proxy_api_base_url)
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        ):
            proxy_base = proxy_api_base_url.rstrip("/")
            targets.append((f"{proxy_base}{PROXY_ME_PATH}", "GET", None))
            targets.append((f"{proxy_base}{PROXY_CLAIM_PATH}", "POST", b"{}"))
    return targets


def _send_prewarm_request(
    url: str,
    method: str,
    body: bytes | None,
    opener: Any,
    timeout: float,
) -> None:
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-store",
        "User-Agent": "NekoLauncherWarmup/1",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(PREWARM_MAX_RESPONSE_BYTES)
    except Exception:
        pass


def prewarm_login_stack(
    identity_base_url: str,
    proxy_api_base_url: str = "",
    *,
    opener: Any = None,
    timeout: float = PREWARM_TIMEOUT_SECONDS,
) -> threading.Thread | None:
    """Wake the auth endpoints while the browser/Discord step is in progress."""
    targets = _prewarm_targets(identity_base_url, proxy_api_base_url)
    if not targets:
        return None

    def run() -> None:
        workers = [
            threading.Thread(
                target=_send_prewarm_request,
                args=(
                    url,
                    method,
                    body,
                    opener if opener is not None else build_opener(),
                    timeout,
                ),
                daemon=True,
            )
            for url, method, body in targets
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout + 1.0)

    thread = threading.Thread(
        target=run,
        name="neko-auth-prewarm",
        daemon=True,
    )
    thread.start()
    return thread


class _LoopbackHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


class LoopbackCallbackServer:
    """Single-use loopback callback receiver bound to 127.0.0.1."""

    def __init__(
        self,
        *,
        expected_state: str,
        port: int = LOOPBACK_PORT,
        path: str = LOOPBACK_PATH,
        host: str = LOOPBACK_HOST,
    ) -> None:
        self._expected_state = expected_state
        self._host = host
        self._path = path
        self._requested_port = port
        self._server: _LoopbackHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._result: CallbackResult | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("loopback server has not started")
        return int(self._server.server_address[1])

    @property
    def redirect_uri(self) -> str:
        return f"http://{self._host}:{self.port}{self._path}"

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "NekoLauncherWebAuth/1"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802
                owner._handle(self)

            def log_message(self, _format: str, *args: object) -> None:
                del args

        try:
            self._server = _LoopbackHTTPServer((self._host, self._requested_port), Handler)
        except OSError as error:
            raise WebAuthError(
                "มีโปรแกรมอื่นใช้งานช่องรับผลการเข้าสู่ระบบอยู่ กรุณาปิดโปรแกรมดังกล่าวแล้วลองใหม่",
                code="loopback_port_unavailable",
                retryable=True,
            ) from error

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="neko-web-auth-loopback",
            daemon=True,
        )
        self._thread.start()

    def wait(self, timeout: float) -> CallbackResult:
        deadline = time.monotonic() + timeout
        while True:
            if self._cancelled.is_set():
                raise WebAuthError(
                    "ยกเลิกการเข้าสู่ระบบแล้ว",
                    code="cancelled",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WebAuthError(
                    "หมดเวลารอการเข้าสู่ระบบผ่านเว็บ กรุณาลองใหม่",
                    code="callback_timeout",
                    retryable=True,
                )
            if self._done.wait(min(0.1, remaining)):
                break
        if self._cancelled.is_set():
            raise WebAuthError("ยกเลิกการเข้าสู่ระบบแล้ว", code="cancelled")
        with self._lock:
            result = self._result
        if result is None:
            raise WebAuthError(
                "ไม่ได้รับการยืนยันจากเบราว์เซอร์ กรุณาลองใหม่",
                code="callback_missing",
            )
        return result

    def cancel(self) -> None:
        self._cancelled.set()
        self._done.set()

    def close(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        if len(handler.path) > MAX_OPAQUE_CODE_CHARS + 1024:
            self._respond(handler, 414, "คำขอยาวเกินไป")
            return
        parsed = urlsplit(handler.path)
        if parsed.path != self._path:
            self._respond(handler, 404, "ไม่พบหน้าที่ร้องขอ")
            return
        expected_host = f"{self._host}:{self.port}"
        if handler.headers.get("Host") != expected_host:
            self._respond(handler, 400, "คำขอไม่ถูกต้อง")
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        if any(len(values) != 1 for values in query.values()):
            self._respond(handler, 400, "คำขอไม่ถูกต้อง")
            return
        state = query.get("state", [""])[0]
        if not hmac.compare_digest(state, self._expected_state):
            self._respond(handler, 400, "สถานะการเข้าสู่ระบบไม่ถูกต้อง")
            return

        error = query.get("error", [None])[0]
        if error is not None:
            if not self._record(CallbackResult(code=None, error=error)):
                self._respond(handler, 409, "คำขอนี้ถูกใช้ไปแล้ว")
                return
            self._respond(handler, 200, "การเข้าสู่ระบบไม่สำเร็จ คุณสามารถปิดหน้าต่างนี้ได้")
            return

        code = query.get("code", [None])[0]
        if (
            not isinstance(code, str)
            or not code
            or len(code) > MAX_OPAQUE_CODE_CHARS
            or not code.isascii()
            or any(character.isspace() for character in code)
        ):
            self._respond(handler, 400, "รหัสยืนยันไม่ถูกต้อง")
            return
        if not self._record(CallbackResult(code=code, error=None)):
            self._respond(handler, 409, "คำขอนี้ถูกใช้ไปแล้ว")
            return
        self._respond(handler, 200, "เข้าสู่ระบบสำเร็จ คุณสามารถปิดหน้าต่างนี้ได้")

    def _record(self, result: CallbackResult) -> bool:
        with self._lock:
            if self._result is not None:
                return False
            self._result = result
        self._done.set()
        return True

    def _respond(
        self, handler: BaseHTTPRequestHandler, status: int, message: str
    ) -> None:
        body = (
            "<!doctype html><html lang=\"th\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Neko Family Proxy</title></head><body>"
            f"<p>{message}</p></body></html>"
        ).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Pragma", "no-cache")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'",
        )
        handler.end_headers()
        handler.wfile.write(body)
        handler.close_connection = True


class WebAuthClient:
    """Browser login with PKCE, loopback callback, identity token, and bridge session."""

    def __init__(
        self,
        *,
        identity_base_url: str = DEFAULT_IDENTITY_BASE_URL,
        bridge_exchange_url: str,
        loopback_port: int = LOOPBACK_PORT,
        callback_timeout: float = CALLBACK_TIMEOUT_SECONDS,
        http_timeout: float = HTTP_TIMEOUT_SECONDS,
        transport: JsonTransport | None = None,
        browser_opener: Callable[[str], bool] | None = None,
        event_sink: SupportEventSink | None = None,
    ) -> None:
        self._identity_base_url = _normalized_https_base(identity_base_url)
        self._bridge_exchange_url = bridge_exchange_url.strip()
        if self._bridge_exchange_url:
            bridge = urlparse(self._bridge_exchange_url)
            if (
                bridge.scheme != "https"
                or not bridge.hostname
                or bridge.query
                or bridge.fragment
            ):
                raise WebAuthError(
                    "ระบบตั้งค่าการเชื่อมบัญชีไม่ถูกต้อง กรุณาติดต่อผู้ดูแล",
                    code="bridge_endpoint_invalid",
                )
        self._loopback_port = loopback_port
        self._callback_timeout = callback_timeout
        self._http_timeout = http_timeout
        self._transport = transport or UrllibJsonTransport()
        self._browser_opener = browser_opener or webbrowser.open
        self._event_sink = event_sink
        self._active = threading.Lock()
        self._cancelled = threading.Event()
        self._server: LoopbackCallbackServer | None = None
        self._teardown: threading.Thread | None = None
        self._observer_lock = threading.Lock()
        self._progress_observer: Callable[[AuthPhase], None] | None = None
        self._flow_started_at: float | None = None
        self._flow_phase_started_at: float | None = None

    def _support_event(self, event: str, **fields: Any) -> None:
        sink = self._event_sink
        if sink is None:
            return
        try:
            sink.record_event("AUTH", event, **fields)
        except Exception:
            pass

    @staticmethod
    def _elapsed_ms(started_at: float | None) -> int | None:
        if started_at is None:
            return None
        return max(0, int((time.monotonic() - started_at) * 1000))

    def attach_progress_observer(
        self,
        observer: Callable[[AuthPhase], None] | None,
    ) -> None:
        """Register a listener for customer-visible sign-in steps (worker thread)."""
        with self._observer_lock:
            self._progress_observer = observer

    def _emit_progress(self, phase: AuthPhase) -> None:
        now = time.monotonic()
        phase_elapsed = self._elapsed_ms(self._flow_phase_started_at)
        self._flow_phase_started_at = now
        self._support_event(
            "FLOW_PHASE",
            phase=phase.value,
            elapsed_ms=self._elapsed_ms(self._flow_started_at),
            phase_elapsed_ms=phase_elapsed,
        )
        with self._observer_lock:
            observer = self._progress_observer
        if observer is None:
            return
        try:
            observer(phase)
        except Exception:
            pass

    def authenticate(self) -> BridgeSession:
        if not self._bridge_exchange_url:
            raise WebAuthError(
                "ยังไม่ได้เปิดให้เข้าสู่ระบบด้วย Discord กรุณาติดต่อผู้ดูแล",
                code="bridge_not_configured",
            )
        return self._authenticate_flow(
            client_id=LEGACY_LAUNCHER_CLIENT_ID,
            require_refresh=False,
            finalize=lambda tokens: self._exchange_bridge(tokens.access_token),
        )

    def authenticate_identity(self) -> IdentityTokenSet:
        """Return identity tokens without the legacy bridge/session exchange."""
        return self._authenticate_flow(
            client_id=PROXY_LAUNCHER_CLIENT_ID,
            require_refresh=True,
            finalize=lambda tokens: tokens,
        )

    def _authenticate_flow(
        self,
        *,
        client_id: str,
        require_refresh: bool,
        finalize: Callable[[IdentityTokenSet], T],
    ) -> T:
        if not self._active.acquire(blocking=False):
            raise WebAuthError(
                "กำลังเข้าสู่ระบบอยู่ กรุณารอสักครู่",
                code="already_in_progress",
            )
        server: LoopbackCallbackServer | None = None
        try:
            self._cancelled.clear()
            self._flow_started_at = time.monotonic()
            self._flow_phase_started_at = None
            self._support_event(
                "FLOW_STARTED",
                mode="identity" if require_refresh else "bridge",
            )
            self._await_previous_teardown()
            pkce = generate_pkce()
            server = LoopbackCallbackServer(
                expected_state=pkce.state,
                port=self._loopback_port,
            )
            self._server = server
            server.start()
            self._support_event(
                "LOOPBACK_READY",
                port=server.port,
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
            )
            redirect_uri = server.redirect_uri
            authorize_url = build_authorize_url(
                self._identity_base_url,
                redirect_uri,
                pkce,
                client_id=client_id,
            )
            self._emit_progress(AuthPhase.OPENING_BROWSER)
            try:
                opened = self._browser_opener(authorize_url)
            except (OSError, RuntimeError) as error:
                raise WebAuthError(
                    "เปิดเบราว์เซอร์ไม่สำเร็จ กรุณาลองใหม่",
                    code="browser_open_failed",
                    retryable=True,
                ) from error
            if opened is False:
                raise WebAuthError(
                    "เปิดเบราว์เซอร์ไม่สำเร็จ กรุณาลองใหม่",
                    code="browser_open_failed",
                    retryable=True,
                )
            self._support_event(
                "BROWSER_OPENED",
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
            )

            self._emit_progress(AuthPhase.WAITING_FOR_BROWSER)
            callback = server.wait(self._callback_timeout)
            self._support_event(
                "CALLBACK_RECEIVED",
                code_present=bool(callback.code),
                error_present=callback.error is not None,
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
            )
            if self._cancelled.is_set():
                raise WebAuthError("ยกเลิกการเข้าสู่ระบบแล้ว", code="cancelled")
            if callback.error is not None:
                raise self._callback_error(callback.error)
            if not callback.code:
                raise WebAuthError(
                    "ไม่ได้รับการยืนยันจากเบราว์เซอร์ กรุณาลองใหม่",
                    code="callback_missing",
                )

            self._release_loopback_async(server)
            server = None
            self._emit_progress(AuthPhase.CONNECTING)
            self._support_event(
                "TOKEN_EXCHANGE_STARTED",
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
            )
            tokens = self._exchange_identity_code_tokens(
                callback.code,
                pkce.verifier,
                redirect_uri,
                client_id=client_id,
                require_refresh=require_refresh,
            )
            self._support_event(
                "TOKEN_EXCHANGE_SUCCEEDED",
                expires_in=tokens.expires_in,
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
            )
            if self._cancelled.is_set():
                raise WebAuthError("ยกเลิกการเข้าสู่ระบบแล้ว", code="cancelled")
            result = finalize(tokens)
            self._support_event(
                "FLOW_SUCCEEDED",
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
            )
            return result
        except WebAuthError as error:
            self._support_event(
                "FLOW_FAILED",
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
                **safe_exception_fields(error),
            )
            raise
        except Exception as error:
            self._support_event(
                "FLOW_FAILED",
                elapsed_ms=self._elapsed_ms(self._flow_started_at),
                **safe_exception_fields(error),
            )
            raise
        finally:
            self._server = None
            if server is not None:
                server.close()
            self._flow_started_at = None
            self._flow_phase_started_at = None
            self._active.release()

    def _await_previous_teardown(self) -> None:
        """The loopback port is exclusive, so never start over a live teardown."""
        teardown = self._teardown
        if teardown is not None:
            if teardown.is_alive():
                teardown.join(timeout=1.0)
            self._teardown = None

    def _release_loopback_async(self, server: LoopbackCallbackServer) -> None:
        """Shut the callback listener down off the critical path.

        The authorisation code is already captured, so waiting for the browser's
        connection to drain here is what kept the login screen frozen after the
        browser reported success.
        """
        self._server = None
        teardown = threading.Thread(
            target=server.close,
            name="neko-web-auth-teardown",
            daemon=True,
        )
        self._teardown = teardown
        teardown.start()

    def cancel(self) -> None:
        self._cancelled.set()
        server = self._server
        if server is not None:
            server.cancel()

    def _exchange_identity_code_tokens(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        *,
        client_id: str,
        require_refresh: bool,
    ) -> IdentityTokenSet:
        response = self._transport.post_json(
            f"{self._identity_base_url}{TOKEN_PATH}",
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
            {},
            self._http_timeout,
        )
        if response.status != 200:
            raise self._identity_http_error(response)
        document = response.document or {}
        token_type = document.get("token_type")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise WebAuthError(
                "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่",
                code="invalid_token_response",
            )
        access_token = document.get("access_token")
        if (
            not isinstance(access_token, str)
            or not access_token
            or len(access_token) > MAX_TOKEN_CHARS
        ):
            raise WebAuthError(
                "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่",
                code="invalid_token_response",
            )
        refresh_token = document.get("refresh_token")
        if require_refresh:
            if (
                not isinstance(refresh_token, str)
                or not refresh_token
                or len(refresh_token) > MAX_TOKEN_CHARS
            ):
                raise WebAuthError(
                    "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่",
                    code="invalid_token_response",
                )
        else:
            refresh_token = ""
        expires_in = document.get("expires_in")
        if (
            type(expires_in) is not int
            or expires_in <= 0
            or expires_in > 3600
        ):
            raise WebAuthError(
                "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่",
                code="invalid_token_response",
            )
        scope = document.get("scope", "")
        if not isinstance(scope, str) or len(scope) > 512:
            raise WebAuthError(
                "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่",
                code="invalid_token_response",
            )
        return IdentityTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            token_type="Bearer",
            scope=scope,
        )

    def _exchange_bridge(self, identity_token: str) -> BridgeSession:
        response = self._transport.post_json(
            self._bridge_exchange_url,
            {},
            {"Authorization": f"Bearer {identity_token}"},
            self._http_timeout,
        )
        if response.status != 200:
            raise self._bridge_http_error(response)
        document = response.document or {}
        token_type = document.get("token_type")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise WebAuthError(
                "เชื่อมบัญชีไม่สำเร็จ กรุณาลองใหม่",
                code="invalid_bridge_response",
            )
        access_token = document.get("access_token")
        refresh_token = document.get("refresh_token")
        if (
            not isinstance(access_token, str)
            or not access_token
            or len(access_token) > MAX_TOKEN_CHARS
            or not isinstance(refresh_token, str)
            or not refresh_token
            or len(refresh_token) > MAX_TOKEN_CHARS
        ):
            raise WebAuthError(
                "เชื่อมบัญชีไม่สำเร็จ กรุณาลองใหม่",
                code="invalid_bridge_response",
            )
        expires_in = document.get("expires_in", 0)
        if type(expires_in) is not int or expires_in < 0:
            raise WebAuthError(
                "เชื่อมบัญชีไม่สำเร็จ กรุณาลองใหม่",
                code="invalid_bridge_response",
            )
        return BridgeSession(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            token_type="Bearer",
        )

    @staticmethod
    def _callback_error(error: str) -> WebAuthError:
        if error == "access_denied":
            return WebAuthError(
                "คุณยกเลิกการเข้าสู่ระบบ หรือบัญชี Discord ถูกระงับ",
                code="access_denied",
            )
        if error == "server_error":
            return WebAuthError(
                "ระบบขัดข้องชั่วคราว กรุณาลองใหม่",
                code="server_error",
                retryable=True,
            )
        return WebAuthError(
            "การเข้าสู่ระบบผ่านเว็บไม่สำเร็จ กรุณาลองใหม่",
            code="callback_error",
            retryable=True,
        )

    @staticmethod
    def _identity_http_error(response: JsonResponse) -> WebAuthError:
        document = response.document or {}
        error = document.get("error")
        if response.status == 400 and error == "invalid_grant":
            return WebAuthError(
                "รหัสยืนยันหมดอายุหรือถูกใช้แล้ว กรุณาเข้าสู่ระบบใหม่",
                code="invalid_grant",
            )
        if response.status == 400:
            return WebAuthError(
                "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
                code="invalid_request",
            )
        if response.status == 401:
            return WebAuthError(
                "โปรแกรมนี้ไม่ได้รับอนุญาตให้เข้าสู่ระบบ กรุณาติดต่อผู้ดูแล",
                code="invalid_client",
            )
        if response.status == 429:
            return WebAuthError(
                "พยายามเข้าสู่ระบบบ่อยเกินไป กรุณารอสักครู่",
                code="rate_limited",
                retryable=True,
            )
        if response.status >= 500:
            return WebAuthError(
                "ระบบขัดข้องชั่วคราว กรุณาลองใหม่",
                code="server_error",
                retryable=True,
            )
        return WebAuthError(
            "การเข้าสู่ระบบผ่านเว็บไม่สำเร็จ กรุณาลองใหม่",
            code="identity_error",
            retryable=True,
        )

    @staticmethod
    def _bridge_http_error(response: JsonResponse) -> WebAuthError:
        document = response.document or {}
        error = document.get("error")
        if response.status == 401:
            return WebAuthError(
                "ข้อมูลเข้าสู่ระบบไม่ถูกต้อง กรุณาเข้าสู่ระบบใหม่",
                code="invalid_token",
            )
        if response.status == 409 and error == "token_replayed":
            return WebAuthError(
                "ข้อมูลเข้าสู่ระบบถูกใช้แล้ว กรุณาเข้าสู่ระบบใหม่",
                code="token_replayed",
            )
        if response.status == 409 and error == "identity_not_linked":
            return WebAuthError(
                "บัญชี Discord นี้ยังไม่ได้เชื่อมกับบัญชี Neko Family",
                code="identity_not_linked",
            )
        if response.status == 429:
            return WebAuthError(
                "พยายามเข้าสู่ระบบบ่อยเกินไป กรุณารอสักครู่",
                code="rate_limited",
                retryable=True,
            )
        if response.status >= 500:
            return WebAuthError(
                "ระบบเชื่อมบัญชีไม่พร้อมใช้งาน กรุณาลองใหม่",
                code="bridge_unavailable",
                retryable=True,
            )
        return WebAuthError(
            "เชื่อมบัญชี Discord ไม่สำเร็จ กรุณาลองใหม่",
            code="bridge_error",
            retryable=True,
        )
