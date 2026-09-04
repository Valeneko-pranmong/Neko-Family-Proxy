from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

from neko_launcher.domain.models import AppState, ProxyStatus
from neko_launcher.ui.app_window import AppWindow


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, Callable[[], None]]] = []

    def winfo_exists(self) -> bool:
        return True

    def after(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self.after_calls.append((delay_ms, callback))


class FakeExecutor:
    def __init__(self, future: Future[Any]) -> None:
        self.future = future
        self.submit_calls = 0

    def submit(self, _work: Callable[[], Any]) -> Future[Any]:
        self.submit_calls += 1
        return self.future


def build_window(future: Future[Any]) -> tuple[AppWindow, FakeRoot, FakeExecutor]:
    root = FakeRoot()
    executor = FakeExecutor(future)
    window = object.__new__(AppWindow)
    window.root = root  # type: ignore[assignment]
    window._closing = False
    window._proxy_status_client = SimpleNamespace(fetch=lambda: None)
    window._proxy_status_refresh_pending = False
    window._proxy_status_executor = executor  # type: ignore[assignment]
    window._server_load = object()  # type: ignore[assignment]
    window._server_avg_download = object()  # type: ignore[assignment]
    window._server_avg_upload = object()  # type: ignore[assignment]
    window._server_average_window = object()  # type: ignore[assignment]
    window._set_if_changed = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    window._record_debug_status = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    return window, root, executor


def test_one_shot_none_result_normalizes_to_offline_without_exception_or_reschedule() -> None:
    future: Future[Any] = Future()
    future.set_result(None)
    window, root, _executor = build_window(future)
    window._public_server_host_status = "ONLINE"
    updated_values: list[tuple[Any, Any]] = []
    window._set_if_changed = lambda target, value: updated_values.append((target, value))  # type: ignore[method-assign]
    debug_events: list[tuple[str, dict[str, Any]]] = []
    window._record_debug_status = lambda event, **kwargs: debug_events.append((event, kwargs))  # type: ignore[method-assign]

    window._refresh_public_proxy_status()

    # Process local 100ms callbacks
    for delay, callback in root.after_calls:
        if delay == 100:
            callback()

    assert _executor.submit_calls == 1
    assert window._proxy_status_refresh_pending is False
    assert window._public_server_host_status == "OFFLINE"
    assert not any(delay_ms == 30_000 for delay_ms, _ in root.after_calls)
    assert (window._server_load, "ยังไม่มีข้อมูล") in updated_values
    assert (window._server_avg_download, "—") in updated_values
    assert (window._server_avg_upload, "—") in updated_values
    assert (window._server_average_window, "เฉลี่ย 30 นาที") in updated_values
    assert debug_events == [("PUBLIC_PROXY_STATUS_UNAVAILABLE", {"error": "no_result"})]


def test_public_proxy_status_fetch_is_one_shot_without_30_second_reschedule() -> None:
    future: Future[Any] = Future()
    future.set_exception(ConnectionError("offline"))
    window, root, _executor = build_window(future)

    window._refresh_public_proxy_status()

    # Process local 100ms callbacks
    for delay, callback in root.after_calls:
        if delay == 100:
            callback()

    assert _executor.submit_calls == 1
    assert window._proxy_status_refresh_pending is False
    assert not any(delay_ms == 30_000 for delay_ms, _ in root.after_calls)


def test_one_shot_result_normalizes_to_online() -> None:
    future: Future[Any] = Future()
    future.set_result(
        SimpleNamespace(
            host_status="ONLINE",
            load_label="ปานกลาง",
            load_level="moderate",
            avg_rx_bps=39_046,
            avg_tx_bps=33_913,
            covered_minutes=29,
            sample_count=29,
            age_seconds=5,
        )
    )
    window, root, _executor = build_window(future)
    window._public_server_host_status = None

    window._refresh_public_proxy_status()

    # Process local 100ms callbacks
    for delay, callback in root.after_calls:
        if delay == 100:
            callback()

    assert window._public_server_host_status == "ONLINE"


def test_one_shot_non_online_server_responses_normalize_to_offline() -> None:
    for non_online_status in ("DEGRADED", "STALE", "UNKNOWN", "OFFLINE", "ANY_OTHER"):
        future: Future[Any] = Future()
        future.set_result(
            SimpleNamespace(
                host_status=non_online_status,
                load_label="ยังไม่มีข้อมูล",
                load_level="unknown",
                avg_rx_bps=0,
                avg_tx_bps=0,
                covered_minutes=0,
                sample_count=0,
                age_seconds=None,
            )
        )
        window, root, _executor = build_window(future)
        window._public_server_host_status = None

        window._refresh_public_proxy_status()

        # Process local 100ms callbacks
        for delay, callback in root.after_calls:
            if delay == 100:
                callback()

        assert window._public_server_host_status == "OFFLINE"


def test_one_shot_fetch_failure_normalizes_to_offline() -> None:
    for exc in (
        TimeoutError("timed out"),
        ConnectionError("DNS failure"),
        ValueError("invalid JSON"),
        RuntimeError("request failed"),
    ):
        future: Future[Any] = Future()
        future.set_exception(exc)
        window, root, _executor = build_window(future)
        window._public_server_host_status = "ONLINE"

        window._refresh_public_proxy_status()

        # Process local 100ms callbacks
        for delay, callback in root.after_calls:
            if delay == 100:
                callback()

        assert window._public_server_host_status == "OFFLINE"


def test_idle_server_status_uses_one_shot_online_result() -> None:
    window = object.__new__(AppWindow)
    window._public_server_host_status = "ONLINE"

    assert window._get_server_status(AppState()) == ("ONLINE", "success")


def test_idle_server_status_uses_one_shot_offline_result() -> None:
    window = object.__new__(AppWindow)
    window._public_server_host_status = "OFFLINE"

    assert window._get_server_status(AppState()) == ("OFFLINE", "danger")


def test_idle_server_status_normalizes_any_non_online_or_missing_signal_to_offline() -> None:
    for state_val in ("DEGRADED", "STALE", "UNKNOWN", "OFFLINE", "OTHER"):
        window = object.__new__(AppWindow)
        window._public_server_host_status = state_val

        assert window._get_server_status(AppState()) == ("OFFLINE", "danger")


def test_idle_server_status_while_startup_fetch_is_pending() -> None:
    window = object.__new__(AppWindow)
    window._public_server_host_status = None
    assert window._get_server_status(AppState()) == ("กำลังเช็ค", "warning")


def test_startup_fetch_completes_asynchronously_and_resolves_pending_status() -> None:
    future: Future[Any] = Future()
    window, root, _executor = build_window(future)
    window._public_server_host_status = None
    server_status_var = SimpleNamespace(value="กำลังเช็ค")
    server_status_var.set = lambda val: setattr(server_status_var, "value", val)
    server_status_var.get = lambda: server_status_var.value
    window._server_status = server_status_var  # type: ignore[assignment]
    role_updates: list[str] = []
    window._dashboard_view = SimpleNamespace(
        update_server_status_role=lambda role: role_updates.append(role)
    )

    window._refresh_public_proxy_status()

    # While pending, status should be CHECKING (None) and presentation untouched
    assert window._public_server_host_status is None
    assert server_status_var.get() == "กำลังเช็ค"
    assert role_updates == []

    # Complete the SAME future asynchronously with ONLINE
    future.set_result(
        SimpleNamespace(
            host_status="ONLINE",
            load_label="ปานกลาง",
            load_level="moderate",
            avg_rx_bps=39_046,
            avg_tx_bps=33_913,
            covered_minutes=29,
            sample_count=29,
            age_seconds=5,
        )
    )

    # Process only local 100ms finish callbacks
    for delay, callback in root.after_calls:
        if delay == 100:
            callback()

    assert _executor.submit_calls == 1
    assert window._public_server_host_status == "ONLINE"
    assert server_status_var.get() == "ONLINE"
    assert role_updates == ["success"]


def test_startup_fetch_completes_asynchronously_and_resolves_offline_presentation() -> None:
    future: Future[Any] = Future()
    window, root, _executor = build_window(future)
    window._public_server_host_status = None
    server_status_var = SimpleNamespace(value="กำลังเช็ค")
    server_status_var.set = lambda val: setattr(server_status_var, "value", val)
    server_status_var.get = lambda: server_status_var.value
    window._server_status = server_status_var  # type: ignore[assignment]
    role_updates: list[str] = []
    window._dashboard_view = SimpleNamespace(
        update_server_status_role=lambda role: role_updates.append(role)
    )

    window._refresh_public_proxy_status()

    assert window._public_server_host_status is None
    assert server_status_var.get() == "กำลังเช็ค"
    assert role_updates == []

    # Complete the SAME future asynchronously with OFFLINE
    future.set_result(
        SimpleNamespace(
            host_status="OFFLINE",
            load_label="ยังไม่มีข้อมูล",
            load_level="unknown",
            avg_rx_bps=0,
            avg_tx_bps=0,
            covered_minutes=0,
            sample_count=0,
            age_seconds=None,
        )
    )

    # Process only local 100ms finish callbacks
    for delay, callback in root.after_calls:
        if delay == 100:
            callback()

    assert _executor.submit_calls == 1
    assert window._public_server_host_status == "OFFLINE"
    assert server_status_var.get() == "OFFLINE"
    assert role_updates == ["danger"]


def test_startup_fetch_failure_resolves_offline_presentation() -> None:
    future: Future[Any] = Future()
    window, root, _executor = build_window(future)
    window._public_server_host_status = None
    server_status_var = SimpleNamespace(value="กำลังเช็ค")
    server_status_var.set = lambda val: setattr(server_status_var, "value", val)
    server_status_var.get = lambda: server_status_var.value
    window._server_status = server_status_var  # type: ignore[assignment]
    role_updates: list[str] = []
    window._dashboard_view = SimpleNamespace(
        update_server_status_role=lambda role: role_updates.append(role)
    )

    window._refresh_public_proxy_status()

    assert window._public_server_host_status is None
    assert server_status_var.get() == "กำลังเช็ค"
    assert role_updates == []

    # Complete the future with an exception
    future.set_exception(ConnectionError("network down"))

    # Process only local 100ms finish callbacks
    for delay, callback in root.after_calls:
        if delay == 100:
            callback()

    assert _executor.submit_calls == 1
    assert window._public_server_host_status == "OFFLINE"
    assert server_status_var.get() == "OFFLINE"
    assert role_updates == ["danger"]


def test_startup_fetch_none_result_resolves_offline_presentation() -> None:
    future: Future[Any] = Future()
    window, root, _executor = build_window(future)
    window._public_server_host_status = None
    server_status_var = SimpleNamespace(value="กำลังเช็ค")
    server_status_var.set = lambda val: setattr(server_status_var, "value", val)
    server_status_var.get = lambda: server_status_var.value
    window._server_status = server_status_var  # type: ignore[assignment]
    role_updates: list[str] = []
    window._dashboard_view = SimpleNamespace(
        update_server_status_role=lambda role: role_updates.append(role)
    )

    window._refresh_public_proxy_status()

    assert window._public_server_host_status is None
    assert server_status_var.get() == "กำลังเช็ค"
    assert role_updates == []

    # Complete the future with None
    future.set_result(None)

    # Process only local 100ms finish callbacks
    for delay, callback in root.after_calls:
        if delay == 100:
            callback()

    assert _executor.submit_calls == 1
    assert window._public_server_host_status == "OFFLINE"
    assert server_status_var.get() == "OFFLINE"
    assert role_updates == ["danger"]


def test_core_running_and_lifecycle_states_not_overridden_by_public_status() -> None:
    window = object.__new__(AppWindow)
    window._public_server_host_status = "ONLINE"

    # Core starting / reconnecting / running / failed must not be overridden by idle public proxy status
    starting = AppState(proxy_status=ProxyStatus.STARTING)
    assert window._get_server_status(starting) == ("กำลังเชื่อมต่อ", "warning")

    reconnecting = AppState(proxy_status=ProxyStatus.RECONNECTING)
    assert window._get_server_status(reconnecting) == ("กำลังเชื่อมต่อ", "warning")

    failed = AppState(proxy_status=ProxyStatus.FAILED)
    assert window._get_server_status(failed) == ("ขัดข้อง", "danger")

    # When core is running without telemetry, it displays warning, not the idle one-shot status
    running = AppState(proxy_status=ProxyStatus.RUNNING, game_process_running=True)
    assert window._get_server_status(running, None) == ("ข้อมูลสถานะไม่พร้อม", "warning")





def test_never_completing_future_hits_ui_deadline_and_resolves_offline(monkeypatch: Any) -> None:
    future: Future[Any] = Future()
    window, root, executor = build_window(future)
    window._public_server_host_status = None
    server_status_var = SimpleNamespace(value="กำลังเช็ค")
    server_status_var.set = lambda val: setattr(server_status_var, "value", val)
    server_status_var.get = lambda: server_status_var.value
    window._server_status = server_status_var  # type: ignore[assignment]
    role_updates: list[str] = []
    window._dashboard_view = SimpleNamespace(
        update_server_status_role=lambda role: role_updates.append(role)
    )
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    window._refresh_public_proxy_status()

    assert window._proxy_status_refresh_pending is True
    assert server_status_var.get() == "กำลังเช็ค"

    callbacks = [callback for delay, callback in root.after_calls if delay == 100]
    root.after_calls.clear()
    now[0] = 10.0
    for callback in callbacks:
        callback()

    assert executor.submit_calls == 1
    assert window._proxy_status_refresh_pending is False
    assert window._public_server_host_status == "OFFLINE"
    assert server_status_var.get() == "OFFLINE"
    assert role_updates == ["danger"]
    assert not any(delay == 30_000 for delay, _ in root.after_calls)
