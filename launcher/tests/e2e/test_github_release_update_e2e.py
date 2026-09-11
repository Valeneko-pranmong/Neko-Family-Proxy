from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from neko_launcher.infrastructure.github_asset_downloader import (
    GitHubAssetDownloader,
    GitHubManifestDownloader,
)
from neko_launcher.infrastructure.github_release import (
    GITHUB_RELEASE_API_URL,
    GitHubLatestReleaseGateway,
    GitHubReleaseDiscoveryError,
)
from neko_launcher.infrastructure.github_release_binding import (
    CORE_ASSET_NAME,
    LAUNCHER_ASSET_NAME,
    RELEASE_MANIFEST_ASSET_NAME,
    UPDATER_ASSET_NAME,
    GitHubReleaseResolver,
    GitHubReleaseResolverError,
)
from neko_launcher.infrastructure.software_update_apply import (
    SoftwareUpdateApplyError,
    SoftwareUpdateApplyService,
)
from neko_launcher.updater.activation import activate_verified_generation
from neko_launcher.updater.binary_frame import SlotFrame, pack_slot_frame
from neko_launcher.updater.broker import BrokerCoordinator
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.ipc_channel import FramedIpcChannel
from neko_launcher.updater.main import run_session
from neko_launcher.updater.probation_runner import SelfTestResult
from neko_launcher.updater.recovery_engine import RecoveryEngine
from neko_launcher.updater.state_models import Binding, Generation, deserialize_state, serialize_state
from tests.software_update_helpers import canonical_payload_bytes, signed_envelope
from tests.e2e.test_live_update_balanced_e2e import BalancedLiveUpdateEnv, ClosableStore


class _SimulatedHttpResponse:
    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        headers: dict[str, Any] | None = None,
    ) -> None:
        self.stream = io.BytesIO(body)
        self.status = status
        self.code = status
        self._headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def getcode(self) -> int:
        return self.status

    def info(self) -> Any:
        return self

    @property
    def headers(self) -> Any:
        return self

    def get(self, name: str, default: Any = None) -> Any:
        for k, v in self._headers.items():
            if k.lower() == name.lower():
                return v
        return default

    def get_all(self, name: str, default: Any = None) -> Any:
        matches = [v for k, v in self._headers.items() if k.lower() == name.lower()]
        return matches if matches else default

    def __enter__(self) -> _SimulatedHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def close(self) -> None:
        pass


class FakeTransportOpener:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.captured_requests: list[Any] = []

    def open(self, request: Any, timeout: float = 15.0) -> Any:
        del timeout
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.captured_requests.append(request)
        if url not in self.routes:
            raise GitHubReleaseDiscoveryError("GITHUB_RELEASE_UNAVAILABLE")
        res = self.routes[url]
        if isinstance(res, BaseException):
            raise res
        return res


class ThreadHelperProcess:
    def __init__(
        self,
        thread: threading.Thread,
        launcher_channel: FramedIpcChannel,
        updater_channel: FramedIpcChannel,
    ) -> None:
        self.thread = thread
        self.launcher_channel = launcher_channel
        self.updater_channel = updater_channel
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.launcher_channel.close()
        self.updater_channel.close()

    def kill(self) -> None:
        self.killed = True
        self.launcher_channel.close()
        self.updater_channel.close()


