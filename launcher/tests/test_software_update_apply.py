from __future__ import annotations

import base64
import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

try:
    from tests.software_update_helpers import (
        TEST_KEY_ID,
        TEST_PUBLIC_KEY,
        signed_envelope,
    )
except ImportError:
    from software_update_helpers import (  # type: ignore[no-redef]
        TEST_KEY_ID,
        TEST_PUBLIC_KEY,
        signed_envelope,
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


class FakeDownloader:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.downloaded: list[tuple[str, Path]] = []

    def download(self, component: str, destination: Path) -> None:
        if self.fail:
            raise RuntimeError(f"Simulated download failure for {component}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"payload-{component}".encode())
        self.downloaded.append((component, destination))


def make_test_v2_envelope() -> dict[str, Any]:
    payload = {
        "schema_version": 2,
        "channel": "beta",
        "release_sequence": 50,
        "release_id": "r-50-test",
        "mandatory": False,
        "minimum_supported_sequence": 1,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": "2.0.0",
                "artifact_id": "launcher-50",
                "artifact_sha256": "1" * 64,
                "installed_identity_sha256": "1" * 64,
                "artifact_size": 1024,
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "version": "3.0.0",
                "artifact_id": "core-50",
                "artifact_sha256": "2" * 64,
                "installed_identity_sha256": "3" * 64,
                "artifact_size": 2048,
                "artifact_format": "zip-core-v1",
            },
        },
    }
    return signed_envelope(payload)


def _build_service(
    service_cls: Any,
    root_dir: Path,
    spawner: FakeSpawner,
    channel: FakeChannel,
    downloader: FakeDownloader,
    envelope: dict[str, Any] | None = None,
) -> Any:
    env = envelope if envelope is not None else make_test_v2_envelope()
    manifest_gateway = SimpleNamespace(fetch=lambda: env)
    key_registry = {TEST_KEY_ID: TEST_PUBLIC_KEY}

    kwargs: dict[str, Any] = {
        "root_dir": root_dir,
        "manifest_gateway": manifest_gateway,
        "key_registry": key_registry,
        "spawner": spawner,
        "channel_factory": lambda: channel,
        "downloader": downloader,
    }

    try:
        return service_cls(**kwargs)
    except TypeError:
        pass

    try:
        return service_cls(
            root_dir=root_dir,
            spawner=spawner,
            channel=channel,
            downloader=downloader,
            manifest_gateway=manifest_gateway,
        )
    except TypeError:
        return service_cls(root_dir)


def test_prepare_success_spawns_helper_downloads_changed_and_returns_prepared(
    tmp_path: Path,
) -> None:
    service_cls, prepared_cls, _ = _get_apply_api()

    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": "req-xyz-101",
                    "transaction_id": "tx-abc-202",
                    "changed": {"launcher": True, "core": True},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-abc-202",
                    "error": None,
                },
            },
        ]
    )
    downloader = FakeDownloader()
    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
    )

    prepared = service.prepare()

    # Spawner invocation assertions: exactly [fixed_root/NekoUpdater.exe, '--session']
    assert len(spawner.calls) == 1
    spawn_call = spawner.calls[0]
    expected_exe = str(tmp_path / "NekoUpdater.exe")
    assert spawn_call["command"] == [expected_exe, "--session"]
    assert not spawn_call.get("kwargs", {}).get("shell", False)
    assert len(spawn_call["command"]) == 2  # No arbitrary root arguments

    # Channel message validations
    assert len(channel.sent) == 2
    assert channel.sent[0]["type"] == "BEGIN"
    assert "envelope_b64" in channel.sent[0]["body"]
    assert channel.sent[1]["type"] == "APPLY"
    assert channel.sent[1]["body"] == {
        "transaction_id": "tx-abc-202",
        "request_id": "req-xyz-101",
    }

    # Downloader destination validations
    assert len(downloader.downloaded) == 2
    expected_incoming = tmp_path / "incoming" / "req-xyz-101"
    assert downloader.downloaded == [
        ("launcher", expected_incoming / "launcher.artifact"),
        ("core", expected_incoming / "core.artifact.zip"),
    ]

    # Prepared update object checks: channel remains open, helper not terminated
    assert isinstance(prepared, prepared_cls)
    assert channel.closed is False
    assert spawner.process.terminated is False
    assert spawner.process.killed is False


