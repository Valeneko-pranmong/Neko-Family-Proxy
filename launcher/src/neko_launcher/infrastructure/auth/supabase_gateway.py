from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

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
    SessionTerminationReason,
)

from neko_launcher.infrastructure.storage.secure_store import SupabaseAuthStorage

if TYPE_CHECKING:
    from neko_launcher.application.authorized_core import CoreChallenge, OpaquePermit


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
        hostname = urlparse(url).hostname
        if not hostname:
            raise ValueError("Supabase URL must include a hostname")
        self._auth_identifier_domain = hostname.lower()
        self._auth_storage = SupabaseAuthStorage(secure_store)
        self._client = client or create_client(
            url,
            publishable_key,
            options=ClientOptions(
                schema="launcher",
                storage=self._auth_storage,
                auto_refresh_token=True,
                persist_session=True,
            ),
        )

    def sign_up(
        self,
        username: str,
        password: str,
    ) -> RegistrationResult:
        username = username.strip().lower()
        auth_identifier = self.auth_identifier_for_username(username)
        try:
            response = self._client.auth.sign_up(
                {
                    "email": auth_identifier,
                    "password": password,
                    "options": {
                        "data": {
                            "username": username,
                            "display_name": username,
                        }
                    },
                }
            )
        except Exception as exc:
            raise self._auth_error(exc, "สมัครสมาชิกไม่สำเร็จ")

        user = self._to_user(response.user) if response.user else None
        return RegistrationResult(
            email=username,
            requires_email_confirmation=(
                response.user is not None and response.session is None
            ),
            user=user if response.session is not None else None,
        )

    def sign_in(self, username: str, password: str) -> AuthenticatedUser:
        username = username.strip().lower()
        auth_identifier = self.auth_identifier_for_username(username)
        try:
            response = self._client.auth.sign_in_with_password(
                {"email": auth_identifier, "password": password}
            )
        except Exception as exc:
            raise self._auth_error(exc, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        if response.user is None or response.session is None:
            raise LauncherServiceError("เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่")
        return self._to_user(response.user)

    def auth_identifier_for_username(self, username: str) -> str:
        """Derive the non-PII Auth identifier without a database lookup."""
        normalized = username.strip().lower()
        return f"{normalized}@{self._auth_identifier_domain}"

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
            # Launcher sign-out is local to this installation. Global scope would
            # revoke refresh tokens on the newest logged-in machine as well.
            self._client.auth.sign_out({"scope": "local"})
        except Exception as exc:
            raise self._auth_error(exc, "ออกจากระบบไม่สำเร็จ")

    def clear_local_session(self) -> None:
        """Remove persisted auth even when the remote sign-out request fails."""
        remover = getattr(self._client.auth, "_remove_session", None)
        if callable(remover):
            remover()
            return
        storage_key = str(
            getattr(self._client.auth, "_storage_key", "supabase.auth.token")
        )
        self._auth_storage.remove_item(storage_key)

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
                    "สิทธิ์ใช้งานไม่พร้อม ถูกยกเลิก หรือหมดอายุ "
                    "กรุณาติดต่อฝ่ายบริการ"
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
            installation_id=self._required_text(data, "installation_id"),
            license_id=self._required_text(data, "license_id"),
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

    def session_termination_reason(
        self, session_id: str
    ) -> SessionTerminationReason:
        """Resolve a customer-safe reason from rows visible through RLS."""
        session = self._first_public_row(
            "launcher_sessions",
            "id,user_id,installation_id,license_id,revoked_at",
            id=session_id,
        )
        if session is None:
            return SessionTerminationReason.REVOKED

        profile = self._first_public_row(
            "profiles", "status", id=str(session["user_id"])
        )
        if profile is not None and profile.get("status") != "active":
            return SessionTerminationReason.ACCOUNT_RESTRICTED

        license_row = self._first_public_row(
            "licenses", "status,valid_from,valid_until", id=str(session["license_id"])
        )
        if license_row is not None:
            valid_from = self._parse_datetime(license_row.get("valid_from"))
            valid_until = self._parse_datetime(license_row.get("valid_until"))
            now = datetime.now(valid_until.tzinfo)
            if (
                license_row.get("status") != "active"
                or valid_from > now
                or valid_until <= now
            ):
                return SessionTerminationReason.LICENSE_UNAVAILABLE

        active = (
            self._client.schema("public")
            .table("launcher_sessions")
            .select("id")
            .eq("user_id", str(session["user_id"]))
            .neq("id", session_id)
            .is_("revoked_at", "null")
            .limit(1)
            .execute()
        )
        if isinstance(active.data, list) and active.data:
            return SessionTerminationReason.REPLACED

        # Compatibility-only diagnosis for a backend that has not yet removed
        # legacy installation revocation. It is not consulted before a newer
        # active session and does not participate in session claims.
        installation = self._first_public_row(
            "installations", "revoked_at", id=str(session["installation_id"])
        )
        if installation is not None and installation.get("revoked_at") is not None:
            return SessionTerminationReason.INSTALLATION_REVOKED
        return SessionTerminationReason.REVOKED

    def _first_public_row(
        self, table: str, columns: str, **filters: str
    ) -> dict[str, Any] | None:
        query = self._client.schema("public").table(table).select(columns)
        for key, value in filters.items():
            query = query.eq(key, value)
        response = query.limit(1).execute()
        if not isinstance(response.data, list) or not response.data:
            return None
        row = response.data[0]
        return row if isinstance(row, dict) else None

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

    def issue_launch_permit(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: "CoreChallenge",
        configuration_digest: str,
        process_name: str,
        target_pid: int,
        mode: str,
        product: str,
        scope: str,
        timeout: float,
    ) -> "OpaquePermit":
        """Call Backend Edge Function to obtain an opaque RS256-signed permit.

        The Launcher never decodes or verifies the permit; Core is the sole
        verifier.  The authenticated Supabase session provides the Bearer
        token automatically.
        """
        from neko_launcher.application.authorized_core import (
            AuthorizedCoreError,
            AuthorizedCoreErrorCode,
            OpaquePermit,
        )

        try:
            response = self._client.functions.invoke(
                "issue_launch_permit",
                invoke_options={
                    "body": {
                        "challenge": challenge.value,
                        "configuration_digest": configuration_digest,
                        "process_name": process_name,
                        "target_pid": target_pid,
                        "mode": mode,
                        "product": product,
                        "scope": scope,
                    },
                },
            )
        except Exception:
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE)
        try:
            import json

            data = json.loads(response) if isinstance(response, (str, bytes)) else response
            permit_value = data.get("permit") if isinstance(data, dict) else None
        except Exception:
            permit_value = None
        if not permit_value or not isinstance(permit_value, str):
            raise AuthorizedCoreError(AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE)
        return OpaquePermit(permit_value)

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
            "not_authenticated": "การเข้าสู่ระบบหมดอายุ กรุณาเข้าสู่ระบบใหม่",
            "account_restricted": (
                "บัญชีนี้ถูกระงับการใช้งาน กรุณาติดต่อฝ่ายบริการ"
            ),
        }
        for code, message in mapping.items():
            if code in text:
                return LauncherServiceError(message)
        return LauncherServiceError(fallback)
