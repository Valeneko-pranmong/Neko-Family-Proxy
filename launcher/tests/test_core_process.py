import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neko_launcher.application.diagnostics import CoreDiagnosticsRecorder, NoopDiagnosticsSink
from neko_launcher.e2e.final_windows_harness import AdmittedArtifactFile, FinalCoreAdmission
from neko_launcher.infrastructure.core.core_process import WindowsCoreProcessAdapter


class FakeGuard:
    handle = "guard-handle"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeIdentityApi:
    def __init__(self, *, verified_hash="a" * 64, image_path=None, same_identity=True):
        self.verified_hash = verified_hash
        self.image_path = image_path
        self.same_identity = same_identity
        self.opened_path = None
        self.identity_calls = 0

    def open_guarded_read_handle(self, path):
        self.opened_path = path
        return FakeGuard()

    def sha256_file(self, _path):
        return self.verified_hash

    def file_identity(self, _handle):
        self.identity_calls += 1
        if self.same_identity:
            return (1, 2)
        return (1, 2) if self.identity_calls == 1 else (1, 3)

    def query_process_image_path(self, _process):
        return self.image_path


def _admission(path, digest="a" * 64, guarded_files=None):
    return FinalCoreAdmission(
        source_sha="b3c9d0851cff74691500c431c0da1ec30c21927a",
        artifact_path=path.parent,
        core_exe_sha256=digest,
        protected_payload_sha256="2" * 64,
        manifest_sha256="3" * 64,
        pso2_mode_sha256="4" * 64,
        manifest_controlled_file_count=245,
        physical_file_count=246,
        guarded_files=guarded_files
        or (AdmittedArtifactFile(Path("NekoProxyCore.exe"), digest),),
    )


def test_windows_core_process_uses_the_bundled_core_pipe_identity(tmp_path):
    adapter = WindowsCoreProcessAdapter(tmp_path / "NekoProxyCore.exe")

    assert adapter._pipe_name == "NekoProxyCoreControl"
    assert adapter.owned_process_id() is None


def test_core_process_environment_rejects_runtime_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOTNET_STARTUP_HOOKS", r"C:\unadmitted\hook.dll")
    monkeypatch.setenv("CORECLR_ENABLE_PROFILING", "1")
    monkeypatch.setenv("CORECLR_PROFILER_PATH", r"C:\unadmitted\profiler.dll")
    monkeypatch.setenv("PATH", r"C:\unadmitted")
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")

    clean = WindowsCoreProcessAdapter._clean_env()

    assert clean["SYSTEMROOT"] == r"C:\Windows"
    assert "DOTNET_STARTUP_HOOKS" not in clean
    assert "CORECLR_ENABLE_PROFILING" not in clean
    assert "CORECLR_PROFILER_PATH" not in clean
    assert "PATH" not in clean


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
    with patch("time.monotonic", side_effect=[0, 0.1, 0.2]), patch("time.sleep"):
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


@patch("subprocess.Popen")
def test_live_owned_host_is_reused_after_runtime_stop(mock_popen, tmp_path):
    process = MagicMock()
    process.pid = 1234
    process.poll.return_value = None
    mock_popen.return_value = process
    executable = tmp_path / "NekoProxyCore.exe"
    executable.touch()
    adapter = WindowsCoreProcessAdapter(executable)

    adapter.start_host_without_secrets()
    adapter.start_host_without_secrets()

    mock_popen.assert_called_once()
    assert adapter.owned_process_id() == 1234


@patch("subprocess.Popen")
def test_wait_uses_exact_owned_child_handle_and_releases_it(mock_popen, tmp_path):
    process = MagicMock()
    process.pid = 1234
    process.poll.return_value = None
    process.wait.return_value = 0
    mock_popen.return_value = process
    executable = tmp_path / "NekoProxyCore.exe"
    executable.touch()
    adapter = WindowsCoreProcessAdapter(executable)
    adapter.start_host_without_secrets()

    with pytest.raises(RuntimeError):
        adapter.wait_for_owned_process_exit(9999, 1.0)
    assert adapter.wait_for_owned_process_exit(1234, 1.0) == 0

    process.wait.assert_called_once_with(timeout=1.0)
    assert adapter.owned_process_id() is None


@patch("subprocess.Popen")
def test_emergency_fallback_targets_only_exact_retained_child_handle(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 1234
    process.poll.return_value = None
    process.wait.return_value = 1
    mock_popen.return_value = process
    executable = tmp_path / "NekoProxyCore.exe"
    executable.touch()
    adapter = WindowsCoreProcessAdapter(executable)
    adapter.start_host_without_secrets()

    assert adapter.terminate_owned_process_after_timeout(1234, 1.0) == 1

    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=1.0)