def test_prepare_default_downloader_uses_launcher_grant_and_https_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import neko_launcher.infrastructure.software_update_apply as apply_module

    service_cls, prepared_cls, _ = _get_apply_api()
    payload = b"neko-launcher-update"
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    launcher_artifact_id = "launcher-default-download"
    envelope_payload = {
        "schema_version": 2,
        "channel": "beta",
        "release_sequence": 51,
        "release_id": "r-51-default-download",
        "mandatory": False,
        "minimum_supported_sequence": 1,
        "updater_protocol": {"minimum": 1, "maximum": 1},
        "components": {
            "launcher": {
                "version": "2.0.1",
                "artifact_id": launcher_artifact_id,
                "artifact_sha256": payload_sha256,
                "installed_identity_sha256": payload_sha256,
                "artifact_size": len(payload),
                "artifact_format": "raw-pe-v1",
            },
            "core": {
                "version": "3.0.0",
                "artifact_id": "core-51",
                "artifact_sha256": "2" * 64,
                "installed_identity_sha256": "3" * 64,
                "artifact_size": 2048,
                "artifact_format": "zip-core-v1",
            },
        },
    }
    envelope = signed_envelope(envelope_payload)
    request_id = "req-default-download"
    (tmp_path / "incoming" / request_id).mkdir(parents=True)
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": request_id,
                    "transaction_id": "tx-default-download",
                    "changed": {"launcher": True, "core": False},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-default-download",
                    "error": None,
                },
            },
        ]
    )
    grant_calls: list[str] = []

    class FakeGrantGateway:
        def grant(self, artifact_id: str) -> Any:
            grant_calls.append(artifact_id)
            return SimpleNamespace(
                url="https://updates.example.test/launcher.artifact",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

    class FakeHttpsResponse:
        status = 200

        def __init__(self) -> None:
            self._offset = 0

        def __enter__(self) -> FakeHttpsResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(payload):
                return b""
            end = len(payload) if size < 0 else self._offset + size
            chunk = payload[self._offset : end]
            self._offset += len(chunk)
            return chunk

    opened_urls: list[str] = []

    def fake_open(url: Any, *_args: Any, **_kwargs: Any) -> FakeHttpsResponse:
        opened_urls.append(url.full_url if hasattr(url, "full_url") else str(url))
        return FakeHttpsResponse()

    opener_name = next(
        (
            name
            for name in ("_open_no_redirect", "urlopen")
            if hasattr(apply_module, name)
        ),
        "urlopen",
    )
    monkeypatch.setattr(apply_module, opener_name, fake_open, raising=False)
    spawner = FakeSpawner()
    service = service_cls(
        root_dir=tmp_path,
        manifest_gateway=SimpleNamespace(fetch=lambda: envelope),
        key_registry={TEST_KEY_ID: TEST_PUBLIC_KEY},
        spawner=spawner,
        channel_factory=lambda: channel,
        grant_gateway=FakeGrantGateway(),
    )

    prepared = service.prepare()

    assert grant_calls == [launcher_artifact_id]
    assert opened_urls == ["https://updates.example.test/launcher.artifact"]
    assert (tmp_path / "incoming" / request_id / "launcher.artifact").read_bytes() == payload
    assert not (tmp_path / "incoming" / request_id / "core.artifact.zip").exists()
    assert [message["type"] for message in channel.sent] == ["BEGIN", "APPLY"]
    assert isinstance(prepared, prepared_cls)
    assert channel.closed is False
    assert spawner.process.terminated is False
    assert spawner.process.killed is False


def test_prepare_default_downloader_rejects_trailing_response_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import neko_launcher.infrastructure.software_update_apply as apply_module

    service_cls, _, error_cls = _get_apply_api()
    good_payload = b"neko-launcher-signed-payload"
    launcher_artifact_id = "launcher-trailing-response"
    envelope = signed_envelope(
        {
            "schema_version": 2,
            "channel": "beta",
            "release_sequence": 52,
            "release_id": "r-52-trailing-response",
            "mandatory": False,
            "minimum_supported_sequence": 1,
            "updater_protocol": {"minimum": 1, "maximum": 1},
            "components": {
                "launcher": {
                    "version": "2.0.2",
                    "artifact_id": launcher_artifact_id,
                    "artifact_sha256": hashlib.sha256(good_payload).hexdigest(),
                    "installed_identity_sha256": hashlib.sha256(good_payload).hexdigest(),
                    "artifact_size": len(good_payload),
                    "artifact_format": "raw-pe-v1",
                },
                "core": {
                    "version": "3.0.0",
                    "artifact_id": "core-52",
                    "artifact_sha256": "2" * 64,
                    "installed_identity_sha256": "3" * 64,
                    "artifact_size": 2048,
                    "artifact_format": "zip-core-v1",
                },
            },
        }
    )
    request_id = "req-trailing-response"
    (tmp_path / "incoming" / request_id).mkdir(parents=True)
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": request_id,
                    "transaction_id": "tx-trailing-response",
                    "changed": {"launcher": True, "core": False},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-trailing-response",
                    "error": None,
                },
            },
        ]
    )

    class FakeGrantGateway:
        def grant(self, artifact_id: str) -> Any:
            assert artifact_id == launcher_artifact_id
            return SimpleNamespace(
                url="https://updates.example.test/launcher.artifact",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

    class FakeHttpsResponse:
        status = 200

        def __init__(self) -> None:
            self.chunks = [good_payload, b"EXTRA"]

        def __enter__(self) -> FakeHttpsResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            if not self.chunks:
                return b""
            chunk = self.chunks.pop(0)
            if size >= 0 and len(chunk) > size:
                self.chunks.insert(0, chunk[size:])
                return chunk[:size]
            return chunk

    def fake_open(_url: Any, *_args: Any, **_kwargs: Any) -> FakeHttpsResponse:
        return FakeHttpsResponse()

    opener_name = next(
        (
            name
            for name in ("_open_no_redirect", "urlopen")
            if hasattr(apply_module, name)
        ),
        "urlopen",
    )
    monkeypatch.setattr(apply_module, opener_name, fake_open, raising=False)
    spawner = FakeSpawner()
    service = service_cls(
        root_dir=tmp_path,
        manifest_gateway=SimpleNamespace(fetch=lambda: envelope),
        key_registry={TEST_KEY_ID: TEST_PUBLIC_KEY},
        spawner=spawner,
        channel_factory=lambda: channel,
        grant_gateway=FakeGrantGateway(),
    )

    with pytest.raises(error_cls):
        service.prepare()

    assert spawner.process.terminated or spawner.process.killed
    assert not any(message["type"] == "APPLY" for message in channel.sent)


@pytest.mark.parametrize(
    ("changed", "expected_provider_reads", "expected_grant_calls"),
    [
        ({"launcher": True, "core": False}, 0, [("anonymous", "launcher-50", None)]),
        ({"launcher": False, "core": True}, 1, [("core", "core-50", "capability")]),
        ({"launcher": False, "core": False}, 0, []),
    ],
    ids=("launcher-only", "core-only", "metadata-only"),
)
def test_default_download_selects_grant_path_and_reads_capability_only_for_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: dict[str, bool],
    expected_provider_reads: int,
    expected_grant_calls: list[tuple[str, str, str | None]],
) -> None:
    import neko_launcher.infrastructure.software_update_apply as apply_module

    service_cls, prepared_cls, _ = _get_apply_api()
    assert "distribution_capability_provider" in inspect.signature(
        service_cls
    ).parameters, "missing lazy distribution_capability_provider seam"
    capability = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    payloads = {"launcher": b"L", "core": b"C"}
    document = make_test_v2_envelope()["payload"]
    for name, payload in payloads.items():
        document["components"][name]["artifact_sha256"] = hashlib.sha256(payload).hexdigest()
        document["components"][name]["installed_identity_sha256"] = hashlib.sha256(
            payload
        ).hexdigest()
        document["components"][name]["artifact_size"] = len(payload)
    envelope = signed_envelope(document)
    request_id = "req-grant-routing"
    (tmp_path / "incoming" / request_id).mkdir(parents=True)
    channel = FakeChannel(
        [
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": request_id,
                    "transaction_id": "tx-grant-routing",
                    "changed": changed,
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-grant-routing",
                    "error": None,
                },
            },
        ]
    )
    provider_reads: list[str] = []
    grant_calls: list[tuple[str, str, str | None]] = []

    class FakeGrantGateway:
        def grant(self, artifact_id: str) -> Any:
            grant_calls.append(("anonymous", artifact_id, None))
            return self._result(artifact_id)

        def grant_core(self, artifact_id: str, received: str) -> Any:
            assert provider_reads == ["read"]
            assert received == capability
            grant_calls.append(("core", artifact_id, "capability"))
            return self._result(artifact_id)

        @staticmethod
        def _result(artifact_id: str) -> Any:
            return SimpleNamespace(
                url=f"https://updates.example.test/{artifact_id}",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

    opened_requests: list[Any] = []

    class FakeHttpsResponse:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> FakeHttpsResponse:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            result = self.body if size < 0 else self.body[:size]
            self.body = self.body[len(result) :]
            return result

    def fake_open(request: Any, **_kwargs: Any) -> FakeHttpsResponse:
        opened_requests.append(request)
        component = "core" if "core-50" in request.full_url else "launcher"
        return FakeHttpsResponse(payloads[component])

    monkeypatch.setattr(apply_module, "_open_no_redirect", fake_open)
    service = service_cls(
        root_dir=tmp_path,
        manifest_gateway=SimpleNamespace(fetch=lambda: envelope),
        key_registry={TEST_KEY_ID: TEST_PUBLIC_KEY},
        spawner=FakeSpawner(),
        channel_factory=lambda: channel,
        grant_gateway=FakeGrantGateway(),
        distribution_capability_provider=lambda: provider_reads.append("read") or capability,
    )

    prepared = service.prepare()

    assert isinstance(prepared, prepared_cls)
    assert len(provider_reads) == expected_provider_reads
    assert grant_calls == expected_grant_calls
    assert all(
        request.get_header("Authorization") is None
        and request.get_header("Cookie") is None
        for request in opened_requests
    )


def test_missing_core_capability_aborts_before_grant_or_apply(tmp_path: Path) -> None:
    service_cls, _, error_cls = _get_apply_api()
    assert "distribution_capability_provider" in inspect.signature(
        service_cls
    ).parameters, "missing lazy distribution_capability_provider seam"
    spawner = FakeSpawner()
    channel = FakeChannel(
        [{
            "type": "REQUEST_READY",
            "message_id": "msg-0",
            "body": {
                "accepted": True,
                "request_id": "req-missing-capability",
                "transaction_id": "tx-missing-capability",
                "changed": {"launcher": False, "core": True},
                "error": None,
            },
        }]
    )
    provider_reads: list[str] = []

    class NeverGrant:
        def grant_core(self, artifact_id: str, capability: str) -> Any:
            raise AssertionError(f"Core grant must not occur: {artifact_id} {capability}")

    service = service_cls(
        root_dir=tmp_path,
        manifest_gateway=SimpleNamespace(fetch=make_test_v2_envelope),
        key_registry={TEST_KEY_ID: TEST_PUBLIC_KEY},
        spawner=spawner,
        channel_factory=lambda: channel,
        grant_gateway=NeverGrant(),
        distribution_capability_provider=lambda: provider_reads.append("read") or None,
    )

    with pytest.raises(error_cls) as caught:
        service.prepare()

    assert caught.value.code
    assert str(caught.value) == caught.value.code
    assert provider_reads == ["read"]
    assert [message["type"] for message in channel.sent] == ["BEGIN"]
    assert spawner.process.terminated or spawner.process.killed


def test_prepared_update_release_closes_channel_without_terminating_helper(
    tmp_path: Path,
) -> None:
    service_cls, prepared_cls, _ = _get_apply_api()

    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": "req-rel-1",
                    "transaction_id": "tx-rel-1",
                    "changed": {"launcher": True, "core": False},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-rel-1",
                    "error": None,
                },
            },
        ]
    )
    downloader = FakeDownloader()
    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
    )

    prepared = service.prepare()
    assert isinstance(prepared, prepared_cls)
    assert channel.closed is False
    assert len(downloader.downloaded) == 1
    assert downloader.downloaded[0][0] == "launcher"

    # Calling release() must close channel/pipe to produce EOF on broker side, but NOT terminate helper
    prepared.release()

    assert channel.closed is True
    assert spawner.process.terminated is False
    assert spawner.process.killed is False


