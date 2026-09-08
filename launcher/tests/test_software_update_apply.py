from __future__ import annotations

import base64
import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from neko_launcher.infrastructure.github_asset_downloader import (
    DownloadedArtifact,
    GitHubAssetDownloadError,
)
from neko_launcher.infrastructure.github_release import (
    GitHubRelease,
    GitHubReleaseAsset,
)
from neko_launcher.infrastructure.github_release_binding import (
    CORE_ASSET_NAME,
    LAUNCHER_ASSET_NAME,
    RELEASE_MANIFEST_ASSET_NAME,
    UPDATER_ASSET_NAME,
    AuthenticatedReleaseGateway,
    GitHubReleaseResolverError,
    ResolvedGitHubRelease,
)
from neko_launcher.infrastructure.software_update_v2 import (
    V2ReleaseManifestVerifierAdapter,
)
from neko_launcher.updater.canonical_json import (
    canonical_json_dumps,
    canonical_json_loads,
)
from neko_launcher.updater.manifest_v2 import (
    UPDATER_PROTOCOL_VERSION,
    parse_release_v2,
)
from neko_launcher.updater.staging_handoff import handle_begin_request
from neko_launcher.updater.state_models import Binding, Generation, State

try:
    from tests.software_update_helpers import (
        TEST_KEY_ID,
        TEST_PUBLIC_KEY,
        signed_envelope,
        valid_v2_release_document,
    )
except ImportError:
    from software_update_helpers import (  # type: ignore[no-redef]
        TEST_KEY_ID,
        TEST_PUBLIC_KEY,
        signed_envelope,
        valid_v2_release_document,
    )


def _get_apply_api() -> tuple[Any, Any, Any]:
    try:
        import neko_launcher.infrastructure.software_update_apply as mod

        service_cls = getattr(mod, "SoftwareUpdateApplyService", None)
        prepared_cls = getattr(mod, "PreparedUpdate", None)
        error_cls = getattr(mod, "SoftwareUpdateApplyError", None)
        if (
            service_cls is not None
            and prepared_cls is not None
            and error_cls is not None
        ):
            return service_cls, prepared_cls, error_cls
    except ImportError:
        pass
    pytest.fail(
        "neko_launcher.infrastructure.software_update_apply API not implemented",
        pytrace=False,
    )


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.stdin: Any = None
        self.stdout: Any = None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class FakeSpawner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.process = FakeProcess()

    def __call__(self, command: list[str], **kwargs: Any) -> FakeProcess:
        self.calls.append({"command": list(command), "kwargs": kwargs})
        return self.process

    def spawn(self, command: list[str], **kwargs: Any) -> FakeProcess:
        return self(command, **kwargs)


class FakeChannel:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send_message(
        self,
        type: str,
        body: dict[str, Any],
        message_id: str | None = None,
    ) -> str:
        mid = message_id or f"msg-{len(self.sent)}"
        self.sent.append({"type": type, "body": body, "message_id": mid})
        return mid

    def receive_message(self, timeout_s: float = 5.0) -> Any:
        if self.closed:
            raise EOFError("channel closed")
        if not self.responses:
            raise TimeoutError("no more queued broker responses")
        resp = self.responses.pop(0)
        return SimpleNamespace(
            type=resp["type"],
            message_id=resp.get("message_id"),
            body=resp.get("body", {}),
        )

    def close(self) -> None:
        self.closed = True


class FakeAssetDownloader:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def download(
        self,
        *,
        initial_url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> DownloadedArtifact:
        self.calls.append(
            {
                "initial_url": initial_url,
                "destination": destination,
                "expected_size": expected_size,
                "expected_sha256": expected_sha256,
            }
        )
        if self.fail:
            raise GitHubAssetDownloadError("DOWNLOAD_UNAVAILABLE")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"downloaded-payload")
        return DownloadedArtifact(size=expected_size, sha256=expected_sha256)


class FakeReleaseGateway:
    def __init__(
        self,
        resolved: ResolvedGitHubRelease | None = None,
        error: Exception | None = None,
    ) -> None:
        self.resolved = resolved
        self.error = error
        self.calls = 0

    def resolve(self) -> ResolvedGitHubRelease | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.resolved


