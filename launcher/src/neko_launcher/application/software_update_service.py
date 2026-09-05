from __future__ import annotations

from collections.abc import Callable
from threading import Condition
from typing import Protocol

from neko_launcher.application.ports import UpdateManifestGateway
from neko_launcher.application.software_update_models import (
    LocalReleaseIdentity,
    ReleaseSet,
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.application.software_update_policy import evaluate_release


class ReleaseManifestVerifier(Protocol):
    def verify(self, document: object) -> ReleaseSet:
        ...


_VERIFIER_REJECTED_CODES = frozenset(
    {
        "INVALID_ENVELOPE_TYPE",
        "INVALID_ENVELOPE_SCHEMA",
        "UNSUPPORTED_ENVELOPE_VERSION",
        "INVALID_KEY_ID",
        "INVALID_BASE64",
        "PAYLOAD_TOO_LARGE",
        "INVALID_SIGNATURE_LENGTH",
        "UNKNOWN_KEY_ID",
        "INVALID_PUBLIC_KEY",
        "SIGNATURE_INVALID",
        "INVALID_UTF8",
        "INVALID_JSON",
        "INVALID_PAYLOAD_SCHEMA",
    }
)


class UpdateCheckService:
    def __init__(
        self,
        manifest_gateway: UpdateManifestGateway,
        verifier: ReleaseManifestVerifier,
        local_identity_provider: Callable[[], LocalReleaseIdentity],
    ) -> None:
        self._manifest_gateway = manifest_gateway
        self._verifier = verifier
        self._local_identity_provider = local_identity_provider
        self._startup_condition = Condition()
        self._startup_checking = False
        self._startup_result: UpdateCheckResult | None = None

    def check_startup(self) -> UpdateCheckResult:
        with self._startup_condition:
            while self._startup_checking:
                self._startup_condition.wait()
            if self._startup_result is not None:
                return self._startup_result
            self._startup_checking = True

        result = self._internal_failure_result(
            UpdateInvocationReason.STARTUP,
        )
        try:
            result = self._check(UpdateInvocationReason.STARTUP)
        finally:
            with self._startup_condition:
                self._startup_result = result
                self._startup_checking = False
                self._startup_condition.notify_all()

        return result

    def check_manual(self) -> UpdateCheckResult:
        return self._check(UpdateInvocationReason.MANUAL)

    def _check(
        self,
        reason: UpdateInvocationReason,
    ) -> UpdateCheckResult:
        try:
            document = self._manifest_gateway.fetch()
        except Exception as error:
            return self._gateway_exception_result(reason, error)

        if document is None:
            return self._empty_result(
                reason,
                UpdateState.UNAVAILABLE,
                None,
            )

        try:
            remote = self._verifier.verify(document)
        except Exception as error:
            return self._verifier_exception_result(reason, error)

        try:
            local = self._local_identity_provider()
            return evaluate_release(local, remote, reason)
        except Exception:
            return self._internal_failure_result(reason)

    @classmethod
    def _gateway_exception_result(
        cls,
        reason: UpdateInvocationReason,
        error: Exception,
    ) -> UpdateCheckResult:
        code = cls._safe_exception_code(error)
        if code == "MANIFEST_UNAVAILABLE":
            return cls._empty_result(
                reason,
                UpdateState.UNAVAILABLE,
                UpdateDiagnosticCode.MANIFEST_UNAVAILABLE,
            )
        if code == "MANIFEST_RESPONSE_INVALID":
            return cls._manifest_rejected_result(reason)
        return cls._internal_failure_result(reason)

    @classmethod
    def _verifier_exception_result(
        cls,
        reason: UpdateInvocationReason,
        error: Exception,
    ) -> UpdateCheckResult:
        code = cls._safe_exception_code(error)
        if code in _VERIFIER_REJECTED_CODES:
            return cls._manifest_rejected_result(reason)
        return cls._internal_failure_result(reason)

    @staticmethod
    def _safe_exception_code(error: Exception) -> str | None:
        try:
            code = getattr(error, "code", None)
        except Exception:
            return None
        if type(code) is not str:
            return None
        return code

    @classmethod
    def _manifest_rejected_result(
        cls,
        reason: UpdateInvocationReason,
    ) -> UpdateCheckResult:
        return cls._empty_result(
            reason,
            UpdateState.VERIFY_FAILED,
            UpdateDiagnosticCode.MANIFEST_REJECTED,
        )

    @classmethod
    def _internal_failure_result(
        cls,
        reason: UpdateInvocationReason,
    ) -> UpdateCheckResult:
        return cls._empty_result(
            reason,
            UpdateState.VERIFY_FAILED,
            UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE,
        )

    @staticmethod
    def _empty_result(
        reason: UpdateInvocationReason,
        state: UpdateState,
        diagnostic_code: UpdateDiagnosticCode | None,
    ) -> UpdateCheckResult:
        return UpdateCheckResult(
            state=state,
            invocation_reason=reason,
            release_id=None,
            release_sequence=None,
            changed_components=(),
            launcher_version=None,
            core_version=None,
            mandatory=False,
            diagnostic_code=diagnostic_code,
        )