def _build_simulation_fixtures(
    root: Path,
    *,
    launcher_changed: bool = True,
    core_changed: bool = True,
    tag: str = "v1.0.0",
) -> tuple[BalancedLiveUpdateEnv, ClosableStore, bytes, dict[str, Any]]:
    env = BalancedLiveUpdateEnv(
        root,
        launcher_changed=launcher_changed,
        core_changed=core_changed,
    )
    store = ClosableStore(env.state)
    env.store = store

    updater_bytes = b"updater-binary-payload"
    (root / "NekoUpdater.exe").write_bytes(updater_bytes)

    manifest_bytes = canonical_json_dumps(env.envelope_dict)
    launcher_bytes = env.new_launcher
    core_bytes = env.new_core_zip_bytes

    api_release = {
        "id": 100,
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "id": 1,
                "name": RELEASE_MANIFEST_ASSET_NAME,
                "size": len(manifest_bytes),
                "browser_download_url": (
                    f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{RELEASE_MANIFEST_ASSET_NAME}"
                ),
            },
            {
                "id": 2,
                "name": LAUNCHER_ASSET_NAME,
                "size": len(launcher_bytes),
                "browser_download_url": (
                    f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{LAUNCHER_ASSET_NAME}"
                ),
            },
            {
                "id": 3,
                "name": UPDATER_ASSET_NAME,
                "size": len(updater_bytes),
                "browser_download_url": (
                    f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{UPDATER_ASSET_NAME}"
                ),
            },
            {
                "id": 4,
                "name": CORE_ASSET_NAME,
                "size": len(core_bytes),
                "browser_download_url": (
                    f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{CORE_ASSET_NAME}"
                ),
            },
        ],
    }

    cdn_prefix = "https://objects.githubusercontent.com/test-assets/"
    routes: dict[str, Any] = {
        GITHUB_RELEASE_API_URL: _SimulatedHttpResponse(
            json.dumps(api_release).encode("utf-8"),
            status=200,
        ),
        f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{RELEASE_MANIFEST_ASSET_NAME}": _SimulatedHttpResponse(
            status=302,
            headers={"Location": cdn_prefix + RELEASE_MANIFEST_ASSET_NAME},
        ),
        cdn_prefix + RELEASE_MANIFEST_ASSET_NAME: _SimulatedHttpResponse(
            manifest_bytes,
            status=200,
        ),
        f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{LAUNCHER_ASSET_NAME}": _SimulatedHttpResponse(
            status=302,
            headers={"Location": cdn_prefix + LAUNCHER_ASSET_NAME},
        ),
        cdn_prefix + LAUNCHER_ASSET_NAME: _SimulatedHttpResponse(
            launcher_bytes,
            status=200,
        ),
        f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{UPDATER_ASSET_NAME}": _SimulatedHttpResponse(
            status=302,
            headers={"Location": cdn_prefix + UPDATER_ASSET_NAME},
        ),
        cdn_prefix + UPDATER_ASSET_NAME: _SimulatedHttpResponse(
            updater_bytes,
            status=200,
        ),
        f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{CORE_ASSET_NAME}": _SimulatedHttpResponse(
            status=302,
            headers={"Location": cdn_prefix + CORE_ASSET_NAME},
        ),
        cdn_prefix + CORE_ASSET_NAME: _SimulatedHttpResponse(
            core_bytes,
            status=200,
        ),
    }

    return env, store, updater_bytes, routes


def _run_full_update_pipeline(
    root: Path,
    env: BalancedLiveUpdateEnv,
    store: ClosableStore,
    opener: FakeTransportOpener,
    *,
    self_test_pass: bool = True,
) -> tuple[int, SoftwareUpdateApplyService]:
    gw = GitHubLatestReleaseGateway()
    gw._opener = opener
    mdl = GitHubManifestDownloader(_opener=opener)
    resolver = GitHubReleaseResolver(
        release_gateway=gw,
        manifest_downloader=mdl,
        key_registry=env.keys,
        install_root=root,
    )
    adl = GitHubAssetDownloader(_opener=opener)

    created_channels: list[FramedIpcChannel] = []
    helper_exit_codes: list[int] = []
    proc_refs: list[ThreadHelperProcess] = []

    def activate_fn(root_dir: Path, slot_store: Any) -> Any:
        return activate_verified_generation(
            root_dir,
            slot_store,
            self_test=lambda p: (
                SelfTestResult(passed=True)
                if self_test_pass
                else SelfTestResult(
                    passed=False,
                    code="SELFTEST_FAILED",
                    message="broken candidate self-test failed",
                )
            ),
        )

    def spawner(cmd: Any, **kwargs: Any) -> ThreadHelperProcess:
        del cmd, kwargs
        r1, w1 = os.pipe()
        r2, w2 = os.pipe()
        l_chan = FramedIpcChannel(read_handle=r2, write_handle=w1)
        u_chan = FramedIpcChannel(read_handle=r1, write_handle=w2)
        created_channels.append(l_chan)

        def run_h() -> None:
            rc = run_session(
                root,
                env.keys,
                channel=u_chan,
                slot_store=store,
                activate=activate_fn,
            )
            helper_exit_codes.append(rc)

        t = threading.Thread(target=run_h, daemon=True)
        t.start()
        proc = ThreadHelperProcess(t, l_chan, u_chan)
        proc_refs.append(proc)
        return proc

    service = SoftwareUpdateApplyService(
        root_dir=root,
        release_gateway=resolver,
        asset_downloader=adl,
        spawner=spawner,
        channel_factory=lambda: created_channels[-1],
    )

    prepared = service.prepare()
    prepared.release()

    assert proc_refs
    proc_refs[0].thread.join(timeout=10.0)
    assert not proc_refs[0].thread.is_alive()
    return helper_exit_codes[0], service


