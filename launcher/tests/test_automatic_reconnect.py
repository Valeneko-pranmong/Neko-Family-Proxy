from datetime import UTC, datetime, timedelta

import pytest

from neko_launcher.application.reconnect import (
    AutomaticProxyReconnectController,
    ReconnectCompletion,
)
from neko_launcher.domain.models import (
    AppState,
    AuthStatus,
    Entitlement,
    EntitlementStatus,
)


def eligible_state(**changes: object) -> AppState:
    values: dict[str, object] = {
        "auth_status": AuthStatus.AUTHENTICATED,
        "entitlement": Entitlement(
            "product",
            EntitlementStatus.ACTIVE,
            datetime.now(UTC) + timedelta(days=1),
        ),
        "session_id": "session-id",
        "game_process_running": True,
    }
    values.update(changes)
    return AppState(**values)  # type: ignore[arg-type]


def test_reconnect_request_is_single_flight_and_uses_bounded_backoff() -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0, 2.0, 4.0))
    controller.observe_running()

    first = controller.request(eligible_state(), shutting_down=False)

    assert first is not None
    assert (first.attempt, first.delay_seconds) == (1, 1.0)
    assert controller.request(eligible_state(), shutting_down=False) is None
    cancellation = controller.begin(first, eligible_state(), shutting_down=False)
    assert cancellation is not None
    assert controller.request(eligible_state(), shutting_down=False) is None
    assert (
        controller.complete(first, succeeded=False, retry_safe=True)
        is ReconnectCompletion.RETRY
    )

    second = controller.request(eligible_state(), shutting_down=False)
    assert second is not None
    assert (second.attempt, second.delay_seconds) == (2, 2.0)


def test_reconnect_success_resets_retry_counter() -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0, 2.0))
    controller.observe_running()
    first = controller.request(eligible_state(), shutting_down=False)
    assert first is not None
    assert controller.begin(first, eligible_state(), shutting_down=False) is not None

    assert (
        controller.complete(first, succeeded=True, retry_safe=False)
        is ReconnectCompletion.SUCCEEDED
    )
    assert controller.attempts == 0

    controller.observe_running()
    next_lifecycle = controller.request(eligible_state(), shutting_down=False)
    assert next_lifecycle is not None
    assert next_lifecycle.attempt == 1


@pytest.mark.parametrize(
    "state",
    [
        eligible_state(auth_status=AuthStatus.SIGNED_OUT),
        eligible_state(session_id=None),
        eligible_state(entitlement=None),
        eligible_state(game_process_running=False),
        eligible_state(proxy_reconnect_suppressed=True),
        eligible_state(shutting_down=True),
    ],
)
def test_reconnect_is_suppressed_when_any_authority_or_intent_guard_fails(
    state: AppState,
) -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0, 2.0))
    controller.observe_running()

    assert controller.request(state, shutting_down=False) is None


def test_launcher_shutdown_argument_suppresses_reconnect() -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0,))
    controller.observe_running()

    assert controller.request(eligible_state(), shutting_down=True) is None


@pytest.mark.parametrize(
    "failure_code",
    [
        "AuthorizationInvalid",
        "SessionInactive",
        "EntitlementInactive",
    ],
)
def test_security_denial_blocks_future_reconnect_attempts(failure_code: str) -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0, 2.0))
    controller.observe_running()
    attempt = controller.request(eligible_state(), shutting_down=False)
    assert attempt is not None
    assert controller.begin(attempt, eligible_state(), shutting_down=False) is not None

    assert (
        controller.complete(
            attempt,
            succeeded=False,
            retry_safe=True,
            failure_code=failure_code,
        )
        is ReconnectCompletion.BLOCKED
    )
    assert controller.request(eligible_state(), shutting_down=False) is None


def test_retry_budget_exhaustion_stops_without_an_infinite_loop() -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0, 2.0))
    controller.observe_running()

    first = controller.request(eligible_state(), shutting_down=False)
    assert first is not None
    assert controller.begin(first, eligible_state(), shutting_down=False) is not None
    assert (
        controller.complete(first, succeeded=False, retry_safe=True)
        is ReconnectCompletion.RETRY
    )

    second = controller.request(eligible_state(), shutting_down=False)
    assert second is not None
    assert controller.begin(second, eligible_state(), shutting_down=False) is not None
    assert (
        controller.complete(second, succeeded=False, retry_safe=True)
        is ReconnectCompletion.EXHAUSTED
    )
    assert controller.request(eligible_state(), shutting_down=False) is None


def test_cancel_invalidates_scheduled_attempt() -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0,))
    controller.observe_running()
    attempt = controller.request(eligible_state(), shutting_down=False)
    assert attempt is not None

    controller.cancel(reset_attempts=True)

    assert controller.begin(attempt, eligible_state(), shutting_down=False) is None
    assert controller.attempts == 0


def test_stale_healthy_observation_does_not_clear_scheduled_or_inflight_attempt() -> None:
    controller = AutomaticProxyReconnectController(backoff_seconds=(1.0,))
    controller.observe_running()
    attempt = controller.request(eligible_state(), shutting_down=False)
    assert attempt is not None

    controller.observe_running()
    cancellation = controller.begin(attempt, eligible_state(), shutting_down=False)
    assert cancellation is not None
    controller.observe_running()

    assert controller.in_flight is True
    assert (
        controller.complete(attempt, succeeded=True, retry_safe=False)
        is ReconnectCompletion.SUCCEEDED
    )
