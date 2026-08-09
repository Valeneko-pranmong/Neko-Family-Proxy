from unittest.mock import MagicMock, patch

import pytest

from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder, NoopDiagnosticsSink
from neko_launcher.infrastructure.core.core_process import WindowsCoreProcessAdapter


def test_windows_core_process_uses_the_bundled_core_pipe_identity(tmp_path):
    adapter = WindowsCoreProcessAdapter(tmp_path / "NekoProxyCore.exe")

    assert adapter._pipe_name == "NekoProxyCoreControl"
    assert adapter.owned_process_id() is None


@patch("subprocess.Popen")
def test_windows_core_process_adapter_runtime(mock_popen, tmp_path):
    mock_process = MagicMock()
    mock_process.pid = 1234
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    executable = tmp_path / "ProxyCore.exe"
    executable.touch()

    recorder = CoreDiagnosticsRecorder(NoopDiagnosticsSink())
    recorder.begin_attempt("TEST-1")

    adapter = WindowsCoreProcessAdapter(executable, diagnostics=recorder)
    adapter.start_host_without_secrets()

    assert adapter._process_started_at is not None
    assert adapter.owned_process_id() == 1234

    # An exited owned process fails immediately instead of accepting a stale pipe.
    mock_process.poll.return_value = 1
    assert adapter.owned_process_id() is None
    with patch("time.monotonic", side_effect=[0, 0.1, 0.2]):
        with patch("time.sleep"):
            with pytest.raises(RuntimeError):
                adapter.wait_for_control_channel(0.15)

    snapshot = recorder.snapshot()
    assert snapshot.process_event == "PROCESS_EXITED_EARLY"
    assert snapshot.exit_code == 1
    assert snapshot.runtime is not None

@patch("subprocess.Popen")
def test_windows_core_process_adapter_handles(mock_popen, tmp_path):
    mock_popen.side_effect = OSError("failed")
    executable = tmp_path / "ProxyCore.exe"
    executable.touch()

    adapter = WindowsCoreProcessAdapter(executable)
    adapter._stdout_handle = MagicMock()
    adapter._stderr_handle = MagicMock()

    with pytest.raises(OSError):
        adapter.start_host_without_secrets()

    assert adapter._stdout_handle is None
    assert adapter._stderr_handle is None
