from __future__ import annotations

import inspect
from collections.abc import Callable
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

import pytest

from neko_launcher.application.software_update_models import (
    UpdateCheckResult,
    UpdateDiagnosticCode,
    UpdateInvocationReason,
    UpdateState,
)
from neko_launcher.ui.app_window import AppWindow


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, Callable[[], None]]] = []

    def after(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self.after_calls.append((delay_ms, callback))

    def winfo_exists(self) -> bool:
        return True

    def run_callbacks(self) -> None:
        while self.after_calls:
            callbacks = self.after_calls
            self.after_calls = []
            for _delay_ms, callback in callbacks:
                callback()

    def run_callback_generation(self) -> None:
        callbacks = self.after_calls
        self.after_calls = []
        for _delay_ms, callback in callbacks:
            callback()


class ImmediateExecutor:
    def __init__(self) -> None:
        self.submitted: list[Callable[[], Any]] = []

    def submit(self, work: Callable[[], Any]) -> Future[Any]:
        self.submitted.append(work)
        future: Future[Any] = Future()
        try:
            future.set_result(work())
        except BaseException as exc:
            future.set_exception(exc)
        return future


class DeferredExecutor:
    def __init__(self) -> None:
        self.submitted: list[Callable[[], Any]] = []
        self.futures: list[Future[Any]] = []

    def submit(self, work: Callable[[], Any]) -> Future[Any]:
        self.submitted.append(work)
        future: Future[Any] = Future()
        self.futures.append(future)
        return future


class RaisingExecutor:
    def __init__(self, exception: RuntimeError) -> None:
        self.exception = exception
        self.submitted: list[Callable[[], Any]] = []

    def submit(self, work: Callable[[], Any]) -> Future[Any]:
        self.submitted.append(work)
        raise self.exception


class ForbiddenExecutor:
    def submit(self, _work: Callable[[], Any]) -> Future[Any]:
        raise AssertionError("software update work used the main executor")


class FakeVariable:
    def __init__(self, value: str) -> None:
        self.value = value
        self.set_calls: list[str] = []

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value
        self.set_calls.append(value)


class CachedUpdateService:
    def __init__(self, result: UpdateCheckResult) -> None:
        self.result = result
        self.startup_calls = 0
        self.gateway_fetches = 0
        self._cached: UpdateCheckResult | None = None

    def check_startup(self) -> UpdateCheckResult:
        self.startup_calls += 1
        if self._cached is None:
            self.gateway_fetches += 1
            self._cached = self.result
        return self._cached


def make_result(
    *,
    state: UpdateState = UpdateState.AVAILABLE,
    reason: UpdateInvocationReason = UpdateInvocationReason.STARTUP,
    release_sequence: int | None = 42,
    changed_components: tuple[str, ...] = ("launcher", "core"),
    diagnostic_code: UpdateDiagnosticCode | None = None,
) -> UpdateCheckResult:
    return UpdateCheckResult(
        state=state,
        invocation_reason=reason,
        release_id="release-42" if release_sequence is not None else None,
        release_sequence=release_sequence,
        changed_components=changed_components,
        launcher_version="2.0.0",
        core_version="3.0.0",
        mandatory=False,
        diagnostic_code=diagnostic_code,
    )


def build_window(
    service: Any,
    apply_service: Any = None,
) -> tuple[AppWindow, FakeRoot, ImmediateExecutor]:
    window = object.__new__(AppWindow)
    root = FakeRoot()
    update_executor = ImmediateExecutor()
    window.root = root  # type: ignore[assignment]
    window._closing = False
    window._update_check_service = service
    window._update_apply_service = apply_service
    window._update_executor = update_executor  # type: ignore[assignment]
    window._executor = ForbiddenExecutor()  # type: ignore[assignment]
    window._last_update_result = None
    window._diagnostics = None
    window._last_debug_status = None
    return window, root, update_executor


def capture_diagnostics(
    window: AppWindow,
) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    window._record_debug_status = (  # type: ignore[method-assign]
        lambda stage, **details: events.append((stage, details))
    )
    return events


def preserve_application_state(
    window: AppWindow,
    *,
    proxy_status: str = "running",
    game_process_running: bool = False,
) -> dict[str, Any]:
    controller = SimpleNamespace(
        state=SimpleNamespace(
            auth_status="authenticated",
            proxy_status=proxy_status,
            game_process_running=game_process_running,
        )
    )
    error = FakeVariable("existing error")
    notice = FakeVariable("existing notice")
    window._controller = controller
    window._error = error  # type: ignore[assignment]
    window._notice = notice  # type: ignore[assignment]
    return {
        "controller": controller,
        "controller_state": controller.state,
        "auth_status": controller.state.auth_status,
        "proxy_status": controller.state.proxy_status,
        "error": error,
        "error_value": error.get(),
        "notice": notice,
        "notice_value": notice.get(),
    }


def assert_application_state_unchanged(
    window: AppWindow,
    before: dict[str, Any],
) -> None:
    assert window._controller is before["controller"]
    assert window._controller.state is before["controller_state"]
    assert window._controller.state.auth_status == before["auth_status"]
    assert window._controller.state.proxy_status == before["proxy_status"]
    assert window._error is before["error"]
    assert window._error.get() == before["error_value"]
    assert window._error.set_calls == []
    assert window._notice is before["notice"]
    assert window._notice.get() == before["notice_value"]
    assert window._notice.set_calls == []


def assert_sanitized_internal_failure(
    diagnostics: list[tuple[str, dict[str, Any]]],
    secret: str,
) -> None:
    assert diagnostics
    assert all(secret not in repr(event) for event in diagnostics)
    assert diagnostics[-1][0] == "SOFTWARE_UPDATE_CHECK"
    assert (
        diagnostics[-1][1].get("diagnostic_code")
        == UpdateDiagnosticCode.UPDATE_CHECK_INTERNAL_FAILURE.value
    )


def test_constructor_accepts_optional_update_check_service() -> None:
    parameter = inspect.signature(AppWindow.__init__).parameters[
        "update_check_service"
    ]

    assert parameter.default is None
    assert parameter.annotation in (Any, "Any")


def test_constructor_defines_dedicated_single_worker_update_executor() -> None:
    source = inspect.getsource(AppWindow.__init__)

    assert "self._update_executor = ThreadPoolExecutor(" in source
    assert "max_workers=1" in source
    assert 'thread_name_prefix="neko-software-update"' in source


def test_constructor_schedules_startup_update_check_exactly_once() -> None:
    source = inspect.getsource(AppWindow.__init__)

    expected = "self.root.after(2000, self._check_software_update_startup)"
    alternate = "self.root.after(2_000, self._check_software_update_startup)"
    assert source.count(expected) + source.count(alternate) == 1


def test_repeated_startup_callbacks_use_update_executor_and_service_single_flight() -> None:
    result = make_result()
    service = CachedUpdateService(result)
    window, root, update_executor = build_window(service)

    window._check_software_update_startup()
    window._check_software_update_startup()
    root.run_callbacks()

    assert len(update_executor.submitted) == 2
    assert service.startup_calls == 2
    assert service.gateway_fetches == 1
    assert window._last_update_result is result


def test_manual_check_is_separately_callable_on_update_executor() -> None:
    result = make_result(reason=UpdateInvocationReason.MANUAL)
    calls = 0

    def check_manual() -> UpdateCheckResult:
        nonlocal calls
        calls += 1
        return result

    service = SimpleNamespace(check_manual=check_manual)
    window, root, update_executor = build_window(service)

    window._check_software_update_manual()
    root.run_callbacks()

    assert calls == 1
    assert len(update_executor.submitted) == 1
    assert window._last_update_result is result


def test_completed_check_stores_only_result_and_safe_diagnostic_fields() -> None:
    result = make_result(
        state=UpdateState.MANDATORY,
        release_sequence=73,
        changed_components=("launcher", "core"),
        diagnostic_code=UpdateDiagnosticCode.MANIFEST_REJECTED,
    )
    service = CachedUpdateService(result)
    window, root, _update_executor = build_window(service)
    diagnostics = capture_diagnostics(window)
    attributes_before = set(vars(window))

    window._check_software_update_startup()
    root.run_callbacks()

    assert window._last_update_result is result
    assert set(vars(window)) - attributes_before == set()
    assert diagnostics == [
        (
            "SOFTWARE_UPDATE_CHECK",
            {
                "state": UpdateState.MANDATORY.value,
                "release_sequence": 73,
                "changed_components": "launcher,core",
                "diagnostic_code": UpdateDiagnosticCode.MANIFEST_REJECTED.value,
            },
        )
    ]
    forbidden_fragments = ("envelope", "signature", "grant", "url")
    assert not any(
        fragment in key.lower()
        for key in vars(window)
        for fragment in forbidden_fragments
    )
    diagnostic_text = repr(diagnostics).lower()
    assert not any(fragment in diagnostic_text for fragment in forbidden_fragments)


def test_completed_check_logs_empty_or_none_diagnostic_code_safely() -> None:
    result = make_result(
        state=UpdateState.LATEST,
        changed_components=(),
        diagnostic_code=None,
    )
    service = CachedUpdateService(result)
    window, root, _update_executor = build_window(service)
    diagnostics = capture_diagnostics(window)

    window._check_software_update_startup()
    root.run_callbacks()

    assert len(diagnostics) == 1
    stage, details = diagnostics[0]
    assert stage == "SOFTWARE_UPDATE_CHECK"
    assert details["state"] == UpdateState.LATEST.value
    assert details["release_sequence"] == 42
    assert details["changed_components"] == ""
    assert details["diagnostic_code"] in ("", None)


def test_unavailable_result_does_not_mutate_auth_proxy_notice_or_error() -> None:
    result = make_result(
        state=UpdateState.UNAVAILABLE,
        release_sequence=None,
        changed_components=(),
        diagnostic_code=UpdateDiagnosticCode.MANIFEST_UNAVAILABLE,
    )
    service = CachedUpdateService(result)
    window, root, _update_executor = build_window(service)
    before = preserve_application_state(window)
    capture_diagnostics(window)

    window._check_software_update_startup()
    root.run_callbacks()

    assert window._last_update_result is result
    assert_application_state_unchanged(window, before)


def test_executor_shutdown_race_is_sanitized_and_clears_stale_result() -> None:
    secret = "SENTINEL_SHUTDOWN_DETAIL"
    service = SimpleNamespace(check_startup=lambda: make_result())
    window, _root, _update_executor = build_window(service)
    stale_result = make_result(state=UpdateState.LATEST)
    window._last_update_result = stale_result
    raising_executor = RaisingExecutor(RuntimeError(secret))
    window._update_executor = raising_executor  # type: ignore[assignment]
    diagnostics = capture_diagnostics(window)

    window._check_software_update_startup()

    assert len(raising_executor.submitted) == 1
    assert window._closing is False
    assert window._last_update_result is None
    assert len(diagnostics) == 1
    assert_sanitized_internal_failure(diagnostics, secret)


def test_unexpected_future_exception_clears_stale_result_without_state_mutation() -> None:
    secret = "signed-envelope-secret-grant-url"

    def check_startup() -> UpdateCheckResult:
        raise RuntimeError(secret)

    service = SimpleNamespace(check_startup=check_startup)
    window, root, update_executor = build_window(service)
    window._last_update_result = make_result(state=UpdateState.LATEST)
    before = preserve_application_state(window)
    diagnostics = capture_diagnostics(window)

    window._check_software_update_startup()
    root.run_callbacks()

    assert len(update_executor.submitted) == 1
    assert window._last_update_result is None
    assert_application_state_unchanged(window, before)
    assert_sanitized_internal_failure(diagnostics, secret)


def test_completed_future_after_close_does_not_mutate_result_diagnostics_or_state() -> None:
    pending_result = make_result(state=UpdateState.MANDATORY)
    stale_result = make_result(state=UpdateState.LATEST)
    service = SimpleNamespace(check_startup=lambda: pending_result)
    window, root, _update_executor = build_window(service)
    deferred_executor = DeferredExecutor()
    window._update_executor = deferred_executor  # type: ignore[assignment]
    window._last_update_result = stale_result
    before = preserve_application_state(window)
    diagnostics = capture_diagnostics(window)

    window._check_software_update_startup()

    assert len(deferred_executor.submitted) == 1
    assert len(deferred_executor.futures) == 1
    assert root.after_calls

    window._closing = True
    deferred_executor.futures[0].set_result(pending_result)
    root.run_callback_generation()

    assert window._last_update_result is stale_result
    assert diagnostics == []
    assert_application_state_unchanged(window, before)
    assert root.after_calls == []


def test_invalid_future_result_is_sanitized_and_clears_stale_result() -> None:
    secret = "SENTINEL_INVALID_RESULT_DETAIL"
    invalid_result = SimpleNamespace(secret=secret)
    service = SimpleNamespace(check_startup=lambda: invalid_result)
    window, root, update_executor = build_window(service)
    window._last_update_result = make_result(state=UpdateState.LATEST)
    before = preserve_application_state(window)
    diagnostics = capture_diagnostics(window)

    window._check_software_update_startup()
    root.run_callbacks()

    assert len(update_executor.submitted) == 1
    assert window._last_update_result is None
    assert_application_state_unchanged(window, before)
    assert_sanitized_internal_failure(diagnostics, secret)


def test_perform_close_shuts_down_update_executor_without_waiting() -> None:
    source = inspect.getsource(AppWindow._perform_close)

    assert "_update_executor" in source
    assert ".shutdown(wait=False, cancel_futures=True)" in source


def _is_update_action_enabled(window: AppWindow) -> bool:
    for name in (
        "_can_apply_software_update",
        "_is_update_action_available",
        "_is_update_action_enabled",
    ):
        fn = getattr(window, name, None)
        if callable(fn):
            return bool(fn())
        if isinstance(fn, bool):
            return fn
    btn = getattr(window, "_update_apply_button", None) or getattr(window, "_update_button", None)
    if btn is not None and hasattr(btn, "cget"):
        return str(btn.cget("state")) != "disabled"
    pytest.fail(
        "AppWindow update action availability contract not implemented",
        pytrace=False,
    )


def _trigger_update_action(window: AppWindow) -> None:
    for name in (
        "_apply_software_update",
        "_apply_software_update_manual",
        "_trigger_software_update_apply",
    ):
        fn = getattr(window, name, None)
        if callable(fn):
            fn()
            return
    btn = getattr(window, "_update_apply_button", None) or getattr(window, "_update_button", None)
    if btn is not None and hasattr(btn, "invoke"):
        btn.invoke()
        return
    pytest.fail(
        "AppWindow update apply action contract not implemented",
        pytrace=False,
    )


def test_update_action_enabled_only_when_update_available_and_proxy_and_game_idle() -> None:
    apply_service = SimpleNamespace(prepare=lambda: None)
    window, _root, _update_executor = build_window(None, apply_service=apply_service)

    controller = SimpleNamespace(
        state=SimpleNamespace(
            proxy_status="stopped",
            game_process_running=False,
        )
    )
    window._controller = controller

    # 1. AVAILABLE and idle -> Enabled
    window._last_update_result = make_result(state=UpdateState.AVAILABLE)
    assert _is_update_action_enabled(window) is True

    # 2. MANDATORY and idle -> Enabled
    window._last_update_result = make_result(state=UpdateState.MANDATORY)
    assert _is_update_action_enabled(window) is True

    # 3. LATEST and idle -> Disabled
    window._last_update_result = make_result(state=UpdateState.LATEST)
    assert _is_update_action_enabled(window) is False

    # 4. AVAILABLE and proxy running -> Disabled
    window._last_update_result = make_result(state=UpdateState.AVAILABLE)
    controller.state.proxy_status = "running"
    assert _is_update_action_enabled(window) is False
    controller.state.proxy_status = "stopped"

    # 5. AVAILABLE and game running -> Disabled
    controller.state.game_process_running = True
    assert _is_update_action_enabled(window) is False
    controller.state.game_process_running = False

    # 6. None result -> Disabled
    window._last_update_result = None
    assert _is_update_action_enabled(window) is False


def test_startup_check_never_calls_prepare_automatically() -> None:
    prepare_calls = 0

    def fake_prepare() -> Any:
        nonlocal prepare_calls
        prepare_calls += 1
        return None

    apply_service = SimpleNamespace(prepare=fake_prepare)
    check_service = CachedUpdateService(make_result(state=UpdateState.AVAILABLE))
    window, root, _update_executor = build_window(
        check_service,
        apply_service=apply_service,
    )

    window._check_software_update_startup()
    root.run_callbacks()

    assert window._last_update_result is not None
    assert window._last_update_result.state == UpdateState.AVAILABLE
    assert prepare_calls == 0


def test_manual_apply_click_submits_single_prepare_and_failed_prepare_keeps_launcher_alive() -> None:
    secret = "secret-manifest-grant-token-leak"
    prepare_calls = 0

    def failing_prepare() -> Any:
        nonlocal prepare_calls
        prepare_calls += 1
        raise RuntimeError(secret)

    apply_service = SimpleNamespace(prepare=failing_prepare)
    window, root, update_executor = build_window(None, apply_service=apply_service)
    window._last_update_result = make_result(state=UpdateState.AVAILABLE)
    before = preserve_application_state(window, proxy_status="stopped")
    diagnostics = capture_diagnostics(window)

    _trigger_update_action(window)

    assert len(update_executor.submitted) == 1
    assert prepare_calls == 1

    root.run_callbacks()

    assert window._closing is False
    assert window._controller.state.auth_status == before["auth_status"]
    assert window._controller.state.proxy_status == before["proxy_status"]
    assert secret not in window._error.get()
    assert all(secret not in repr(ev) for ev in diagnostics)


def test_successful_prepared_update_calls_perform_close_before_release_without_close_loop() -> None:
    call_order: list[str] = []

    class FakePrepared:
        def release(self) -> None:
            call_order.append("prepared.release")

    prepared = FakePrepared()
    apply_service = SimpleNamespace(prepare=lambda: prepared)
    window, root, _update_executor = build_window(None, apply_service=apply_service)
    window._last_update_result = make_result(state=UpdateState.AVAILABLE)
    window._controller = SimpleNamespace(
        state=SimpleNamespace(
            proxy_status="stopped",
            game_process_running=False,
        )
    )

    def fake_perform_close() -> None:
        call_order.append("_perform_close")
        window._closing = True

    window._perform_close = fake_perform_close  # type: ignore[method-assign]

    confirmation_invoked = False

    def fake_confirm(*_args: Any, **_kwargs: Any) -> bool:
        nonlocal confirmation_invoked
        confirmation_invoked = True
        return False

    window._confirm_game_active_action = fake_confirm  # type: ignore[method-assign]

    _trigger_update_action(window)
    root.run_callbacks()

    assert confirmation_invoked is False
    assert call_order == ["_perform_close", "prepared.release"]
