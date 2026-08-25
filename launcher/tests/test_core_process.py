import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from neko_launcher.infrastructure.core.core_process import (
    WindowsCoreProcessAdapter,
    _create_lifetime_job,
    _NoopLifetimeJob,
)


class FakeLifetimeJob:
    def __init__(self) -> None:
        self.spawned: list[list[str]] = []
        self.closed = False

    def spawn(
        self,
        command: list[str],
        *,
        cwd: str,
        creationflags: int,
        env: dict[str, str],
    ) -> MagicMock:
        self.spawned.append(command)
        process = MagicMock(spec=subprocess.Popen)
        process.pid = 4242
        process.poll.return_value = None
        process.args = command
        return process

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_job(monkeypatch: pytest.MonkeyPatch) -> FakeLifetimeJob:
    job = FakeLifetimeJob()
    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_process._create_lifetime_job",
        lambda: job,
    )
    return job


def test_windows_core_process_uses_the_bundled_core_pipe_identity(tmp_path):
    adapter = WindowsCoreProcessAdapter(tmp_path / "NekoProxyCore.exe")

    assert adapter._pipe_name == "NekoProxyCoreControl"
    assert adapter.owned_process_id() is None


def test_core_process_environment_rejects_runtime_injection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COR_ENABLE_PROFILING", "1")
    monkeypatch.setenv("CORECLR_ENABLE_PROFILING", "1")
    monkeypatch.setenv("CORECLR_PROFILER", "{deadbeef}")
    monkeypatch.setenv("DOTNET_ADDITIONAL_DEPS", "/tmp/evil")

    env = WindowsCoreProcessAdapter._clean_env()

    for forbidden in (
        "COR_ENABLE_PROFILING",
        "CORECLR_ENABLE_PROFILING",
        "CORECLR_PROFILER",
        "DOTNET_ADDITIONAL_DEPS",
    ):
        assert forbidden not in env


def test_host_start_spawns_core_bound_to_launcher_kill_on_close_lifetime(
    tmp_path: Path, fake_job: FakeLifetimeJob
) -> None:
    (tmp_path / "NekoProxyCore.exe").write_bytes(b"core")
    adapter = WindowsCoreProcessAdapter(tmp_path / "NekoProxyCore.exe")

    adapter.start_host_without_secrets()

    assert fake_job.spawned == [[str(tmp_path / "NekoProxyCore.exe")]]
    assert adapter.owned_process_id() == 4242
    adapter._close_lifetime_job()


def test_host_start_spawn_failure_closes_lifetime_job(
    tmp_path: Path, fake_job: FakeLifetimeJob
) -> None:
    executable = tmp_path / "missing" / "NekoProxyCore.exe"

    adapter = WindowsCoreProcessAdapter(executable)

    with pytest.raises(FileNotFoundError):
        adapter.start_host_without_secrets()


def test_admitted_core_spawn_uses_lifetime_bound_child(
    tmp_path: Path, fake_job: FakeLifetimeJob
) -> None:
    from neko_launcher.e2e.final_windows_harness import (
        AdmittedArtifactFile,
        FinalCoreAdmission,
    )

    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    exe = artifact_root / "NekoProxyCore.exe"
    exe.write_bytes(b"core")

    class FakeGuard:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeIdentityApi:
        def open_guarded_read_handle(self, path):
            return FakeGuard()

        def sha256_file(self, path):
            return "a" * 64

        def file_identity(self, handle):
            return (1, 2)

        def query_process_image_path(self, process):
            return Path(process.args[0])

    admission = FinalCoreAdmission(
        source_sha="b3c9d0851cff74691500c431c0da1ec30c21927a",
        artifact_path=artifact_root,
        core_exe_sha256="a" * 64,
        protected_payload_sha256="2" * 64,
        manifest_sha256="3" * 64,
        pso2_mode_sha256="4" * 64,
        manifest_controlled_file_count=245,
        physical_file_count=246,
        guarded_files=(AdmittedArtifactFile(Path("NekoProxyCore.exe"), "a" * 64),),
    )
    adapter = WindowsCoreProcessAdapter(
        exe,
        identity_api=FakeIdentityApi(),  # type: ignore[arg-type]
    )

    provenance = adapter.start_admitted_core(admission)

    assert fake_job.spawned == [[str(exe)]]
    assert provenance.pid == 4242
    assert provenance.expected_sha256 == "a" * 64


def test_admitted_core_requires_live_lifetime_job_after_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spawned child must never outlive a missing kill-on-close owner."""
    from neko_launcher.e2e.final_windows_harness import (
        AdmittedArtifactFile,
        FinalCoreAdmission,
    )

    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    exe = artifact_root / "NekoProxyCore.exe"
    exe.write_bytes(b"core")

    class FakeGuard:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class VanishingJob(FakeLifetimeJob):
        def spawn(self, command, *, cwd, creationflags, env):
            process = super().spawn(
                command,
                cwd=cwd,
                creationflags=creationflags,
                env=env,
            )
            # Simulate the Job handle disappearing between spawn and return.
            adapter._lifetime_job = None
            return process

    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_process._create_lifetime_job",
        lambda: VanishingJob(),
    )

    class FakeIdentityApi:
        def open_guarded_read_handle(self, path):
            return FakeGuard()

        def sha256_file(self, path):
            return "a" * 64

        def file_identity(self, handle):
            return (1, 2)

        def query_process_image_path(self, process):
            return Path(process.args[0])

    admission = FinalCoreAdmission(
        source_sha="b3c9d0851cff74691500c431c0da1ec30c21927a",
        artifact_path=artifact_root,
        core_exe_sha256="a" * 64,
        protected_payload_sha256="2" * 64,
        manifest_sha256="3" * 64,
        pso2_mode_sha256="4" * 64,
        manifest_controlled_file_count=245,
        physical_file_count=246,
        guarded_files=(AdmittedArtifactFile(Path("NekoProxyCore.exe"), "a" * 64),),
    )
    adapter = WindowsCoreProcessAdapter(
        exe,
        identity_api=FakeIdentityApi(),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="lifetime job is unavailable"):
        adapter.start_admitted_core(admission)


def test_cleanup_failed_spawn_closes_lifetime_job(tmp_path, fake_job) -> None:
    executable = tmp_path / "NekoProxyCore.exe"
    executable.write_bytes(b"core")
    adapter = WindowsCoreProcessAdapter(executable)
    process = MagicMock(spec=subprocess.Popen)
    process.poll.return_value = None

    adapter._spawn_lifetime_bound(executable)
    assert fake_job.closed is False

    adapter._cleanup_failed_spawn(process)

    assert fake_job.closed is True
    assert adapter.owned_process_id() is None


def test_create_lifetime_job_selects_noop_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(
        "neko_launcher.infrastructure.core.core_process.os.name",
        "posix",
    )
    assert isinstance(_create_lifetime_job(), _NoopLifetimeJob)
