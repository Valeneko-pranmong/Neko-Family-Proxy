from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any
from uuid import UUID

from neko_launcher.application.errors import (
    LauncherServiceError,
    RecoveryRetryRequired,
    RecoverySessionInvalid,
)
from neko_launcher.domain.models import RecoverySession

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,200}$")
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_MAX_RESPONSE_BYTES = 16_384


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_open_no_redirect = urllib.request.build_opener(_NoRedirectHandler()).open


class HttpAccountRecoveryGateway:
    """Strict public Web API client that never touches normal Supabase Auth state."""

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("Account Recovery API must use HTTPS")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def verify_recovery_code(
        self, username: str, recovery_code: str
    ) -> RecoverySession:
        data = self._post_json(
            "/api/account/recovery/verify",
            {"username": username, "recovery_code": recovery_code},
            operation="verify",
        )
        try:
            if set(data) != {
                "ok",
                "recovery_session_id",
                "recovery_session",
                "scope",
                "expires_at",
            }:
                raise ValueError("unexpected recovery response fields")
            session_id = str(UUID(self._required_text(data, "recovery_session_id")))
            token = self._required_text(data, "recovery_session")
            scope = self._required_text(data, "scope")
            expires_at_raw = self._required_text(data, "expires_at")
            if (
                data.get("ok") is not True
                or scope != "change_password"
                or not _TOKEN_PATTERN.fullmatch(token)
                or not _RFC3339_PATTERN.fullmatch(expires_at_raw)
            ):
                raise ValueError("invalid recovery response")
            expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                raise ValueError("timezone required")
        except (KeyError, TypeError, ValueError) as exc:
            raise LauncherServiceError(
                "ระบบกู้บัญชีตอบกลับไม่ถูกต้อง กรุณาลองใหม่ภายหลัง"
            ) from exc
        return RecoverySession(session_id, token, expires_at)

    def change_password(self, recovery_session: str, new_password: str) -> None:
        data = self._post_json(
            "/api/account/recovery/change-password",
            {"new_password": new_password},
            operation="change",
            recovery_session=recovery_session,
        )
        if data != {"ok": True, "completed": True, "state": "completed"}:
            raise RecoveryRetryRequired(
                "ไม่สามารถยืนยันผลการเปลี่ยนรหัสผ่านได้ "
                "กรุณาลองส่งรหัสผ่านเดิมอีกครั้ง"
            )

    def _post_json(
        self,
        path: str,
        payload: dict[str, str],
        *,
        operation: str,
        recovery_session: str | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > 4096:
            raise LauncherServiceError("ข้อมูลยาวเกินกำหนด กรุณาตรวจสอบแล้วลองใหม่")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if recovery_session is not None:
            if not _TOKEN_PATTERN.fullmatch(recovery_session):
                raise RecoverySessionInvalid(
                    "เซสชันกู้บัญชีไม่ถูกต้องหรือหมดอายุแล้ว กรุณาเริ่มใหม่"
                )
            headers["Authorization"] = f"Bearer {recovery_session}"
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with _open_no_redirect(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise LauncherServiceError("ระบบกู้บัญชีขัดข้อง กรุณาลองใหม่ภายหลัง")
                return self._decode_response(response.read(_MAX_RESPONSE_BYTES + 1))
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc, operation)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if operation == "change":
                raise RecoveryRetryRequired(
                    "ไม่สามารถยืนยันผลการเปลี่ยนรหัสผ่านได้ "
                    "กรุณาลองส่งรหัสผ่านเดิมอีกครั้ง"
                ) from exc
            raise LauncherServiceError(
                "ไม่สามารถเชื่อมต่อระบบได้ กรุณาลองอีกครั้ง"
            ) from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _decode_response(raw: bytes) -> dict[str, Any]:
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise LauncherServiceError("ระบบกู้บัญชีตอบกลับไม่ถูกต้อง กรุณาลองใหม่ภายหลัง")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LauncherServiceError(
                "ระบบกู้บัญชีตอบกลับไม่ถูกต้อง กรุณาลองใหม่ภายหลัง"
            ) from exc
        if not isinstance(data, dict):
            raise LauncherServiceError("ระบบกู้บัญชีตอบกลับไม่ถูกต้อง กรุณาลองใหม่ภายหลัง")
        return data

    def _raise_http_error(self, exc: urllib.error.HTTPError, operation: str) -> None:
        try:
            data = self._decode_response(exc.read(_MAX_RESPONSE_BYTES + 1))
            error = data.get("error") if isinstance(data.get("error"), str) else ""
        except LauncherServiceError:
            error = ""
        if operation == "verify":
            if exc.code == 400 and error == "Recovery code is invalid or expired":
                raise LauncherServiceError(
                    "รหัสกู้บัญชีไม่ถูกต้องหรือหมดอายุแล้ว "
                    "กรุณาติดต่อผู้ดูแลเพื่อขอรหัสใหม่"
                ) from exc
            if exc.code == 413:
                raise LauncherServiceError("ข้อมูลยาวเกินกำหนด กรุณาตรวจสอบแล้วลองใหม่") from exc
            raise LauncherServiceError("ระบบขัดข้อง กรุณาลองใหม่ภายหลัง") from exc

        policy_error = (
            "Password must be 12-128 characters and include upper, lower, number, and symbol"
        )
        if exc.code == 400 and error == policy_error:
            raise LauncherServiceError(
                "รหัสผ่านต้องมี 12-128 ตัวอักษร และมีตัวพิมพ์ใหญ่ "
                "ตัวพิมพ์เล็ก ตัวเลข และสัญลักษณ์"
            ) from exc
        if exc.code == 401:
            raise RecoverySessionInvalid(
                "เซสชันกู้บัญชีไม่ถูกต้องหรือหมดอายุแล้ว กรุณาเริ่มใหม่"
            ) from exc
        retry_errors = {
            "Retry the same recovery session and password",
            "Recovery backend is temporarily unavailable",
            "Password recovery is temporarily unavailable; retry the same request",
            "Password was updated but recovery finalization is pending; retry the same request",
            "Recovery backend returned an invalid response",
        }
        if exc.code in {409, 502, 503} and error in retry_errors:
            raise RecoveryRetryRequired(
                "ระบบกู้บัญชียังดำเนินการไม่เสร็จ "
                "กรุณาลองส่งรหัสผ่านเดิมอีกครั้ง"
            ) from exc
        if exc.code == 413:
            raise LauncherServiceError("ข้อมูลยาวเกินกำหนด กรุณาตรวจสอบแล้วลองใหม่") from exc
        raise LauncherServiceError("ระบบขัดข้อง กรุณาลองใหม่ภายหลัง") from exc

    @staticmethod
    def _required_text(data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"missing {key}")
        return value