def make_resolved_release(
    sequence: int = 50,
    *,
    launcher_version: str = "2.0.0",
    core_version: str = "3.0.0",
    launcher_sha: str = "1" * 64,
    core_sha: str = "2" * 64,
    updater_sha: str = "3" * 64,
    launcher_size: int = 1024,
    core_size: int = 2048,
    updater_size: int = 4096,
) -> ResolvedGitHubRelease:
    doc = valid_v2_release_document(
        sequence=sequence,
        release_id=f"r-{sequence}-test",
        launcher_version=launcher_version,
        launcher_sha=launcher_sha,
        launcher_size=launcher_size,
        core_version=core_version,
        core_sha=core_sha,
        core_size=core_size,
        updater_sha=updater_sha,
        updater_size=updater_size,
    )
    envelope = signed_envelope(doc)
    envelope_bytes = canonical_json_dumps(envelope)

    adapter = V2ReleaseManifestVerifierAdapter(
        {TEST_KEY_ID: TEST_PUBLIC_KEY},
        updater_protocol=UPDATER_PROTOCOL_VERSION,
    )
    auth_release = adapter.verify(envelope)
    auth_release_v2 = parse_release_v2(doc)

    manifest_asset = GitHubReleaseAsset(
        id=1,
        name=RELEASE_MANIFEST_ASSET_NAME,
        size=len(envelope_bytes),
        browser_download_url=f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/release-v2.json",
    )
    launcher_asset = GitHubReleaseAsset(
        id=2,
        name=LAUNCHER_ASSET_NAME,
        size=launcher_size,
        browser_download_url=f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoLauncher.exe",
    )
    updater_asset = GitHubReleaseAsset(
        id=3,
        name=UPDATER_ASSET_NAME,
        size=updater_size,
        browser_download_url=f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoUpdater.exe",
    )
    core_asset = GitHubReleaseAsset(
        id=4,
        name=CORE_ASSET_NAME,
        size=core_size,
        browser_download_url=f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v{launcher_version}/NekoProxyCore.zip",
    )
    gh_release = GitHubRelease(
        id=999,
        tag_name=f"v{launcher_version}",
        draft=False,
        prerelease=False,
        assets=(manifest_asset, launcher_asset, updater_asset, core_asset),
    )

    return ResolvedGitHubRelease(
        authenticated_release=auth_release,
        authenticated_release_v2=auth_release_v2,
        envelope_bytes=envelope_bytes,
        envelope_document=envelope,
        github_release=gh_release,
        manifest_asset=manifest_asset,
        launcher_asset=launcher_asset,
        updater_asset=updater_asset,
        core_asset=core_asset,
    )


