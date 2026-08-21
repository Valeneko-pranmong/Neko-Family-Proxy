from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol
from uuid import UUID, uuid4

from neko_launcher.application.authorized_core import (
    AuthorizedCoreError,
    AuthorizedCoreErrorCode,
    CoreChallenge,
    PermitDiagnosticCode,
)
from neko_launcher.infrastructure.auth.supabase_gateway import SupabaseGateway
from neko_launcher.infrastructure.core.launch_permit_gateway import IssueLaunchPermitGateway
from neko_launcher.infrastructure.process.process_detector import (
    PSO2_PROCESS_NAMES,
    is_any_process_running,
)

_LIVE_INTENT_ENV = "NEKO_LIVE_DISTINCT_AUTH_SESSION_PROOF"
_LIVE_INTENT_VALUE = "YES-I-UNDERSTAND"
_URL_ENV = "NEKO_PHASE25_SUPABASE_URL"
_PUBLISHABLE_KEY_ENV = "NEKO_PHASE25_SUPABASE_PUBLISHABLE_KEY"
_PRODUCT = "neko-family-proxy"
_PERMIT_TIMEOUT_SECONDS = 10.0


class ProofFailure(RuntimeError):
    """A fixed, non-sensitive outcome code for the hosted proof."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class InMemorySecureStore:
    """Run-local storage: Auth tokens never reach the Windows credential vault."""

    values: dict[str, str]

    def __init__(self) -> None:
        self.values = {}

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class PermitRequester(Protocol):
    def issue_launch_permit(
        self,
        authenticated_transport: object,
        correlation_id: str,
        challenge: CoreChallenge,
        timeout: float,
    ) -> object: ...


@dataclass
class _AuthContext:
    label: str
    gateway: SupabaseGateway
    installation_key_hash: str
    display_name: str
    auth_session_id: str | None = None
    user_id: str | None = None


@dataclass(frozen=True)
class _Claim:
    context: _AuthContext
    launcher_session_id: str
    installation_id: str


@dataclass(frozen=True)
class ProofResult:
    auth_session_ids_pairwise_distinct: bool
    backend_edge_session_inactive_denials: int
    final_authority: str
    remembered_installations: int
    permanent_device_revokes: int
    active_launcher_sessions_after_cleanup: int
    successful_permits: int
    permit_retries: int
    core_starts: int
    core_challenges: int

    def evidence(self) -> dict[str, object]:
        return {
            "phase": "DISTINCT_AUTH_SESSION_FUTURE_PERMIT_PROOF",
            "auth_session_ids_pairwise_distinct": self.auth_session_ids_pairwise_distinct,
            "backend_edge_session_inactive_denials": self.backend_edge_session_inactive_denials,
            "final_authority": self.final_authority,
            "remembered_installations": self.remembered_installations,
            "permanent_device_revokes": self.permanent_device_revokes,
            "active_launcher_sessions_after_cleanup": self.active_launcher_sessions_after_cleanup,
            "successful_permits": self.successful_permits,
            "permit_retries": self.permit_retries,
            "core_starts": self.core_starts,
            "core_challenges": self.core_challenges,
        }


def _session_id_from_access_token(access_token: object) -> str:
    """Read the JWT session claim in memory only; never serialize the JWT or ID."""
    if not isinstance(access_token, str):
        raise ProofFailure("AUTH_SESSION_ID_UNAVAILABLE")
    parts = access_token.split(".")
    if len(parts) != 3:
        raise ProofFailure("AUTH_SESSION_ID_UNAVAILABLE")
    try:
        payload = parts[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        value = json.loads(decoded.decode("utf-8")).get("session_id")
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise ProofFailure("AUTH_SESSION_ID_UNAVAILABLE") from None


def _current_auth_session_id(gateway: object) -> str:
    client = getattr(gateway, "_client", None)
    auth = getattr(client, "auth", None)
    getter = getattr(auth, "get_session", None)
    session = getter() if callable(getter) else None
    return _session_id_from_access_token(getattr(session, "access_token", None))


def _transport_for(gateway: object) -> object:
    transport = getattr(gateway, "_client", None)
    if transport is None:
        raise ProofFailure("AUTHENTICATED_TRANSPORT_UNAVAILABLE")
    return transport


def _random_challenge() -> str:
    value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    if len(value) != 43:
        raise ProofFailure("CHALLENGE_CONSTRUCTION_FAILED")
    return value


def _default_active_session_count(gateway: SupabaseGateway) -> int:
    response = (
        gateway._client.schema("public")  # noqa: SLF001 - live proof observation
        .table("launcher_sessions")
        .select("id")
        .is_("revoked_at", "null")
        .execute()
    )
    if not isinstance(response.data, list):
        raise ProofFailure("ACTIVE_LAUNCHER_SESSION_OBSERVATION_FAILED")
    return len(response.data)


def _default_installation_state(
    gateway: SupabaseGateway,
    installation_ids: tuple[str, ...],
) -> tuple[int, int]:
    response = (
        gateway._client.schema("public")  # noqa: SLF001 - live proof observation
        .table("installations")
        .select("id,revoked_at")
        .in_("id", list(installation_ids))
        .execute()
    )
    if not isinstance(response.data, list):
        raise ProofFailure("REMEMBERED_INSTALLATION_OBSERVATION_FAILED")
    rows = [row for row in response.data if isinstance(row, dict)]
    observed_ids = {str(row.get("id") or "") for row in rows}
    if observed_ids != set(installation_ids):
        raise ProofFailure("REMEMBERED_INSTALLATIONS_UNAVAILABLE")
    return len(rows), sum(row.get("revoked_at") is not None for row in rows)


class DistinctAuthSessionFuturePermitProofHarness:
    """Direct Edge proof that deliberately never starts Core or asks Core for a challenge."""

    def __init__(
        self,
        *,
        gateway_factory: Callable[[], SupabaseGateway],
        permit_requester: PermitRequester | None = None,
        pso2_running: Callable[[], bool | None] = lambda: is_any_process_running(
            PSO2_PROCESS_NAMES
        ),
        active_session_count: Callable[[SupabaseGateway], int] = _default_active_session_count,
        installation_state: Callable[[SupabaseGateway, tuple[str, ...]], tuple[int, int]] = (
            _default_installation_state
        ),
    ) -> None:
        self._gateway_factory = gateway_factory
        self._permit_requester = permit_requester or IssueLaunchPermitGateway()
        self._pso2_running = pso2_running
        self._active_session_count = active_session_count
        self._installation_state = installation_state
        self._permit_attempts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
        self._successful_permits = 0
        self._backend_edge_session_inactive_denials = 0

    def run(self, username: str, password: str) -> ProofResult:
        self._require_pso2_closed()
        if not username or not password:
            raise ProofFailure("CREDENTIAL_INPUT_REQUIRED")

        contexts = {
            label: _AuthContext(
                label=label,
                gateway=self._gateway_factory(),
                installation_key_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
                display_name=f"Phase 2.5 proof {label}",
            )
            for label in ("A", "B", "C")
        }
        active_claim: _Claim | None = None
        cleanup_complete = False
        try:
            self._authenticate(contexts["A"], username, password)
            claim_a = self._claim(contexts["A"])
            active_claim = claim_a
            self._require_heartbeat(claim_a, accepted=True)

            self._authenticate(contexts["B"], username, password)
            claim_b = self._claim(contexts["B"])
            active_claim = claim_b
            self._require_heartbeat(claim_a, accepted=False)
            self._require_backend_edge_session_inactive(contexts["A"])

            self._authenticate(contexts["C"], username, password)
            self._require_pairwise_distinct_auth_sessions(contexts)
            claim_c = self._claim(contexts["C"])
            active_claim = claim_c
            self._require_heartbeat(claim_b, accepted=False)
            self._require_backend_edge_session_inactive(contexts["B"])

            final_claim = self._claim(contexts["A"])
            active_claim = final_claim
            self._require_heartbeat(claim_c, accepted=False)
            self._require_backend_edge_session_inactive(contexts["C"])
            self._require_heartbeat(final_claim, accepted=True)

            installation_ids = (
                claim_a.installation_id,
                claim_b.installation_id,
                claim_c.installation_id,
            )
            if final_claim.installation_id != claim_a.installation_id:
                raise ProofFailure("RETURNING_INSTALLATION_NOT_RECLAIMED")
            remembered_count, device_revokes = self._installation_state(
                contexts["A"].gateway,
                installation_ids,
            )
            if remembered_count != 3:
                raise ProofFailure("REMEMBERED_INSTALLATIONS_UNAVAILABLE")
            if device_revokes != 0:
                raise ProofFailure("PERMANENT_DEVICE_REVOKE_DETECTED")

            self._release_active_claim(final_claim)
            active_claim = None
            cleanup_complete = True
            return ProofResult(
                auth_session_ids_pairwise_distinct=True,
                backend_edge_session_inactive_denials=self._backend_edge_session_inactive_denials,
                final_authority="A",
                remembered_installations=remembered_count,
                permanent_device_revokes=device_revokes,
                active_launcher_sessions_after_cleanup=0,
                successful_permits=self._successful_permits,
                permit_retries=sum(max(0, attempts - 1) for attempts in self._permit_attempts.values()),
                core_starts=0,
                core_challenges=0,
            )
        finally:
            cleanup_failed = False
            if not cleanup_complete and active_claim is not None:
                try:
                    self._release_active_claim(active_claim)
                except ProofFailure:
                    cleanup_failed = True
            for context in contexts.values():
                try:
                    context.gateway.clear_local_session()
                except Exception:
                    cleanup_failed = True
            if cleanup_failed:
                raise ProofFailure("CLEANUP_ACTIVE_LAUNCHER_SESSION_FAILED") from None

    def _require_pso2_closed(self) -> None:
        if self._pso2_running() is not False:
            raise ProofFailure("PSO2_CLOSED_REQUIRED")

    @staticmethod
    def _authenticate(context: _AuthContext, username: str, password: str) -> None:
        user = context.gateway.sign_in(username, password)
        context.user_id = str(getattr(user, "user_id", "") or "")
        if not context.user_id:
            raise ProofFailure("AUTH_CONTEXT_USER_UNAVAILABLE")
        context.auth_session_id = _current_auth_session_id(context.gateway)

    @staticmethod
    def _require_pairwise_distinct_auth_sessions(contexts: dict[str, _AuthContext]) -> None:
        labels = ("A", "B", "C")
        values = tuple(contexts[label].auth_session_id for label in labels)
        user_ids = tuple(contexts[label].user_id for label in labels)
        if any(value is None for value in user_ids) or len(set(user_ids)) != 1:
            raise ProofFailure("AUTH_CONTEXT_USER_MISMATCH")
        if any(value is None for value in values) or len(set(values)) != 3:
            raise ProofFailure("AUTH_SESSION_IDS_NOT_DISTINCT")

    @staticmethod
    def _claim(context: _AuthContext) -> _Claim:
        claim = context.gateway.claim_session(
            _PRODUCT,
            context.installation_key_hash,
            context.display_name,
        )
        session_id = str(getattr(claim, "session_id", "") or "")
        installation_id = str(getattr(claim, "installation_id", "") or "")
        if not session_id or not installation_id:
            raise ProofFailure("SESSION_CLAIM_FAILED")
        return _Claim(context, session_id, installation_id)

    @staticmethod
    def _require_heartbeat(claim: _Claim, *, accepted: bool) -> None:
        try:
            observed = claim.context.gateway.heartbeat_session(claim.launcher_session_id)
        except Exception:
            raise ProofFailure("HEARTBEAT_OBSERVATION_FAILED") from None
        if observed is not accepted:
            raise ProofFailure(
                "NEW_AUTH_HEARTBEAT_REJECTED" if accepted else "OLD_AUTH_HEARTBEAT_ACCEPTED"
            )

    def _require_backend_edge_session_inactive(self, context: _AuthContext) -> None:
        self._permit_attempts[context.label] += 1
        if self._permit_attempts[context.label] != 1:
            raise ProofFailure("PERMIT_RETRY_FORBIDDEN")
        try:
            permit = self._permit_requester.issue_launch_permit(
                _transport_for(context.gateway),
                uuid4().hex,
                CoreChallenge(_random_challenge()),
                _PERMIT_TIMEOUT_SECONDS,
            )
        except AuthorizedCoreError as exc:
            if (
                exc.code is AuthorizedCoreErrorCode.PERMIT_UNAVAILABLE
                and exc.diagnostic_code
                is PermitDiagnosticCode.BACKEND_EDGE_SESSION_INACTIVE
                and exc.diagnostic_context.get("http_status") == 403
                and exc.diagnostic_context.get("function") == "issue_launch_permit"
                and exc.diagnostic_context.get("stage") == "PERMIT_REQUEST"
            ):
                self._backend_edge_session_inactive_denials += 1
                return
            raise ProofFailure("BACKEND_EDGE_SESSION_INACTIVE_REQUIRED") from None
        self._successful_permits += 1
        del permit
        raise ProofFailure("UNEXPECTED_SUCCESSFUL_PERMIT")

    def _release_active_claim(self, claim: _Claim) -> None:
        try:
            released = claim.context.gateway.release_session(claim.launcher_session_id)
        except Exception:
            released = False
        if released is not True:
            raise ProofFailure("ACTIVE_LAUNCHER_SESSION_RELEASE_FAILED")
        if self._active_session_count(claim.context.gateway) != 0:
            raise ProofFailure("ACTIVE_LAUNCHER_SESSIONS_REMAIN")


def default_preparation_manifest() -> dict[str, object]:
    return {
        "phase": "DISTINCT_AUTH_SESSION_FUTURE_PERMIT_PROOF_PREPARATION",
        "hosted_execution_performed": False,
        "same_user_account": True,
        "auth_contexts": ["A", "B", "C"],
        "auth_session_ids_must_be_pairwise_distinct": True,
        "forbidden_auth_practices": [
            "token_cloning",
            "service_role_or_admin_jwt",
            "manual_session_id_manipulation",
        ],
        "required_sequence": [
            "A_CLAIM",
            "B_CLAIM",
            "OLD_A_HEARTBEAT_DENIED",
            "OLD_A_EDGE_403_SESSION_INACTIVE",
            "C_CLAIM",
            "OLD_B_HEARTBEAT_DENIED",
            "OLD_B_EDGE_403_SESSION_INACTIVE",
            "A_RECLAIM",
            "OLD_C_HEARTBEAT_DENIED",
            "OLD_C_EDGE_403_SESSION_INACTIVE",
        ],
        "proof_requirements": {
            "pso2_must_be_closed_before_manual_auth": True,
            "edge_invocations_required": 3,
            "expected_edge_status": 403,
            "expected_edge_code": "SessionInactive",
            "required_classification": "BACKEND_EDGE_SESSION_INACTIVE",
            "successful_permits": 0,
            "permit_retries": 0,
            "core_starts": 0,
            "core_challenges": 0,
        },
    }


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _gateway_factory_from_environment() -> Callable[[], SupabaseGateway]:
    url = os.getenv(_URL_ENV, "").strip()
    publishable_key = os.getenv(_PUBLISHABLE_KEY_ENV, "").strip()
    if not url or not publishable_key:
        raise ProofFailure("PUBLIC_SUPABASE_CONFIGURATION_REQUIRED")

    def create() -> SupabaseGateway:
        return SupabaseGateway(url, publishable_key, InMemorySecureStore())

    return create


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 2.5 distinct Auth-session future-permit proof"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="write an offline readiness manifest")
    prepare.add_argument("--output", required=True, type=Path)
    execute = commands.add_parser("execute", help="run the explicitly authorized hosted proof")
    execute.add_argument("--live", action="store_true", required=True)
    execute.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "prepare":
        _write_evidence(args.output, default_preparation_manifest())
        print("DISTINCT_AUTH_SESSION_FUTURE_PERMIT_PROOF_PREPARED")
        return 0

    if not args.live or os.getenv(_LIVE_INTENT_ENV) != _LIVE_INTENT_VALUE:
        print("LIVE_INTENT_REQUIRED")
        return 2
    try:
        harness = DistinctAuthSessionFuturePermitProofHarness(
            gateway_factory=_gateway_factory_from_environment()
        )
        harness._require_pso2_closed()
        username = getpass.getpass("Phase 2.5 username: ").strip()
        password = getpass.getpass("Phase 2.5 password: ")
        result = harness.run(username, password)
        _write_evidence(args.output, result.evidence())
    except ProofFailure as exc:
        print(exc.code)
        return 1
    except Exception:
        print("UNEXPECTED_PROOF_FAILURE")
        return 1
    print("DISTINCT_AUTH_SESSION_FUTURE_PERMIT_PROOF_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