@pytest.mark.parametrize(
    ("launcher_changed", "core_changed"),
    [
        (True, False),
        (False, True),
        (True, True),
    ],
)
def test_github_release_update_n_to_n_plus_one_success_e2e(
    tmp_path: Path,
    launcher_changed: bool,
    core_changed: bool,
) -> None:
    env, store, updater_bytes, routes = _build_simulation_fixtures(
        tmp_path,
        launcher_changed=launcher_changed,
        core_changed=core_changed,
    )
    opener = FakeTransportOpener(routes)

    rc, service = _run_full_update_pipeline(
        tmp_path,
        env,
        store,
        opener,
        self_test_pass=True,
    )

    assert rc == 0
    state = store.state
    assert state is not None
    assert state.phase in ("CLEANING", "IDLE")
    assert state.committed == env.candidate
    assert state.previous == env.old
    assert state.highwater == env.candidate.binding
    assert state.observed == env.candidate.binding
    assert state.failed is None
    assert state.transaction is None

    seq = env.candidate.binding.release_sequence
    sha = env.candidate.binding.payload_sha256
    published_dir = tmp_path / "releases" / f"g-{seq:020d}-{sha}"
    assert published_dir.is_dir()
    assert (published_dir / "release-envelope.json").is_file()
    assert (published_dir / "NekoLauncher.exe").is_file()
    assert (published_dir / "ProxyCore").is_dir()

    # Verify no Admin, Supabase, Vercel, or Authorization/Cookie headers
    for req in opener.captured_requests:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert "supabase" not in url.lower()
        assert "admin" not in url.lower()
        assert "vercel" not in url.lower()
        assert req.get_header("Authorization") is None
        assert req.get_header("Cookie") is None


