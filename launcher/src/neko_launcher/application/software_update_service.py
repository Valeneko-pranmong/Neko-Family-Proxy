from __future__ import annotations

from collections.abc import Callable
from threading import Condition
from typing import TYPE_CHECKING, Protocol

from neko_launcher.application.software_update_models import (
    LocalReleaseIdentity,
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.application.software_update_policy import evaluate_release

if TYPE_CHECKING:
    from neko_launcher.infrastructure.github_release_binding import (
        ResolvedGitHubRelease,
    )


class AuthenticatedReleaseGateway(Protocol):
    def resolve(self) -> ResolvedGitHubRelease | None:
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
        "RELEASE_MANIFEST_REJECTED",
        "MANIFEST_RESPONSE_INVALID",
    }
)


class UpdateCheckService:
    def __init__(
        self,
        release_gateway: AuthenticatedReleaseGateway,
        local_identity_provider: Callable[[], LocalReleaseIdentity],
    ) -> None:
        self._release_gateway = release_gateway
        self._local_identity_provider = local_identity_provider
        self._startup_condition = Condition()
        self._startup_checking = False
        self._startup_result: UpdateCheckResult | None = None
        self._startup_resolved: ResolvedGitHubRelease | None = None

    def check_startup(self) -> UpdateCheckResult:
        return self.check_startup_with_resolved()[0]

    def check_manual(self) -> UpdateCheckResult:
        return self.check_manual_with_resolved()[0]

    def check_startup_with_resolved(
        self,
    ) -> tuple[UpdateCheckResult, ResolvedGitHubRelease | None]:
        with self._startup_condition:
            while self._startup_checking:
                self._startup_condition.wait()
            if self._startup_result is not None:
                return self._startup_result, self._startup_resolved
            self._startup_checking = True

        result = self._internal_failure_result(
            UpdateInvocationReason.STARTUP,
        )
        resolved: ResolvedGitHubRelease | None = None
        try:
            result, resolved = self._check_with_resolved(UpdateInvocationReason.STARTUP)
        finally:
            with self._startup_condition:
                self._startup_result = result
                self._startup_resolved = resolved
                self._startup_checking = False
                self._startup_condition.notify_all()

        return result, resolved

    def check_manual_with_resolved(
        self,
    ) -> tuple[UpdateCheckResult, ResolvedGitHubRelease | None]:
        return self._check_with_resolved(UpdateInvocationReason.MANUAL)

    def _check(
        self,
        reason: UpdateInvocationReason,
    ) -> UpdateCheckResult:
        return self._check_with_resolved(reason)[0]

    def _check_with_resolved(
        self,
        reason: UpdateInvocationReason,
    ) -> tuple[UpdateCheckResult, ResolvedGitHubRelease | None]:
        try:
            resolved = self._release_gateway.resolve()
        except Exception as error:
            return self._gateway_exception_result(reason, error), None

        if resolved is None:
            return (
                self._empty_result(
                    reason,
                    UpdateState.UNAVAILABLE,
                    None,
                ),
                None,
            )

        try:
            remote = resolved.authenticated_release
            local = self._local_identity_provider()
            return evaluate_release(local, remote, reason), resolved
        except Exception:
            return self._internal_failure_result(reason), None

    @classmethod
    def _gateway_exception_result(
        cls,
        reason: UpdateInvocationReason,
        error: Exception,
    ) -> UpdateCheckResult:
        code = cls._safe_exception_code(error)
        if code in ("MANIFEST_UNAVAILABLE", "GITHUB_RELEASE_UNAVAILABLE"):
            diag = getattr(
                UpdateDiagnosticCode,
                code,
                UpdateDiagnosticCode.MANIFEST_UNAVAILABLE,
            )
            return cls._empty_result(
                reason,
                UpdateState.UNAVAILABLE,
                diag,
            )
        if code in _VERIFIER_REJECTED_CODES:
            return cls._manifest_rejected_result(reason)
        if code == "UPDATER_INCOMPATIBLE":
            return cls._empty_result(
                reason,
                UpdateState.VERIFY_FAILED,
                UpdateDiagnosticCode.UPDATER_INCOMPATIBLE,
            )
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