def _metadata_only_responses(
    *,
    ready_body: dict[str, Any] | None = None,
    apply_body: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    default_ready = {
        "accepted": True,
        "request_id": "req-strict",
        "transaction_id": "tx-strict",
        "changed": {"launcher": False, "core": False},
        "error": None,
    }
    default_apply = {
        "accepted": True,
        "transaction_id": "tx-strict",
        "error": None,
    }
    return [
        {
            "type": "REQUEST_READY",
            "message_id": "msg-0",
            "body": default_ready if ready_body is None else ready_body,
        },
        {
            "type": "APPLY_RESULT",
            "message_id": "msg-1",
            "body": default_apply if apply_body is None else apply_body,
        },
    ]


def test_software_update_apply_service_contract() -> None:
    service_cls, _, _ = _get_apply_api()
    sig = inspect.signature(service_cls.__init__)
    params = tuple(sig.parameters)
    assert params == (
        "self",
        "root_dir",
        "release_gateway",
        "asset_downloader",
        "spawner",
        "channel_factory",
    )


def test_prepare_success_spawns_helper_downloads_changed_and_returns_prepared(
    tmp_path: Path,
) -> None:
    service_cls, prepared_cls, _ = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()

    request_id = "req-xyz-101"
    transaction_id = "tx-abc-202"
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": request_id,
                    "transaction_id": transaction_id,
                    "changed": {"launcher": True, "core": True},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": transaction_id,
                    "error": None,
                },
            },
        ]
    )

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    prepared = service.prepare()

    assert isinstance(prepared, prepared_cls)
    assert gateway.calls == 1
    assert len(spawner.calls) == 1
    assert spawner.calls[0]["command"] == [
        str(tmp_path / "NekoUpdater.exe"),
        "--session",
    ]

    # Verify BEGIN message sent exact envelope bytes as base64
    assert len(channel.sent) == 2
    begin_msg = channel.sent[0]
    assert begin_msg["type"] == "BEGIN"
    raw_env_bytes = base64.b64decode(begin_msg["body"]["envelope_b64"])
    assert raw_env_bytes == resolved.envelope_bytes

    # Verify downloads: both launcher and core
    assert len(downloader.calls) == 2
    incoming_dir = tmp_path / "incoming" / request_id
    launcher_call = next(
        c for c in downloader.calls if c["destination"] == incoming_dir / "launcher.artifact"
    )
    core_call = next(
        c for c in downloader.calls if c["destination"] == incoming_dir / "core.artifact.zip"
    )
    assert launcher_call["initial_url"] == resolved.launcher_asset.browser_download_url
    assert launcher_call["expected_size"] == resolved.authenticated_release_v2.components["launcher"].artifact_size
    assert launcher_call["expected_sha256"] == resolved.authenticated_release_v2.components["launcher"].artifact_sha256

    assert core_call["initial_url"] == resolved.core_asset.browser_download_url
    assert core_call["expected_size"] == resolved.authenticated_release_v2.components["core"].artifact_size
    assert core_call["expected_sha256"] == resolved.authenticated_release_v2.components["core"].artifact_sha256

    # Verify APPLY message sent
    apply_msg = channel.sent[1]
    assert apply_msg["type"] == "APPLY"
    assert apply_msg["body"] == {
        "transaction_id": transaction_id,
        "request_id": request_id,
    }


def test_prepare_mandatory_resolver_refetch(tmp_path: Path) -> None:
    service_cls, _, _ = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()

    def make_channel() -> FakeChannel:
        return FakeChannel(_metadata_only_responses())

    spawner = FakeSpawner()
    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=make_channel,
    )

    service.prepare()
    service.prepare()
    assert gateway.calls == 2


def test_prepare_metadata_only_skips_downloads_and_sends_apply(
    tmp_path: Path,
) -> None:
    service_cls, prepared_cls, _ = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()
    channel = FakeChannel(_metadata_only_responses())

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    prepared = service.prepare()
    assert isinstance(prepared, prepared_cls)
    assert len(downloader.calls) == 0
    assert len(channel.sent) == 2
    assert channel.sent[1]["type"] == "APPLY"


def test_prepare_launcher_only_download(tmp_path: Path) -> None:
    service_cls, _, _ = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()
    request_id = "req-launcher-only"
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": request_id,
                    "transaction_id": "tx-l",
                    "changed": {"launcher": True, "core": False},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-l",
                    "error": None,
                },
            },
        ]
    )

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    service.prepare()
    assert len(downloader.calls) == 1
    assert downloader.calls[0]["destination"] == tmp_path / "incoming" / request_id / "launcher.artifact"


def test_prepare_core_only_download(tmp_path: Path) -> None:
    service_cls, _, _ = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()
    request_id = "req-core-only"
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": request_id,
                    "transaction_id": "tx-c",
                    "changed": {"launcher": False, "core": True},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-c",
                    "error": None,
                },
            },
        ]
    )

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    service.prepare()
    assert len(downloader.calls) == 1
    assert downloader.calls[0]["destination"] == tmp_path / "incoming" / request_id / "core.artifact.zip"


@pytest.mark.parametrize(
    "error",
    [
        GitHubReleaseResolverError("RELEASE_MANIFEST_REJECTED"),
        GitHubReleaseResolverError("UPDATER_INCOMPATIBLE"),
        GitHubReleaseResolverError("GITHUB_RELEASE_UNAVAILABLE"),
        None,  # gateway.resolve() returning None
    ],
)
def test_prepare_resolver_failure_rejects_before_spawner(
    tmp_path: Path,
    error: Exception | None,
) -> None:
    service_cls, _, error_cls = _get_apply_api()
    gateway = FakeReleaseGateway(resolved=None, error=error)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
    )

    with pytest.raises(error_cls):
        service.prepare()

    # Spawner must NEVER be called if resolver fails
    assert len(spawner.calls) == 0


def test_cross_boundary_canonical_envelope_regression(tmp_path: Path) -> None:
    service_cls, _, _ = _get_apply_api()
    resolved = make_resolved_release(2)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()

    sent_envelopes: list[str] = []

    class CapturingChannel(FakeChannel):
        def send_message(
            self,
            type: str,
            body: dict[str, Any],
            message_id: str | None = None,
        ) -> str:
            if type == "BEGIN":
                sent_envelopes.append(body["envelope_b64"])
            return super().send_message(type, body, message_id)

    channel = CapturingChannel(_metadata_only_responses())
    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    service.prepare()

    assert len(sent_envelopes) == 1
    forwarded_b64 = sent_envelopes[0]
    forwarded_bytes = base64.b64decode(forwarded_b64)
    # Byte-identical to resolver canonical exact bytes
    assert forwarded_bytes == resolved.envelope_bytes

    # Prove staging_handoff accepts those exact bytes
    initial_binding = Binding(release_sequence=1, release_id="rel-1", payload_sha256="1" * 64)
    committed_gen = Generation(
        binding=initial_binding,
        launcher_identity_sha256="a" * 64,
        core_identity_sha256="b" * 64,
    )
    current_state = State(
        schema_version=1,
        revision=1,
        installation_id="1" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=committed_gen,
        previous=None,
        highwater=initial_binding,
        observed=initial_binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={},
    )
    keys = {TEST_KEY_ID: TEST_PUBLIC_KEY}
    ready_res, next_state = handle_begin_request(tmp_path, current_state, forwarded_b64, keys)
    assert ready_res.accepted is True
    assert ready_res.error is None
    assert next_state is not None


def test_prepared_update_release_closes_channel_without_terminating_helper(
    tmp_path: Path,
) -> None:
    service_cls, _, _ = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()
    channel = FakeChannel(_metadata_only_responses())

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    prepared = service.prepare()
    assert channel.closed is False
    assert spawner.process.terminated is False
    assert spawner.process.killed is False

    prepared.release()
    assert channel.closed is True
    assert spawner.process.terminated is False
    assert spawner.process.killed is False


def test_prepare_aborts_and_raises_when_begin_rejected(tmp_path: Path) -> None:
    service_cls, _, error_cls = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": False,
                    "request_id": None,
                    "transaction_id": None,
                    "changed": None,
                    "error": "DOWNGRADE_REJECTED",
                },
            }
        ]
    )

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert exc_info.value.code == "BEGIN_REJECTED"
    assert spawner.process.terminated or spawner.process.killed


def test_prepare_aborts_and_raises_when_message_id_mismatched_or_malformed(
    tmp_path: Path,
) -> None:
    service_cls, _, error_cls = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "mismatched-non-echoed-id",
                "body": {
                    "accepted": True,
                    "request_id": "req-bad-1",
                    "transaction_id": "tx-bad-1",
                    "changed": {"launcher": True, "core": True},
                },
            }
        ]
    )

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    assert spawner.process.terminated or spawner.process.killed


def test_prepare_aborts_and_raises_when_download_fails(tmp_path: Path) -> None:
    service_cls, _, error_cls = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader(fail=True)
    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": "req-fail-dl",
                    "transaction_id": "tx-fail-dl",
                    "changed": {"launcher": True, "core": True},
                    "error": None,
                },
            }
        ]
    )

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    assert spawner.process.terminated or spawner.process.killed