@patch("subprocess.Popen")
def test_admitted_core_spawn_proves_the_exact_child_image_and_file_identity(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 4321
    process.poll.return_value = None
    mock_popen.return_value = process
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")
    api = FakeIdentityApi(image_path=executable)
    adapter = WindowsCoreProcessAdapter(executable, identity_api=api)

    identity = adapter.start_admitted_core(_admission(executable))

    assert identity.pid == 4321
    assert identity.canonical_executable_path == executable
    assert identity.expected_sha256 == "a" * 64
    assert identity.verified_sha256 == "a" * 64
    assert identity.file_identity == (1, 2)
    mock_popen.assert_called_once()
    assert mock_popen.call_args.args[0] == [str(executable)]


@patch("subprocess.Popen")
def test_admitted_core_spawn_blocks_substitution_before_process_creation(
    mock_popen, tmp_path
):
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"substitute")
    api = FakeIdentityApi(verified_hash="b" * 64, image_path=executable)
    adapter = WindowsCoreProcessAdapter(executable, identity_api=api)

    with pytest.raises(RuntimeError, match="admitted Core artifact hash mismatch"):
        adapter.start_admitted_core(_admission(executable))

    mock_popen.assert_not_called()


@patch("subprocess.Popen")
def test_admitted_core_spawn_blocks_wrong_admission_hash(mock_popen, tmp_path):
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")
    api = FakeIdentityApi(verified_hash="a" * 64, image_path=executable)
    adapter = WindowsCoreProcessAdapter(executable, identity_api=api)

    with pytest.raises(RuntimeError, match="admitted Core artifact hash mismatch"):
        adapter.start_admitted_core(_admission(executable, "b" * 64))

    mock_popen.assert_not_called()


@patch("subprocess.Popen")
def test_admitted_core_spawn_cleans_exact_child_when_image_identity_cannot_be_proven(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 9876
    process.poll.return_value = None
    process.wait.return_value = 1
    mock_popen.return_value = process
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")
    api = FakeIdentityApi(image_path=executable, same_identity=False)
    adapter = WindowsCoreProcessAdapter(executable, identity_api=api)

    with pytest.raises(RuntimeError, match="Core process provenance could not be proven"):
        adapter.start_admitted_core(_admission(executable))

    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=1.0)
    assert adapter.owned_process_id() is None


@patch("subprocess.Popen")
def test_admitted_core_spawn_fails_closed_when_process_image_query_is_unavailable(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 9877
    process.poll.return_value = None
    process.wait.return_value = 1
    mock_popen.return_value = process
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")
    api = FakeIdentityApi(image_path=executable)
    api.query_process_image_path = MagicMock(side_effect=OSError("unavailable"))
    adapter = WindowsCoreProcessAdapter(executable, identity_api=api)

    with pytest.raises(OSError, match="unavailable"):
        adapter.start_admitted_core(_admission(executable))

    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=1.0)
    assert adapter.owned_process_id() is None


