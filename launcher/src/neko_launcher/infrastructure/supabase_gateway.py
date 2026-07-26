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

    def sign_up(self, email: str, password: str) -> RegistrationResult:
        try:
            response = self._client.auth.sign_up(
                {"email": email, "password": password}
            )
        except Exception as exc:
            raise self._auth_error(exc, "สมัครสมาชิกไม่สำเร็จ")

        user = self._to_user(response.user) if response.user else None
        return RegistrationResult(
            email=email,
            requires_email_confirmation=response.session is None,
            user=user if response.session is not None else None,
        )

    def sign_in(self, email: str, password: str) -> AuthenticatedUser:
        try:
            response = self._client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:
            raise self._auth_error(exc, "อีเมลหรือรหัสผ่านไม่ถูกต้อง")
        if response.user is None or response.session is None:
            raise LauncherServiceError("ไม่พบเซสชันหลังเข้าสู่ระบบ")
        return self._to_user(response.user)

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
                    "บัญชียังไม่มีสิทธิ์ใช้งาน กรุณาเติมคูปอง"
                ) from exc
            raise self._rpc_error(exc, "ตรวจสอบสิทธิ์ใช้งานไม่สำเร็จ")

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
            raise self._rpc_error(exc, "ตรวจสอบสถานะเซสชันไม่สำเร็จ")
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
                    "account_restricted": "บัญชีนี้ถูกจำกัดการใช้งาน",
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
        email = str(getattr(user, "email", "") or "").strip().lower()
        if not user_id or not email:
            raise LauncherServiceError("ข้อมูลบัญชีที่ได้รับไม่สมบูรณ์")
        return AuthenticatedUser(user_id=user_id, email=email)

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise LauncherServiceError("ข้อมูลตอบกลับจากเซิร์ฟเวอร์ไม่ถูกต้อง")
        return value

    @staticmethod
    def _required_text(data: dict[str, Any], key: str) -> str:
        value = str(data.get(key) or "")
        if not value:
            raise LauncherServiceError("ข้อมูลตอบกลับจากเซิร์ฟเวอร์ไม่สมบูรณ์")
        return value

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise LauncherServiceError(
                "ข้อมูลวันหมดอายุจากเซิร์ฟเวอร์ไม่ถูกต้อง"
            ) from exc

    @staticmethod
    def _contains_error(exc: Exception, code: str) -> bool:
        return code.lower() in str(exc).lower()

    @classmethod
    def _auth_error(cls, exc: Exception, fallback: str) -> LauncherServiceError:
        text = str(exc).lower()
        if "email not confirmed" in text:
            return LauncherServiceError("กรุณายืนยันอีเมลก่อนเข้าสู่ระบบ")
        if "invalid login credentials" in text:
            return LauncherServiceError("อีเมลหรือรหัสผ่านไม่ถูกต้อง")
        if "user already registered" in text:
            return LauncherServiceError("อีเมลนี้ถูกสมัครสมาชิกแล้ว")
        return LauncherServiceError(fallback)

    @classmethod
    def _rpc_error(cls, exc: Exception, fallback: str) -> LauncherServiceError:
        text = str(exc).lower()
        mapping = {
            "device_limit_reached": "บัญชีนี้ใช้งานครบจำนวนอุปกรณ์แล้ว",
            "installation_revoked": "อุปกรณ์นี้ถูกระงับการใช้งาน",
            "not_authenticated": "เซสชันเข้าสู่ระบบหมดอายุ กรุณาเข้าสู่ระบบใหม่",
            "account_restricted": "บัญชีนี้ถูกจำกัดการใช้งาน",
        }
        for code, message in mapping.items():
            if code in text:
                return LauncherServiceError(message)
        return LauncherServiceError(fallback)