def test_prepare_aborts_and_raises_when_apply_rejected(tmp_path: Path) -> None:
    service_cls, _, error_cls = _get_apply_api()
    resolved = make_resolved_release(50)
    gateway = FakeReleaseGateway(resolved)
    downloader = FakeAssetDownloader()
    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": "req-fail-apply",
                    "transaction_id": "tx-fail-apply",
                    "changed": {"launcher": True, "core": False},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": False,
                    "transaction_id": "tx-fail-apply",
                    "error": "TRANSACTION_STATE_INVALID",
                },
            },
        ]
    )

    service = service_cls(
        root_dir=tmp_path,
        release_gateway=gateway,
        asset_downloader=downloader,
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    assert spawner.process.terminated or spawner.process.killed


def test_prepare_default_channel_uses_process_pipe_file_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import neko_launcher.infrastructure.software_update_apply as apply_module

    service_cls, prepared_cls, _ = _get_apply_api()

    class FakePipe:
        def __init__(self, fd: int) -> None:
            self.fd = fd
            self.closed = False

        def fileno(self) -> int:
            return self.fd

        def close(self) -> None:
            self.closed = True

    process = FakeProcess()
    process.stdout = FakePipe(41)
    process.stdin = FakePipe(42)
    spawner = FakeSpawner()
    spawner.process = process
    captured: list[tuple[int, int]] = []

    class StrictFramedIpcChannel(FakeChannel):
        def __init__(self, read_handle: int, write_handle: int) -> None:
            assert type(read_handle) is int
            assert type(write_handle) is int
            assert read_handle == process.stdout.fileno()
            assert write_handle == process.stdin.fileno()
            captured.append((read_handle, write_handle))
            super().__init__(_metadata_only_responses())

    monkeypatch.setattr(apply_module, "FramedIpcChannel", StrictFramedIpcChannel)
    resolved = make_resolved_release(50)
    service = service_cls(
        root_dir=tmp_path,
        release_gateway=FakeReleaseGateway(resolved),
        asset_downloader=FakeAssetDownloader(),
        spawner=spawner,
    )

    prepared = service.prepare()
    assert isinstance(prepared, prepared_cls)
    assert captured == [(41, 42)]


@pytest.mark.parametrize(
    ("ready_body", "apply_body"),
    [
        (
            {
                "accepted": 1,
                "request_id": "req-strict",
                "transaction_id": "tx-strict",
                "changed": {"launcher": False, "core": False},
                "error": None,
            },
            None,
        ),
        (
            {
                "accepted": True,
                "request_id": "req-strict",
                "transaction_id": "tx-strict",
                "changed": {"launcher": False, "core": False},
                "error": None,
                "extra": "forbidden",
            },
            None,
        ),
        (
            None,
            {
                "accepted": True,
                "transaction_id": "tx-other",
                "error": None,
            },
        ),
    ],
    ids=("ready-non-bool", "ready-extra-key", "apply-wrong-transaction"),
)
def test_prepare_aborts_on_non_closed_response_body(
    tmp_path: Path,
    ready_body: dict[str, Any] | None,
    apply_body: dict[str, Any] | None,
) -> None:
    service_cls, _, error_cls = _get_apply_api()
    resolved = make_resolved_release(50)
    spawner = FakeSpawner()
    channel = FakeChannel(
        _metadata_only_responses(ready_body=ready_body, apply_body=apply_body)
    )
    service = service_cls(
        root_dir=tmp_path,
        release_gateway=FakeReleaseGateway(resolved),
        asset_downloader=FakeAssetDownloader(),
        spawner=spawner,
        channel_factory=lambda: channel,
    )

    with pytest.raises(error_cls):
        service.prepare()

    assert spawner.process.terminated or spawner.process.killed


def test_source_guards_no_grant_or_obsolete_apis_in_apply() -> None:
    import neko_launcher.infrastructure.software_update_apply as apply_module

    source = inspect.getsource(apply_module)
    forbidden = (
        "HttpArtifactGrantGateway",
        "get_distribution_capability",
        "/api/software-update",
        "software_update_api_url",
        "grant_gateway",
        "distribution_capability_provider",
        "DefaultDownloader",
        "_validate_grant",
        "_download_and_verify",
    )
    for term in forbidden:
        assert term not in source, f"Forbidden legacy update term found in apply: {term}"