def test_prepare_metadata_only_skips_downloads_and_sends_apply(
    tmp_path: Path,
) -> None:
    service_cls, prepared_cls, _ = _get_apply_api()

    spawner = FakeSpawner()
    channel = FakeChannel(
        responses=[
            {
                "type": "REQUEST_READY",
                "message_id": "msg-0",
                "body": {
                    "accepted": True,
                    "request_id": "req-meta-1",
                    "transaction_id": "tx-meta-1",
                    "changed": {"launcher": False, "core": False},
                    "error": None,
                },
            },
            {
                "type": "APPLY_RESULT",
                "message_id": "msg-1",
                "body": {
                    "accepted": True,
                    "transaction_id": "tx-meta-1",
                    "error": None,
                },
            },
        ]
    )
    downloader = FakeDownloader()
    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
    )

    prepared = service.prepare()

    # Metadata only: no downloads performed
    assert len(downloader.downloaded) == 0
    # Still sends APPLY
    assert len(channel.sent) == 2
    assert channel.sent[1]["type"] == "APPLY"
    assert channel.sent[1]["body"]["transaction_id"] == "tx-meta-1"
    assert isinstance(prepared, prepared_cls)


def test_prepare_aborts_and_raises_when_begin_rejected(
    tmp_path: Path,
) -> None:
    service_cls, _, error_cls = _get_apply_api()

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
                    "error": "REJECTED_SIGNATURE",
                },
            }
        ]
    )
    downloader = FakeDownloader()
    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    # Abort must terminate helper
    assert spawner.process.terminated or spawner.process.killed
    assert len(downloader.downloaded) == 0


def test_prepare_aborts_and_raises_when_message_id_mismatched_or_malformed(
    tmp_path: Path,
) -> None:
    service_cls, _, error_cls = _get_apply_api()

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
    downloader = FakeDownloader()
    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    assert spawner.process.terminated or spawner.process.killed
    assert len(downloader.downloaded) == 0


def test_prepare_aborts_and_raises_when_download_fails(
    tmp_path: Path,
) -> None:
    service_cls, _, error_cls = _get_apply_api()

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
    downloader = FakeDownloader(fail=True)
    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    # Helper process aborted on download failure
    assert spawner.process.terminated or spawner.process.killed
    # No APPLY message sent
    assert not any(m["type"] == "APPLY" for m in channel.sent)


def test_prepare_aborts_and_raises_when_apply_rejected(
    tmp_path: Path,
) -> None:
    service_cls, _, error_cls = _get_apply_api()

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
    downloader = FakeDownloader()
    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    # Helper process aborted on apply rejection
    assert spawner.process.terminated or spawner.process.killed


def _metadata_only_responses(
    *,
    ready_body: dict[str, Any] | None = None,
    apply_body: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "type": "REQUEST_READY",
            "message_id": "msg-0",
            "body": ready_body
            or {
                "accepted": True,
                "request_id": "req-strict",
                "transaction_id": "tx-strict",
                "changed": {"launcher": False, "core": False},
                "error": None,
            },
        },
        {
            "type": "APPLY_RESULT",
            "message_id": "msg-1",
            "body": apply_body
            or {
                "accepted": True,
                "transaction_id": "tx-strict",
                "error": None,
            },
        },
    ]


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
    service = service_cls(
        root_dir=tmp_path,
        manifest_gateway=SimpleNamespace(fetch=make_test_v2_envelope),
        key_registry={TEST_KEY_ID: TEST_PUBLIC_KEY},
        spawner=spawner,
        downloader=FakeDownloader(),
    )

    prepared = service.prepare()

    assert isinstance(prepared, prepared_cls)
    assert captured == [(41, 42)]


