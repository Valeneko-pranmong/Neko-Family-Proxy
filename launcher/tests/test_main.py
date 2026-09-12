from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from neko_launcher.main import _report_startup_error, main
from neko_launcher.bootstrap.pending_update_bootstrap import (
    PendingUpdateBootstrapResult,
)
from neko_launcher.bootstrap.single_instance import (
    acquire_instance_mutex,
    release_instance_mutex,
)
from neko_launcher.infrastructure.unavailable_gateway import (
    AuthorizationPendingProxyGateway,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex behavior")
def test_instance_mutex_rejects_a_second_launcher_process() -> None:
    name = f"Local\\NekoFamilyProxyLauncher-Test-{uuid4()}"
    first = acquire_instance_mutex(name)
    assert first is not None
    try:
        assert acquire_instance_mutex(name) is None
    finally:
        release_instance_mutex(first)

    replacement = acquire_instance_mutex(name)
    assert replacement is not None
    release_instance_mutex(replacement)


def test_pending_authorization_contract_fails_closed_without_starting_core() -> None:
    gateway = AuthorizationPendingProxyGateway()

    with pytest.raises(RuntimeError, match="authorization integration is unavailable"):
        gateway.start()

    gateway.stop()


def test_startup_error_report_does_not_persist_or_display_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sentinel = "sentinel-startup-token"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    messages: list[str] = []
    monkeypatch.setattr(
        "neko_launcher.main._show_startup_error_message",
        lambda message: messages.append(message),
    )

    try:
        raise RuntimeError(sentinel)
    except RuntimeError as exc:
        _report_startup_error(exc)

    log_text = (tmp_path / "NEKO FAMILY" / "launcher-error.log").read_text(
        encoding="utf-8"
    )
    assert sentinel not in log_text
    assert "Traceback" not in log_text
    assert messages and sentinel not in messages[0]


def test_main_bootstrap_handoff_started_exits_before_building_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    exit_codes: list[int] = []

    monkeypatch.setattr("neko_launcher.main.maybe_dispatch_updater_entry", lambda args: False)
    monkeypatch.setattr(
        "neko_launcher.main.acquire_instance_mutex",
        lambda: events.append("acquire_mutex") or 4321,
    )
    monkeypatch.setattr(
        "neko_launcher.main.release_instance_mutex",
        lambda handle: events.append(f"release_mutex_{handle}"),
    )
    monkeypatch.setattr(
        "neko_launcher.main.run_pending_update_bootstrap",
        lambda: events.append("run_bootstrap") or PendingUpdateBootstrapResult.HANDOFF_STARTED,
    )
    monkeypatch.setattr(
        "neko_launcher.main.build_window",
        lambda: events.append("build_window"),
    )
    monkeypatch.setattr("os._exit", lambda code: exit_codes.append(code))

    main()

    assert events == ["acquire_mutex", "run_bootstrap", "release_mutex_4321"]
    assert "build_window" not in events
    assert exit_codes == [0]


def test_main_bootstrap_none_or_deferred_proceeds_to_build_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for result_val in (
        PendingUpdateBootstrapResult.NONE,
        PendingUpdateBootstrapResult.DEFERRED,
    ):
        events: list[str] = []
        exit_codes: list[int] = []

        monkeypatch.setattr("neko_launcher.main.maybe_dispatch_updater_entry", lambda args: False)
        monkeypatch.setattr(
            "neko_launcher.main.acquire_instance_mutex",
            lambda: events.append("acquire_mutex") or 5678,
        )
        monkeypatch.setattr(
            "neko_launcher.main.release_instance_mutex",
            lambda handle: events.append(f"release_mutex_{handle}"),
        )
        monkeypatch.setattr(
            "neko_launcher.main.run_pending_update_bootstrap",
            lambda: events.append("run_bootstrap") or result_val,
        )

        mock_root = MagicMock()
        mock_window = MagicMock(root=mock_root)
        monkeypatch.setattr(
            "neko_launcher.main.build_window",
            lambda: events.append("build_window") or mock_window,
        )
        monkeypatch.setattr("os._exit", lambda code: exit_codes.append(code))

        main()

        assert events == ["acquire_mutex", "run_bootstrap", "build_window", "release_mutex_5678"]
        mock_root.mainloop.assert_called_once()
        assert exit_codes == [0]
