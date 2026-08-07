import pytest
from unittest.mock import patch, MagicMock
from neko_launcher.infrastructure.core.core_process import WindowsCoreProcessAdapter
from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder, NoopDiagnosticsSink


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
    
    # Simulate wait_for_control_channel with timeout
    mock_process.poll.return_value = 1
    with patch("time.monotonic", side_effect=[0, 0.1, 0.2, 0.3, 0.4, 0.5]):
        with patch("time.sleep"):
            try:
                adapter.wait_for_control_channel(0.15)
            except TimeoutError:
                pass
                
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
