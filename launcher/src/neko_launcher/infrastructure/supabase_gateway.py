from __future__ import annotations

from datetime import datetime
from typing import Any

from supabase import Client, ClientOptions, create_client

from neko_launcher.application.errors import (
    EntitlementUnavailable,
    LauncherServiceError,
)
from neko_launcher.application.ports import AuthGateway, EntitlementGateway, SecureStore
from neko_launcher.domain.models import (
    AuthenticatedUser,
    CouponRedemption,
    Entitlement,
    EntitlementStatus,
    RegistrationResult,
    SessionClaim,
)

from .secure_store import SupabaseAuthStorage


class SupabaseGateway(AuthGateway, EntitlementGateway):
    """Supabase Auth and launcher-schema RPC adapter using a publishable key."""

    def __init__(
        self,
        url: str,
        publishable_key: str,
        secure_store: SecureStore,
        client: Client | None = None,
    ) -> None:
        if not url or not publishable_key:
            raise ValueError("Supabase URL and publishable key are required")
        self._client = client or create_client(
            url,
            publishable_key,
            options=ClientOptions(
                schema="launcher",
                storage=SupabaseAuthStorage(secure_store),
                auto_refresh_token=True,
                persist_session=True,
            ),
        )

    def sign_up(self, username: str, password: str, email: str) -> RegistrationResult:
        username = username.strip().lower()
        email = email.strip().lower()
        try:
            response = self._client.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                    "options": {
                        "data": {
                            "username": username,
                            "display_name": username,
                            "recovery_email": email,
                        }
                    },
                }
            )
        except Exception as exc:
            raise self._auth_error(exc, "สมัครสมาชิกไม่สำเร็จ")

        user = self._to_user(response.user) if response.user else None
        return RegistrationResult(
            email=username,
            requires_email_confirmation=False,
            user=user if response.session is not None else None,
        )

    def sign_in(self, username: str, password: str) -> AuthenticatedUser:
        username = username.strip().lower()
        if not self.user_exists(username):
            raise LauncherServiceError(
                "ไม่พบบัญชีนี้ กรุณาตรวจสอบชื่อผู้ใช้หรือสมัครสมาชิกก่อน"
            )
        email = self._auth_email_for_username(username)
        try:
            response = self._client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:
            raise self._auth_error(exc, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        if response.user is None or response.session is None:
            raise LauncherServiceError("เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่")
        return self._to_user(response.user)

    def request_password_reset(self, email: str) -> None:
        try:
            self._client.auth.reset_password_for_email(email.strip().lower())
        except Exception as exc:
            raise self._auth_error(
                exc,
                "ส่งลิงก์ไม่สำเร็จ กรุณาตรวจสอบอีเมลและลองใหม่",
            ) from exc

    def user_exists(self, username: str) -> bool:
        """Ask the launcher API/database whether a username is registered.

        The RPC returns only a boolean.  Password verification remains in
        Supabase Auth, so this lookup never reads credentials or user rows.
        """
        username = username.strip().lower()
        try:
            response = (
                self._client.schema("launcher")
                .rpc("user_exists", {"p_username": username})
                .execute()
            )
        except Exception as exc:
            raise self._rpc_error(
                exc,
                "ตรวจสอบบัญชีไม่ได้ชั่วคราว กรุณาลองใหม่",
            ) from exc
        return response.data is True

    def change_password(self, password: str) -> None:
        try:
            response = self._client.auth.update_user({"password": password})
        except Exception as exc:
            raise self._auth_error(
                exc,
                "เปลี่ยนรหัสผ่านไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
            )
        if getattr(response, "user", None) is None:
            raise LauncherServiceError("กรุณาเข้าสู่ระบบใหม่แล้วลองอีกครั้ง")

    def restore_session(self) -> AuthenticatedUser | None:
        try:
            session = self._client.auth.get_session()
            if session is None:
                return None
            response = self._client.auth.get_user()
        except Exception:
            return None
        return self._to_user(response.user) if response.user else None

    def sign_out(self) -> None:
        try:
            self._client.auth.sign_out()
        except Exception as exc:
            raise self._auth_error(exc, "ออกจากระบบไม่สำเร็จ")

    def claim_session(
        self,
        product_code: str,
        installation_key_hash: str,
        display_name: str,
    ) -> SessionClaim:
        try:
            response = (
                self._client.schema("launcher")
                .rpc(
                    "claim_session",
                    {
                        "p_product_code": product_code,
                        "p_installation_key_hash": installation_key_hash,
                        "p_display_name": display_name,
                    },
                )
                .execute()
            )
        except Exception as exc:
            if self._contains_error(exc, "license_invalid"):
                raise EntitlementUnavailable(
                    "บัญชีนี้ยังไม่มีวันใช้งาน กรุณาเติมคูปองก่อน"
                ) from exc
            raise self._rpc_error(exc, "ตรวจสอบวันใช้งานไม่ได้ กรุณาลองใหม่")

        data = self._as_dict(response.data)
        valid_until = self._parse_datetime(data.get("valid_until"))
        return SessionClaim(
            session_id=self._required_text(data, "session_id"),
            entitlement=Entitlement(
                product_code=str(data.get("product_code") or product_code),
                status=EntitlementStatus.ACTIVE,
                valid_until=valid_until,
                max_devices=int(data.get("max_devices") or 1),
            ),
        )

    def heartbeat_session(self, session_id: str) -> bool:
        try:
            response = (
                self._client.schema("launcher")
                .rpc("heartbeat_session", {"p_session_id": session_id})
                .execute()
            )
        except Exception as exc:
            raise self._rpc_error(exc, "ตรวจสอบการเชื่อมต่อไม่ได้ กรุณาลองใหม่")
        return response.data is True

    def release_session(self, session_id: str) -> bool:
        try:
            response = (
                self._client.schema("launcher")
                .rpc("release_session", {"p_session_id": session_id})
                .execute()
            )
        except Exception:
            return False
        return response.data is True

    def redeem_coupon(self, code: str) -> CouponRedemption:
        try:
            response = (
                self._client.schema("launcher")
                .rpc("redeem_coupon", {"p_code": code})
                .execute()
            )
        except Exception as exc:
            raise self._rpc_error(exc, "ใช้คูปองไม่สำเร็จ")

        data = self._as_dict(response.data)
        if not data.get("ok"):
            raise LauncherServiceError(
                {
                    "invalid_coupon": "คูปองไม่ถูกต้องหรือใช้งานไม่ได้",
                    "already_redeemed": "คูปองนี้ถูกใช้กับบัญชีนี้แล้ว",
                    "rate_limited": "ลองใช้คูปองบ่อยเกินไป กรุณารอ 10 นาที",
                    "account_restricted": (
                        "บัญชีนี้ยังไม่สามารถใช้งานได้ กรุณาติดต่อฝ่ายบริการ"
                    ),
                }.get(str(data.get("error")), "ใช้คูปองไม่สำเร็จ")
            )
        return CouponRedemption(
            product_code=self._required_text(data, "product_code"),
            days_added=int(data.get("days_added") or 0),
            valid_until=self._parse_datetime(data.get("valid_until")),
        )

    @staticmethod
    def _to_user(user: Any) -> AuthenticatedUser:
        user_id = str(getattr(user, "id", "") or "")
        metadata = getattr(user, "user_metadata", None) or {}
        username = str(metadata.get("username") or "").strip().lower()
        if not username:
            auth_email = str(getattr(user, "email", "") or "").strip().lower()
            username = auth_email.split("@", 1)[0]
        if not user_id or not username:
            raise LauncherServiceError("เปิดบัญชีนี้ไม่ได้ กรุณาเข้าสู่ระบบใหม่")
        return AuthenticatedUser(user_id=user_id, email=username)

    def lookup_recovery_email(self, username: str) -> str | None:
        """Return the recovery email for *username*, or ``None`` if not found."""
        username = username.strip().lower()
        try:
            response = (
                self._client.schema("launcher")
                .rpc("auth_email_for_username", {"p_username": username})
                .execute()
            )
        except Exception as exc:
            raise self._rpc_error(
                exc,
                "ตรวจสอบบัญชีไม่ได้ชั่วคราว กรุณาลองใหม่",
            ) from exc
        email = str(response.data or "").strip().lower()
        return email or None

    def _auth_email_for_username(self, username: str) -> str:
        """Internal helper that raises when no email is found (used by sign_in)."""
        email = self.lookup_recovery_email(username)
        if not email:
            raise LauncherServiceError("บัญชีนี้ยังไม่มีอีเมลสำหรับเข้าสู่ระบบ")
        return email

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise LauncherServiceError("ระบบขัดข้องชั่วคราว กรุณาลองใหม่")
        return value

    @staticmethod
    def _required_text(data: dict[str, Any], key: str) -> str:
        value = str(data.get(key) or "")
        if not value:
            raise LauncherServiceError("ระบบขัดข้องชั่วคราว กรุณาลองใหม่")
        return value

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise LauncherServiceError(
                "แสดงวันคงเหลือไม่ได้ชั่วคราว กรุณาลองใหม่"
            ) from exc

    @staticmethod
    def _contains_error(exc: Exception, code: str) -> bool:
        return code.lower() in str(exc).lower()

    @classmethod
    def _auth_error(cls, exc: Exception, fallback: str) -> LauncherServiceError:
        text = str(exc).lower()
        if "email not confirmed" in text:
            return LauncherServiceError("บัญชียังไม่พร้อมใช้งาน กรุณาลองใหม่")
        if "invalid login credentials" in text:
            return LauncherServiceError("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        if "user already registered" in text:
            return LauncherServiceError(
                "ชื่อผู้ใช้นี้มีบัญชีอยู่แล้ว กรุณาไปที่แท็บเข้าสู่ระบบ"
            )
        return LauncherServiceError(fallback)

    @classmethod
    def _rpc_error(cls, exc: Exception, fallback: str) -> LauncherServiceError:
        text = str(exc).lower()
        mapping = {
            "device_limit_reached": "บัญชีนี้ใช้งานครบจำนวนอุปกรณ์แล้ว",
            "installation_revoked": (
                "เครื่องนี้ไม่สามารถใช้งานบัญชีนี้ได้ กรุณาติดต่อฝ่ายบริการ"
            ),
            "not_authenticated": "การเข้าสู่ระบบหมดอายุ กรุณาเข้าสู่ระบบใหม่",
            "account_restricted": (
                "บัญชีนี้ยังไม่สามารถใช้งานได้ กรุณาติดต่อฝ่ายบริการ"
            ),
        }
        for code, message in mapping.items():
            if code in text:
                return LauncherServiceError(message)
        return LauncherServiceError(fallback)