@patch("subprocess.Popen")
def test_admitted_core_spawn_fails_closed_when_child_exits_before_identity_proof(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 9878
    process.poll.return_value = 7
    process.wait.return_value = 7
    mock_popen.return_value = process
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")
    adapter = WindowsCoreProcessAdapter(
        executable,
        identity_api=FakeIdentityApi(image_path=executable),
    )

    with pytest.raises(RuntimeError, match="Core process provenance could not be proven"):
        adapter.start_admitted_core(_admission(executable))

    process.kill.assert_not_called()
    process.wait.assert_called_once_with(timeout=1.0)
    assert adapter.owned_process_id() is None


@patch("subprocess.Popen")
def test_admitted_core_spawn_rejects_actual_process_image_path_mismatch(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 9879
    process.poll.return_value = None
    process.wait.return_value = 1
    mock_popen.return_value = process
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")
    different = (tmp_path.parent / f"{tmp_path.name}-substituted.exe").resolve()
    different.write_bytes(b"core")
    adapter = WindowsCoreProcessAdapter(
        executable,
        identity_api=FakeIdentityApi(image_path=different),
    )

    with pytest.raises(RuntimeError, match="Core process provenance could not be proven"):
        adapter.start_admitted_core(_admission(executable))

    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=1.0)
    assert adapter.owned_process_id() is None


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file sharing semantics")
def test_verify_to_spawn_guard_prevents_toctou_substitution(tmp_path):
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"original")
    substitute_dir = tmp_path.parent / f"{tmp_path.name}-substitute-exe"
    substitute_dir.mkdir()
    substitute = substitute_dir / "substitute.exe"
    substitute.write_bytes(b"replacement")
    admission = _admission(executable, hashlib.sha256(b"original").hexdigest())
    substitution_accepted = False

    class SubstitutionProbeAdapter(WindowsCoreProcessAdapter):
        def _spawn_exact(self, guarded_executable):
            nonlocal substitution_accepted
            try:
                os.replace(substitute, guarded_executable)
            except PermissionError:
                raise RuntimeError("substitution prevented") from None
            substitution_accepted = True
            raise AssertionError("guard accepted executable substitution")

    adapter = SubstitutionProbeAdapter(executable)

    with pytest.raises(RuntimeError, match="substitution prevented"):
        adapter.start_admitted_core(admission)

    assert substitution_accepted is False
    assert executable.read_bytes() == b"original"
    assert adapter.owned_process_id() is None


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file sharing semantics")
def test_verify_to_spawn_guard_prevents_dependency_substitution(tmp_path):
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    dependency = (tmp_path / "NekoProxyCore.dll").resolve()
    substitute_dir = tmp_path.parent / f"{tmp_path.name}-substitute"
    substitute_dir.mkdir()
    substitute = substitute_dir / "substitute.dll"
    executable.write_bytes(b"core")
    dependency.write_bytes(b"dependency")
    substitute.write_bytes(b"replacement")
    admission = _admission(
        executable,
        hashlib.sha256(b"core").hexdigest(),
        (
            AdmittedArtifactFile(
                Path("NekoProxyCore.exe"), hashlib.sha256(b"core").hexdigest()
            ),
            AdmittedArtifactFile(
                Path("NekoProxyCore.dll"),
                hashlib.sha256(b"dependency").hexdigest(),
            ),
        ),
    )
    substitution_accepted = False

    class DependencySubstitutionProbeAdapter(WindowsCoreProcessAdapter):
        def _spawn_exact(self, _guarded_executable):
            nonlocal substitution_accepted
            try:
                os.replace(substitute, dependency)
            except PermissionError:
                raise RuntimeError("dependency substitution prevented") from None
            substitution_accepted = True
            raise AssertionError("guard accepted dependency substitution")

    adapter = DependencySubstitutionProbeAdapter(executable)

    with pytest.raises(RuntimeError, match="dependency substitution prevented"):
        adapter.start_admitted_core(admission)

    assert substitution_accepted is False
    assert dependency.read_bytes() == b"dependency"
    assert adapter.owned_process_id() is None


@patch("subprocess.Popen")
def test_admitted_core_spawn_rejects_unlisted_file_created_during_spawn(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 9880
    process.poll.return_value = None
    process.wait.return_value = 1
    mock_popen.return_value = process
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")

    class ExtraFileProbeAdapter(WindowsCoreProcessAdapter):
        def _spawn_exact(self, guarded_executable):
            (guarded_executable.parent / "injected.dll").write_bytes(b"injected")
            return super()._spawn_exact(guarded_executable)

    api = FakeIdentityApi(image_path=executable)
    adapter = ExtraFileProbeAdapter(executable, identity_api=api)

    with pytest.raises(RuntimeError, match="Core process provenance could not be proven"):
        adapter.start_admitted_core(_admission(executable))

    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=1.0)
    assert adapter.owned_process_id() is None


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file sharing semantics")
@patch("subprocess.Popen")
def test_admitted_artifact_guards_are_retained_until_exact_child_exit(
    mock_popen, tmp_path
):
    process = MagicMock()
    process.pid = 9881
    process.poll.return_value = None
    process.wait.return_value = 0
    mock_popen.return_value = process
    executable = (tmp_path / "NekoProxyCore.exe").resolve()
    executable.write_bytes(b"core")
    substitute_dir = tmp_path.parent / f"{tmp_path.name}-retained-guard"
    substitute_dir.mkdir()
    substitute = substitute_dir / "substitute.exe"
    substitute.write_bytes(b"replacement")
    digest = hashlib.sha256(b"core").hexdigest()
    adapter = WindowsCoreProcessAdapter(executable)
    adapter._identity_api.query_process_image_path = lambda _process: executable

    identity = adapter.start_admitted_core(_admission(executable, digest))

    with pytest.raises(PermissionError):
        os.replace(substitute, executable)
    assert adapter.wait_for_owned_process_exit(identity.pid, 1.0) == 0
    os.replace(substitute, executable)
    assert executable.read_bytes() == b"replacement"
