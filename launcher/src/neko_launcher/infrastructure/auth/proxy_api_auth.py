from __future__ import annotations

from threading import RLock
from typing import Any

from neko_launcher.application.errors import LauncherServiceError
from neko_launcher.application.ports import SecureStore
from neko_launcher.domain.models import AuthenticatedUser, RegistrationResult

from .proxy_api_gateway import (
    MAX_TOKEN_CHARS,
    ProxyAccountStatus,
    ProxyApiError,
    ProxyApiGateway,
    ProxyApiTokenSet,
)

REFRESH_TOKEN_STORE_KEY = "proxy-api-refresh-token"
WEB_ONLY_MESSAGE = "5.3.0 ใช้การเข้าสู่ระบบผ่าน Discord เท่านั้น"
DEFAULT_DISPLAY_NAME = "Neko Family"


class ProxyApiTokenStore:
    """Stores only the rotating refresh token in the OS credential vault."""

    def __init__(
        self,
        secure_store: SecureStore,
        key: str = REFRESH_TOKEN_STORE_KEY,
    ) -> None:
        self._secure_store = secure_store
        self._key = key

    def load(self) -> str | None:
        try:
            value = self._secure_store.read(self._key)
        except Exception:
            raise ProxyApiError("credential_store_unavailable") from None
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_TOKEN_CHARS
            or not value.isascii()
        ):
            try:
                self._secure_store.delete(self._key)
            except Exception:
                pass
            return None
        return value

    def save(self, refresh_token: str) -> None:
        if (
            not isinstance(refresh_token, str)
            or not refresh_token
            or len(refresh_token) > MAX_TOKEN_CHARS
            or not refresh_token.isascii()
        ):
            raise ProxyApiError("invalid_response")
        try:
            self._secure_store.write(self._key, refresh_token)
        except Exception:
            raise ProxyApiError("credential_store_unavailable") from None

    def clear(self) -> None:
        try:
            self._secure_store.delete(self._key)
        except Exception:
            raise ProxyApiError("credential_store_unavailable") from None


class ProxyApiAuthGateway:
    """Web-auth gateway for the source-only Neko Proxy API line.

    The access token lives in memory only. Only the refresh token is persisted,
    under a new credential-vault key; no Supabase session is created.
    """

    def __init__(
        self,
        client: ProxyApiGateway,
        token_store: ProxyApiTokenStore,
    ) -> None:
        self._client = client
        self._token_store = token_store
        self._lock = RLock()
        self._access_token: str | None = None
        self._account_status: ProxyAccountStatus | None = None

    @property
    def account_status(self) -> ProxyAccountStatus | None:
        with self._lock:
            return self._account_status

    def sign_up(
        self,
        username: str,
        password: str,
    ) -> RegistrationResult:
        raise LauncherServiceError(WEB_ONLY_MESSAGE)

    def sign_in(self, username: str, password: str) -> AuthenticatedUser:
        raise LauncherServiceError(WEB_ONLY_MESSAGE)

    def sign_in_with_web(self, authenticator: Any) -> AuthenticatedUser:
        authenticate = getattr(authenticator, "authenticate_identity", None)
        if not callable(authenticate):
            raise LauncherServiceError(
                "ไคลเอนต์ล็อกอินไม่รองรับการเชื่อมต่อ Proxy API"
            )
        identity_session = authenticate()
        tokens = _identity_tokens(identity_session)
        with self._lock:
            try:
                self._token_store.save(tokens.refresh_token)
                self._access_token = tokens.access_token
                status = self._preflight_locked(tokens.access_token)
                status.require_active()
            except Exception:
                self._clear_all_locked()
                raise
            self._account_status = status
            return AuthenticatedUser(
                user_id=status.identity_user_id,
                email=status.display_name or DEFAULT_DISPLAY_NAME,
            )

    def restore_session(self) -> AuthenticatedUser | None:
        with self._lock:
            try:
                refresh_token = self._token_store.load()
            except ProxyApiError:
                return None
            if not refresh_token:
                return None
            try:
                tokens = self._exchange_refresh_locked(refresh_token)
                status = self._client.get_me(tokens.access_token)
                status.require_active()
            except ProxyApiError as error:
                self._clear_memory_locked()
                if error.is_terminal_auth:
                    self._clear_store_quietly()
                return None
            except Exception:
                self._clear_memory_locked()
                return None
            self._account_status = status
            return AuthenticatedUser(
                user_id=status.identity_user_id,
                email=status.display_name or DEFAULT_DISPLAY_NAME,
            )

    def change_password(self, password: str) -> None:
        raise LauncherServiceError(WEB_ONLY_MESSAGE)

    def auth_identifier_for_username(self, username: str) -> str:
        raise LauncherServiceError(WEB_ONLY_MESSAGE)

    def sign_out(self) -> None:
        with self._lock:
            self._clear_memory_locked()
            self._token_store.clear()

    def clear_local_session(self) -> None:
        with self._lock:
            self._clear_memory_locked()
            self._clear_store_quietly()

    def access_token(self) -> str:
        with self._lock:
            if not self._access_token:
                raise ProxyApiError("invalid_token")
            return self._access_token

    def refresh_access_token(self) -> str:
        with self._lock:
            return self._refresh_locked().access_token

    def _preflight_locked(self, access_token: str) -> ProxyAccountStatus:
        try:
            return self._client.get_me(access_token)
        except ProxyApiError as error:
            if error.code not in {"invalid_token", "token_expired"}:
                raise
            tokens = self._refresh_locked()
            return self._client.get_me(tokens.access_token)

    def _refresh_locked(self) -> ProxyApiTokenSet:
        refresh_token = self._token_store.load()
        if not refresh_token:
            raise ProxyApiError("invalid_grant")
        return self._exchange_refresh_locked(refresh_token)

    def _exchange_refresh_locked(
        self,
        refresh_token: str,
    ) -> ProxyApiTokenSet:
        try:
            tokens = self._client.refresh_access_token(refresh_token)
        except ProxyApiError:
            self._clear_memory_locked()
            self._clear_store_quietly()
            raise
        try:
            self._token_store.save(tokens.refresh_token)
        except ProxyApiError:
            self._clear_memory_locked()
            self._clear_store_quietly()
            raise
        self._access_token = tokens.access_token
        return tokens

    def _clear_memory_locked(self) -> None:
        self._access_token = None
        self._account_status = None

    def _clear_store_quietly(self) -> None:
        try:
            self._token_store.clear()
        except ProxyApiError:
            pass

    def _clear_all_locked(self) -> None:
        self._clear_memory_locked()
        self._clear_store_quietly()


def _identity_tokens(identity_session: Any) -> ProxyApiTokenSet:
    access_token = getattr(identity_session, "access_token", None)
    refresh_token = getattr(identity_session, "refresh_token", None)
    expires_in = getattr(identity_session, "expires_in", None)
    if (
        not isinstance(access_token, str)
        or not access_token
        or len(access_token) > MAX_TOKEN_CHARS
        or not access_token.isascii()
        or not isinstance(refresh_token, str)
        or not refresh_token
        or len(refresh_token) > MAX_TOKEN_CHARS
        or not refresh_token.isascii()
        or type(expires_in) is not int
        or expires_in <= 0
        or expires_in > 3_600
    ):
        raise LauncherServiceError("คำตอบจากระบบล็อกอินไม่ถูกต้อง")
    return ProxyApiTokenSet(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )
