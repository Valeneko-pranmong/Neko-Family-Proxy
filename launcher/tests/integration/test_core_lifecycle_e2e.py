from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from neko_launcher.application.authorized_core import CoreStatusKind
from neko_launcher.e2e.final_windows_harness import admit_final_core_artifact
from neko_launcher.infrastructure.core.core_control_channel import (
    NamedPipeCoreControlChannel,
)
from neko_launcher.infrastructure.core.core_process import WindowsCoreProcessAdapter


@pytest.mark.integration
@pytest.mark.skipif(os.name != "nt", reason="requires Windows named pipes")
def test_frozen_core_stop_then_graceful_host_shutdown_and_restart() -> None:
    configured = os.getenv("NEKO_FINAL_CORE_ARTIFACT_PATH")
    try:
        admission = admit_final_core_artifact(Path(configured) if configured else None)
    except ValueError as exc:
        pytest.fail(str(exc))
    executable = admission.artifact_path / "NekoProxyCore.exe"

    process = WindowsCoreProcessAdapter(executable)
    channel = NamedPipeCoreControlChannel(
        "NekoProxyCoreControl",
        expected_server_pid=process.owned_process_id,
    )

    def cleanup_exact_owned_child() -> None:
        pid = process.owned_process_id()
        if pid is not None:
            process.terminate_owned_process_after_timeout(pid, 5.0)

    try:
        process.start_host_without_secrets()
        process.wait_for_control_channel(10.0)
        first_pid = process.owned_process_id()
        assert first_pid is not None

        assert channel.status(uuid4().hex, 5.0).kind is CoreStatusKind.STOPPED
        assert len(channel.request_challenge(uuid4().hex, 5.0).value) == 43
        assert channel.stop(uuid4().hex, 5.0).kind is CoreStatusKind.STOPPED
        assert channel.status(uuid4().hex, 5.0).kind is CoreStatusKind.STOPPED
        assert process.owned_process_id() == first_pid

        assert channel.shutdown(uuid4().hex, 5.0).kind is CoreStatusKind.STOPPED
        assert process.wait_for_owned_process_exit(first_pid, 10.0) == 0

        process.start_host_without_secrets()
        process.wait_for_control_channel(10.0)
        second_pid = process.owned_process_id()
        assert second_pid is not None
        assert channel.status(uuid4().hex, 5.0).kind is CoreStatusKind.STOPPED

        assert channel.shutdown(uuid4().hex, 5.0).kind is CoreStatusKind.STOPPED
        assert process.wait_for_owned_process_exit(second_pid, 10.0) == 0
    finally:
        cleanup_exact_owned_child()