def _retarget_as_launcher_only_n_plus_two(
    env: BalancedLiveUpdateEnv,
    routes: dict[str, Any],
) -> Generation:
    launcher_bytes = b"broken-n-plus-two-launcher"
    launcher_sha = hashlib.sha256(launcher_bytes).hexdigest()
    payload = env.build_release_doc(
        3,
        launcher_sha,
        len(launcher_bytes),
        env.new_core_zip_sha,
        len(env.new_core_zip_bytes),
        env.new_core_id,
    )
    payload["minimum_supported_sequence"] = 2
    payload["components"]["launcher"]["version"] = "1.0.1"
    payload["components"]["updater"]["version"] = "1.0.1"
    payload["components"]["core"]["version"] = "1.0.1"
    envelope = signed_envelope(payload)
    manifest_bytes = canonical_payload_bytes(envelope)
    payload_sha = hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()
    candidate = Generation(Binding(3, "rel-3", payload_sha), launcher_sha, env.new_core_id)

    tag = "v1.0.1"
    release_base = (
        f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/"
    )
    cdn_base = "https://objects.githubusercontent.com/test-assets-n-plus-two/"
    api_release = {
        "id": 101,
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "assets": [
            {"id": 11, "name": RELEASE_MANIFEST_ASSET_NAME, "size": len(manifest_bytes), "browser_download_url": release_base + RELEASE_MANIFEST_ASSET_NAME},
            {"id": 12, "name": LAUNCHER_ASSET_NAME, "size": len(launcher_bytes), "browser_download_url": release_base + LAUNCHER_ASSET_NAME},
            {"id": 13, "name": UPDATER_ASSET_NAME, "size": len(b"updater-binary-payload"), "browser_download_url": release_base + UPDATER_ASSET_NAME},
            {"id": 14, "name": CORE_ASSET_NAME, "size": len(env.new_core_zip_bytes), "browser_download_url": release_base + CORE_ASSET_NAME},
        ],
    }
    routes.clear()
    routes.update(
        {
            GITHUB_RELEASE_API_URL: _SimulatedHttpResponse(json.dumps(api_release).encode(), 200),
            release_base + RELEASE_MANIFEST_ASSET_NAME: _SimulatedHttpResponse(status=302, headers={"Location": cdn_base + RELEASE_MANIFEST_ASSET_NAME}),
            cdn_base + RELEASE_MANIFEST_ASSET_NAME: _SimulatedHttpResponse(manifest_bytes),
            release_base + LAUNCHER_ASSET_NAME: _SimulatedHttpResponse(status=302, headers={"Location": cdn_base + LAUNCHER_ASSET_NAME}),
            cdn_base + LAUNCHER_ASSET_NAME: _SimulatedHttpResponse(launcher_bytes),
        }
    )
    env.envelope_dict = envelope
    env.envelope = manifest_bytes
    env.envelope_b64 = base64.standard_b64encode(manifest_bytes).decode("ascii")
    env.payload_doc = payload
    env.payload_bytes = canonical_payload_bytes(payload)
    env.new_launcher = launcher_bytes
    env.new_launcher_sha = launcher_sha
    env.l_sha = launcher_sha
    env.l_size = len(launcher_bytes)
    env.candidate = candidate
    return candidate


def _request_urls(opener: FakeTransportOpener) -> list[str]:
    return [
        request.full_url if hasattr(request, "full_url") else str(request)
        for request in opener.captured_requests
    ]


def _assert_public_unauthenticated_requests(opener: FakeTransportOpener) -> None:
    for request in opener.captured_requests:
        url = request.full_url if hasattr(request, "full_url") else str(request)
        assert all(term not in url.lower() for term in ("admin", "supabase", "vercel", "grant", "capability"))
        assert request.get_header("Authorization") is None
        assert request.get_header("Cookie") is None