def test_prepare_uses_real_channel_send_message_api(tmp_path: Path) -> None:
    service_cls, prepared_cls, _ = _get_apply_api()
    spawner = FakeSpawner()

    class StrictSendChannel(FakeChannel):
        def send_message(
            self,
            msg_type: str,
            body: dict[str, Any],
            message_id: str | None = None,
        ) -> str:
            return super().send_message(msg_type, body, message_id)

    channel = StrictSendChannel(_metadata_only_responses())
    service = _build_service(
        service_cls, tmp_path, spawner, channel, FakeDownloader()
    )

    prepared = service.prepare()

    assert isinstance(prepared, prepared_cls)


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
    spawner = FakeSpawner()
    channel = FakeChannel(
        _metadata_only_responses(ready_body=ready_body, apply_body=apply_body)
    )
    service = _build_service(
        service_cls, tmp_path, spawner, channel, FakeDownloader()
    )

    with pytest.raises(error_cls):
        service.prepare()

    assert spawner.process.terminated or spawner.process.killed


def test_prepare_aborts_and_raises_when_manifest_verify_fails(
    tmp_path: Path,
) -> None:
    service_cls, _, error_cls = _get_apply_api()

    spawner = FakeSpawner()
    channel = FakeChannel([])
    downloader = FakeDownloader()

    corrupt_envelope = make_test_v2_envelope()
    corrupt_envelope["signature_b64"] = "A" * 86 + "=="

    service = _build_service(
        service_cls,
        tmp_path,
        spawner,
        channel,
        downloader,
        envelope=corrupt_envelope,
    )

    with pytest.raises(error_cls) as exc_info:
        service.prepare()

    assert hasattr(exc_info.value, "code")
    assert (
        len(spawner.calls) == 0
        or spawner.process.terminated
        or spawner.process.killed
    )
    assert len(downloader.downloaded) == 0