def test_github_release_update_chained_n_plus_two_rollback_e2e(tmp_path: Path) -> None:
    env, store, updater_bytes, routes = _build_simulation_fixtures(
        tmp_path, launcher_changed=True, core_changed=True
    )
    first_opener = FakeTransportOpener(routes)
    rc1, _ = _run_full_update_pipeline(tmp_path, env, store, first_opener)
    assert rc1 == 0
    n_plus_one = env.candidate
    assert store.state is not None
    assert store.state.committed == n_plus_one

    # Durable serialization/recovery/reload is the process restart boundary.
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_bytes = serialize_state(store.state)
    (state_dir / "slot-a.bin").write_bytes(
        pack_slot_frame(
            SlotFrame(revision=store.state.revision, format_version=1, body_bytes=state_bytes)
        )
    )
    restarted = RecoveryEngine(tmp_path, env.keys).run_recovery()
    assert restarted.converged is True
    assert restarted.selected_generation == n_plus_one
    assert restarted.final_state is not None
    store = ClosableStore(deserialize_state(serialize_state(restarted.final_state)))
    env.store = store
    n_plus_two = _retarget_as_launcher_only_n_plus_two(env, routes)
    second_opener = FakeTransportOpener(routes)
    rc2, _ = _run_full_update_pipeline(
        tmp_path, env, store, second_opener, self_test_pass=False
    )

    assert rc2 != 0
    state = store.state
    assert state is not None
    assert state.committed == n_plus_one
    assert state.previous == env.old
    assert state.highwater == n_plus_one.binding
    assert state.observed == n_plus_two.binding
    assert state.failed == n_plus_two.binding
    assert state.transaction is None
    assert state.last_error == "SELFTEST_FAILED"

    selected_dir = tmp_path / "releases" / (
        f"g-{n_plus_one.binding.release_sequence:020d}-{n_plus_one.binding.payload_sha256}"
    )
    assert selected_dir.is_dir()
    assert (selected_dir / "NekoLauncher.exe").is_file()
    assert (selected_dir / "ProxyCore").is_dir()

    first_names = [url.rsplit("/", 1)[-1] for url in _request_urls(first_opener)]
    second_names = [url.rsplit("/", 1)[-1] for url in _request_urls(second_opener)]
    assert first_names == [
        "latest", RELEASE_MANIFEST_ASSET_NAME, RELEASE_MANIFEST_ASSET_NAME,
        LAUNCHER_ASSET_NAME, LAUNCHER_ASSET_NAME, CORE_ASSET_NAME, CORE_ASSET_NAME,
    ]
    assert second_names == [
        "latest", RELEASE_MANIFEST_ASSET_NAME, RELEASE_MANIFEST_ASSET_NAME,
        LAUNCHER_ASSET_NAME, LAUNCHER_ASSET_NAME,
    ]
    assert UPDATER_ASSET_NAME not in first_names + second_names
    _assert_public_unauthenticated_requests(first_opener)
    _assert_public_unauthenticated_requests(second_opener)

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    for slot in (state_dir / "slot-a.bin", state_dir / "slot-b.bin"):
        slot.unlink(missing_ok=True)
    state_bytes = serialize_state(state)
    (state_dir / "slot-a.bin").write_bytes(
        pack_slot_frame(SlotFrame(revision=state.revision, format_version=1, body_bytes=state_bytes))
    )
    recovery = RecoveryEngine(tmp_path, env.keys)
    recovered1 = recovery.run_recovery()
    assert recovered1.converged is True
    assert recovered1.selected_generation == n_plus_one
    recovered2 = recovery.run_recovery()
    assert recovered2.converged is True
    assert recovered2.mutations_performed == 0
    assert recovered2.selected_generation == n_plus_one
    assert recovered2.final_state == recovered1.final_state


def test_github_release_update_failure_matrix_e2e(tmp_path: Path) -> None:
    cases = [
        "github_unavailable",
        "malformed_release",
        "wrong_tag",
        "missing_asset",
        "duplicate_asset",
        "redirect_denial",
        "product_underrun",
        "product_overrun",
        "hash_mismatch",
        "helper_incompatibility",
        "busy_session",
    ]

    for scenario in cases:
        case_root = tmp_path / scenario
        case_root.mkdir()
        env, store, updater_bytes, routes = _build_simulation_fixtures(case_root)

        tag = "v1.0.0"
        manifest_bytes = canonical_json_dumps(env.envelope_dict)
        launcher_bytes = env.new_launcher
        core_bytes = env.new_core_zip_bytes

        if scenario == "github_unavailable":
            routes[GITHUB_RELEASE_API_URL] = GitHubReleaseDiscoveryError("GITHUB_RELEASE_UNAVAILABLE")

        elif scenario == "malformed_release":
            routes[GITHUB_RELEASE_API_URL] = _SimulatedHttpResponse(b"invalid-json{", status=200)

        elif scenario == "wrong_tag":
            bad_release = {
                "id": 100,
                "tag_name": "v9.9.9",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"id": 1, "name": RELEASE_MANIFEST_ASSET_NAME, "size": len(manifest_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v9.9.9/{RELEASE_MANIFEST_ASSET_NAME}"},
                    {"id": 2, "name": LAUNCHER_ASSET_NAME, "size": len(launcher_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v9.9.9/{LAUNCHER_ASSET_NAME}"},
                    {"id": 3, "name": UPDATER_ASSET_NAME, "size": len(updater_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v9.9.9/{UPDATER_ASSET_NAME}"},
                    {"id": 4, "name": CORE_ASSET_NAME, "size": len(core_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/v9.9.9/{CORE_ASSET_NAME}"},
                ],
            }
            routes[GITHUB_RELEASE_API_URL] = _SimulatedHttpResponse(json.dumps(bad_release).encode("utf-8"), status=200)

        elif scenario == "missing_asset":
            missing_release = {
                "id": 100,
                "tag_name": tag,
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"id": 1, "name": RELEASE_MANIFEST_ASSET_NAME, "size": len(manifest_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{RELEASE_MANIFEST_ASSET_NAME}"},
                    {"id": 2, "name": LAUNCHER_ASSET_NAME, "size": len(launcher_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{LAUNCHER_ASSET_NAME}"},
                    # CORE_ASSET_NAME is omitted
                    {"id": 3, "name": UPDATER_ASSET_NAME, "size": len(updater_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{UPDATER_ASSET_NAME}"},
                ],
            }
            routes[GITHUB_RELEASE_API_URL] = _SimulatedHttpResponse(json.dumps(missing_release).encode("utf-8"), status=200)

        elif scenario == "duplicate_asset":
            dup_release = {
                "id": 100,
                "tag_name": tag,
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"id": 1, "name": RELEASE_MANIFEST_ASSET_NAME, "size": len(manifest_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{RELEASE_MANIFEST_ASSET_NAME}"},
                    {"id": 2, "name": LAUNCHER_ASSET_NAME, "size": len(launcher_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{LAUNCHER_ASSET_NAME}"},
                    {"id": 3, "name": LAUNCHER_ASSET_NAME, "size": len(launcher_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{LAUNCHER_ASSET_NAME}"},
                    {"id": 4, "name": UPDATER_ASSET_NAME, "size": len(updater_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{UPDATER_ASSET_NAME}"},
                    {"id": 5, "name": CORE_ASSET_NAME, "size": len(core_bytes), "browser_download_url": f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{CORE_ASSET_NAME}"},
                ],
            }
            routes[GITHUB_RELEASE_API_URL] = _SimulatedHttpResponse(json.dumps(dup_release).encode("utf-8"), status=200)

        elif scenario == "redirect_denial":
            # Redirect to unauthorized domain
            routes[f"https://github.com/Valeneko-pranmong/Neko-Family-Proxy/releases/download/{tag}/{LAUNCHER_ASSET_NAME}"] = _SimulatedHttpResponse(
                status=302,
                headers={"Location": "https://malicious.example.invalid/launcher.exe"},
            )

        elif scenario == "product_underrun":
            cdn_prefix = "https://objects.githubusercontent.com/test-assets/"
            routes[cdn_prefix + LAUNCHER_ASSET_NAME] = _SimulatedHttpResponse(
                launcher_bytes[:-1], status=200
            )

        elif scenario == "product_overrun":
            cdn_prefix = "https://objects.githubusercontent.com/test-assets/"
            routes[cdn_prefix + LAUNCHER_ASSET_NAME] = _SimulatedHttpResponse(
                launcher_bytes + b"!", status=200
            )

        elif scenario == "hash_mismatch":
            cdn_prefix = "https://objects.githubusercontent.com/test-assets/"
            corrupted = bytes([launcher_bytes[0] ^ 1]) + launcher_bytes[1:]
            assert len(corrupted) == len(launcher_bytes)
            assert hashlib.sha256(corrupted).digest() != hashlib.sha256(launcher_bytes).digest()
            routes[cdn_prefix + LAUNCHER_ASSET_NAME] = _SimulatedHttpResponse(
                corrupted, status=200
            )

        elif scenario == "helper_incompatibility":
            # Installed helper does not match signed updater hash
            (case_root / "NekoUpdater.exe").write_bytes(b"tampered-helper-bytes")

        elif scenario == "busy_session":
            # Put state into PREPARING
            import dataclasses

            busy_state = dataclasses.replace(store.state, phase="PREPARING")
            store.state = busy_state

        opener = FakeTransportOpener(routes)
        gw = GitHubLatestReleaseGateway()
        gw._opener = opener
        mdl = GitHubManifestDownloader(_opener=opener)
        resolver = GitHubReleaseResolver(
            release_gateway=gw,
            manifest_downloader=mdl,
            key_registry=env.keys,
            install_root=case_root,
        )
        adl = GitHubAssetDownloader(_opener=opener)

        created_channels: list[FramedIpcChannel] = []

        def spawner(cmd: Any, **kwargs: Any) -> ThreadHelperProcess:
            del cmd, kwargs
            r1, w1 = os.pipe()
            r2, w2 = os.pipe()
            l_chan = FramedIpcChannel(read_handle=r2, write_handle=w1)
            u_chan = FramedIpcChannel(read_handle=r1, write_handle=w2)
            created_channels.append(l_chan)

            def run_h() -> None:
                run_session(
                    case_root,
                    env.keys,
                    channel=u_chan,
                    slot_store=store,
                    activate=lambda r, s: activate_verified_generation(
                        r, s, self_test=lambda p: SelfTestResult(passed=True)
                    ),
                )

            t = threading.Thread(target=run_h, daemon=True)
            t.start()
            return ThreadHelperProcess(t, l_chan, u_chan)

        service = SoftwareUpdateApplyService(
            root_dir=case_root,
            release_gateway=resolver,
            asset_downloader=adl,
            spawner=spawner,
            channel_factory=lambda: created_channels[-1],
        )

        with pytest.raises((SoftwareUpdateApplyError, GitHubReleaseResolverError, GitHubReleaseDiscoveryError)):
            service.prepare()

        # In all failure modes, old generation remains selected and runnable
        assert store.state is not None
        assert store.state.committed == env.old
        old_seq = env.old.binding.release_sequence
        old_sha = env.old.binding.payload_sha256
        old_dir = case_root / "releases" / f"g-{old_seq:020d}-{old_sha}"
        assert old_dir.is_dir()
        assert (old_dir / "NekoLauncher.exe").is_file()
        assert (old_dir / "ProxyCore").is_dir()


def test_github_release_update_idempotent_recovery_e2e(tmp_path: Path) -> None:
    for stage in ("ADMITTED", "VERIFIED"):
        case_root = tmp_path / f"recovery-{stage.lower()}"
        case_root.mkdir()
        env = BalancedLiveUpdateEnv(case_root, launcher_changed=True, core_changed=True)
        store = ClosableStore(env.state)

        coordinator = BrokerCoordinator(case_root, store, env.keys)
        begin_res = coordinator.begin(env.envelope_b64)
        assert begin_res.accepted is True

        if stage == "VERIFIED":
            env.populate_incoming(begin_res.request_id)
            apply_res = coordinator.apply(begin_res.transaction_id, begin_res.request_id)
            assert apply_res.accepted is True
            assert store.state is not None
            assert store.state.transaction is not None
            assert store.state.transaction.stage == "VERIFIED"
        else:
            assert store.state is not None
            assert store.state.transaction is not None
            assert store.state.transaction.stage == "ADMITTED"

        assert store.state is not None
        state_bytes = serialize_state(store.state)
        frame = SlotFrame(
            revision=store.state.revision,
            format_version=1,
            body_bytes=state_bytes,
        )
        state_dir = case_root / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "slot-a.bin").write_bytes(pack_slot_frame(frame))

        engine = RecoveryEngine(case_root, env.keys)
        res1 = engine.run_recovery()
        assert res1.converged is True
        assert res1.selected_generation == env.old
        assert res1.final_state is not None
        assert res1.final_state.phase == "IDLE"
        assert res1.final_state.committed == env.old
        assert res1.final_state.highwater == env.old.binding
        assert res1.final_state.failed == env.candidate.binding
        assert res1.final_state.transaction is None

        # Second recovery pass must perform 0 mutations and select identical generation
        res2 = engine.run_recovery()
        assert res2.converged is True
        assert res2.selected_generation == env.old
        assert res2.mutations_performed == 0
        assert res2.final_state is not None
        assert res2.final_state.committed == env.old
        assert res2.final_state.highwater == env.old.binding
