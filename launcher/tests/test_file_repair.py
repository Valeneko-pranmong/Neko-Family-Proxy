from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from neko_launcher.application.file_integrity import (
    FileIntegrityItem,
    FileIntegrityReport,
    IntegrityStatus,
)
from neko_launcher.application.file_repair import (
    ReinstallRequiredError,
    RepairError,
    RepairNotAllowed,
    RepairRequest,
    create_repair_request_from_report,
    repair_installed_release,
)
from neko_launcher.application.software_update_models import (
    InstalledReleaseSelector,
)
from neko_launcher.application.software_update_pending import (
    VerifiedPendingUpdate,
)
from neko_launcher.infrastructure.github_asset_downloader import DownloadedArtifact
from neko_launcher.infrastructure.github_release import GitHubRelease, GitHubReleaseAsset
from neko_launcher.infrastructure.github_release_binding import (
    CORE_ASSET_NAME,
    LAUNCHER_ASSET_NAME,
    RELEASE_MANIFEST_ASSET_NAME,
    UPDATER_ASSET_NAME,
    ResolvedGitHubRelease,
)
from neko_launcher.infrastructure.software_update_v2 import (
    V2ReleaseManifestVerifierAdapter,
)
from neko_launcher.updater.canonical_json import (
    canonical_json_dumps,
)
from neko_launcher.updater.manifest_v2 import (
    verify_release_envelope_v2,
)
from tests.software_update_helpers import (
    TEST_KEY_ID,
    get_test_key_registry,
    signed_envelope,
    valid_v2_release_document,
)


def _make_selector(
    sequence: int = 9,
    release_id: str = "stable-0009",
    version: str = "5.1.3",
    tag_name: str = "v5.1.3",
    target_commit: str = "a" * 40,
) -> InstalledReleaseSelector:
    return InstalledReleaseSelector(
        sequence=sequence,
        release_id=release_id,
        version=version,
        tag_name=tag_name,
        target_commit=target_commit,
    )


def _make_dummy_report(
    selector: InstalledReleaseSelector,
    *,
    launcher_status: IntegrityStatus = IntegrityStatus.OK,
    updater_status: IntegrityStatus = IntegrityStatus.OK,
    core_status: IntegrityStatus = IntegrityStatus.OK,
) -> FileIntegrityReport:
    items = (
        FileIntegrityItem(
            component="launcher",
            path=Path("NekoLauncher.exe"),
            expected_size=100,
            expected_sha256="1" * 64,
            actual_size=100 if launcher_status == IntegrityStatus.OK else None,
            actual_sha256="1" * 64 if launcher_status == IntegrityStatus.OK else None,
            status=launcher_status,
        ),
        FileIntegrityItem(
            component="updater",
            path=Path("NekoUpdater.exe"),
            expected_size=200,
            expected_sha256="2" * 64,
            actual_size=200 if updater_status == IntegrityStatus.OK else None,
            actual_sha256="2" * 64 if updater_status == IntegrityStatus.OK else None,
            status=updater_status,
        ),
        FileIntegrityItem(
            component="core",
            path=Path("ProxyCore/core-manifest.json"),
            expected_size=300,
            expected_sha256="3" * 64,
            actual_size=300 if core_status == IntegrityStatus.OK else None,
            actual_sha256="3" * 64 if core_status == IntegrityStatus.OK else None,
            status=core_status,
        ),
    )
    if updater_status != IntegrityStatus.OK:
        reinstall_required = True
        repairable: tuple[Any, ...] = ()
    else:
        reinstall_required = False
        rep = []
        if launcher_status != IntegrityStatus.OK:
            rep.append("launcher")
        if core_status != IntegrityStatus.OK:
            rep.append("core")
        repairable = tuple(rep)

    return FileIntegrityReport(
        selector=selector,
        items=items,
        repairable_components=repairable,
        reinstall_required=reinstall_required,
    )


def _make_resolved_release(
    selector: InstalledReleaseSelector,
    *,
    launcher_size: int = 1024,
    launcher_sha: str = "1" * 64,
    core_size: int = 2048,
    core_sha: str = "2" * 64,
    updater_size: int = 4096,
    updater_sha: str = "3" * 64,
    repository: str = "Valeneko-pranmong/Neko-Family-Proxy",
) -> tuple[ResolvedGitHubRelease, bytes]:
    doc = valid_v2_release_document(
        sequence=selector.sequence,
        release_id=selector.release_id,
        launcher_version=selector.version,
        core_version=selector.version,
        updater_version=selector.version,
    )
    doc["components"]["launcher"]["artifact_size"] = launcher_size
    doc["components"]["launcher"]["artifact_sha256"] = launcher_sha
    doc["components"]["launcher"]["installed_identity_sha256"] = launcher_sha
    doc["components"]["core"]["artifact_size"] = core_size
    doc["components"]["core"]["artifact_sha256"] = core_sha
    doc["components"]["core"]["installed_identity_sha256"] = core_sha
    doc["components"]["updater"]["artifact_size"] = updater_size
    doc["components"]["updater"]["artifact_sha256"] = updater_sha
    doc["components"]["updater"]["installed_identity_sha256"] = updater_sha

    envelope_doc = signed_envelope(doc, key_id=TEST_KEY_ID)
    envelope_bytes = canonical_json_dumps(envelope_doc)
    adapter = V2ReleaseManifestVerifierAdapter(get_test_key_registry(), updater_protocol=1)
    authenticated = adapter.verify(envelope_doc)

    gh_release = GitHubRelease(
        id=101,
        tag_name=selector.tag_name,
        draft=False,
        prerelease=False,
        assets=(
            GitHubReleaseAsset(
                id=1,
                name=RELEASE_MANIFEST_ASSET_NAME,
                size=len(envelope_bytes),
                browser_download_url=f"https://example.com/{RELEASE_MANIFEST_ASSET_NAME}",
            ),
            GitHubReleaseAsset(
                id=2,
                name=LAUNCHER_ASSET_NAME,
                size=launcher_size,
                browser_download_url=f"https://example.com/{LAUNCHER_ASSET_NAME}",
            ),
            GitHubReleaseAsset(
                id=3,
                name=UPDATER_ASSET_NAME,
                size=updater_size,
                browser_download_url=f"https://example.com/{UPDATER_ASSET_NAME}",
            ),
            GitHubReleaseAsset(
                id=4,
                name=CORE_ASSET_NAME,
                size=core_size,
                browser_download_url=f"https://example.com/{CORE_ASSET_NAME}",
            ),
        ),
    )
    object.__setattr__(gh_release, "target_commitish", selector.target_commit)
    object.__setattr__(
        gh_release,
        "html_url",
        f"https://github.com/{repository}/releases/tag/{selector.tag_name}",
    )

    v2_obj, _ = verify_release_envelope_v2(envelope_doc, get_test_key_registry())

    resolved = ResolvedGitHubRelease(
        authenticated_release=authenticated,
        authenticated_release_v2=v2_obj,
        envelope_bytes=envelope_bytes,
        envelope_document=envelope_doc,
        github_release=gh_release,
        manifest_asset=gh_release.assets[0],
        launcher_asset=gh_release.assets[1],
        updater_asset=gh_release.assets[2],
        core_asset=gh_release.assets[3],
    )
    return resolved, envelope_bytes


class FakeDownloader:
    def __init__(self, payloads: dict[str, bytes] | None = None) -> None:
        self.payloads = dict(payloads or {})
        self.download_calls: list[dict[str, Any]] = []

    def download(
        self,
        *,
        initial_url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> DownloadedArtifact:
        self.download_calls.append(
            {
                "initial_url": initial_url,
                "destination": Path(destination),
                "expected_size": expected_size,
                "expected_sha256": expected_sha256,
            }
        )
        data = self.payloads.get(initial_url, b"A" * expected_size)
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        return DownloadedArtifact(size=len(data), sha256=digest)


class FakeUpdaterVerifier:
    def __init__(self, *, trusted: bool = True, reinstall_required: bool = False) -> None:
        self.trusted = trusted
        self.reinstall_required = reinstall_required
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})
        res = MagicMock()
        res.trusted = self.trusted
        res.reinstall_required = self.reinstall_required
        return res


class FakeStageService:
    def __init__(self) -> None:
        self.staged_calls: list[dict[str, Any]] = []

    def stage_repair(
        self,
        resolved: Any,
        components: tuple[str, ...],
    ) -> Any:
        self.staged_calls.append({"resolved": resolved, "components": components})
        pending = MagicMock()
        pending.release_sequence = resolved.authenticated_release.release_sequence
        pending.release_id = resolved.authenticated_release.release_id
        pending.changed_components = components
        pending.envelope_bytes = getattr(resolved, "envelope_bytes", b"")
        return pending


class FakeUpdaterSession:
    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.apply_calls: list[dict[str, Any]] = []

    def prepare_pending(self, pending: Any, **kwargs: Any) -> Any:
        self.apply_calls.append({"pending": pending, "kwargs": kwargs})
        prep = MagicMock()
        prep.release = MagicMock()
        prep.success = self.success
        return prep


# -----------------------------------------------------------------------------
# Unit Tests
# -----------------------------------------------------------------------------


def test_repair_request_cannot_include_updater() -> None:
    selector = _make_selector()
    with pytest.raises(RepairNotAllowed) as exc_info:
        RepairRequest(
            selector=selector,
            components=("updater",),  # type: ignore[arg-type]
        )
    assert "updater" in str(exc_info.value).lower()


def test_repair_request_cannot_have_empty_components() -> None:
    selector = _make_selector()
    with pytest.raises(RepairNotAllowed):
        RepairRequest(
            selector=selector,
            components=(),
        )


def test_repair_request_cannot_have_invalid_components() -> None:
    selector = _make_selector()
    with pytest.raises(RepairNotAllowed):
        RepairRequest(
            selector=selector,
            components=("other",),  # type: ignore[arg-type]
        )


def test_repair_request_requires_explicit_user_action() -> None:
    selector = _make_selector()
    with pytest.raises(RepairNotAllowed) as exc_info:
        RepairRequest(
            selector=selector,
            components=("launcher",),
            explicit_action=False,
        )
    assert "explicit user action" in str(exc_info.value).lower()


def test_repair_request_from_report_rejects_reinstall_required() -> None:
    selector = _make_selector()
    report = _make_dummy_report(
        selector,
        launcher_status=IntegrityStatus.MISSING,
        updater_status=IntegrityStatus.HASH_MISMATCH,
    )
    with pytest.raises(RepairNotAllowed) as exc_info:
        create_repair_request_from_report(report)
    assert "reinstall" in str(exc_info.value).lower()


def test_repair_request_from_report_rejects_when_no_repairable_components() -> None:
    selector = _make_selector()
    report = _make_dummy_report(selector)  # all OK
    with pytest.raises(RepairNotAllowed) as exc_info:
        create_repair_request_from_report(report)
    assert "no repairable components" in str(exc_info.value).lower()


def test_repair_request_from_report_creates_valid_request() -> None:
    selector = _make_selector()
    report = _make_dummy_report(
        selector,
        launcher_status=IntegrityStatus.HASH_MISMATCH,
    )
    req = create_repair_request_from_report(report)
    assert req.selector == selector
    assert req.components == ("launcher",)
    assert req.explicit_action is True
    assert req.integrity_report == report


def test_repair_preserves_exact_installed_version_launcher_only(tmp_path: Path) -> None:
    selector = _make_selector(
        sequence=9, release_id="stable-0009", version="5.1.3", tag_name="v5.1.3"
    )
    resolved, _ = _make_resolved_release(selector)

    def resolver(sel: InstalledReleaseSelector) -> ResolvedGitHubRelease:
        assert sel == selector
        return resolved

    verifier = FakeUpdaterVerifier(trusted=True)
    stager = FakeStageService()
    session = FakeUpdaterSession(success=True)

    def fake_file_check(root: Path, rel: Any) -> FileIntegrityReport:
        return _make_dummy_report(
            selector, launcher_status=IntegrityStatus.OK, core_status=IntegrityStatus.OK
        )

    request = RepairRequest(
        selector=selector,
        components=("launcher",),
    )

    result = repair_installed_release(
        request=request,
        exact_release_resolver=resolver,
        updater_verifier=verifier,
        stage_service=stager,
        updater_session=session,
        install_root=tmp_path,
        file_checker=fake_file_check,
    )

    assert result.success is True
    assert result.before_version == "5.1.3"
    assert result.after_version == "5.1.3"
    assert result.resolved_tag == "v5.1.3"
    assert result.repaired_components == ("launcher",)
    assert len(stager.staged_calls) == 1
    assert stager.staged_calls[0]["components"] == ("launcher",)
    assert len(session.apply_calls) == 1


def test_repair_preserves_exact_installed_version_core_only(tmp_path: Path) -> None:
    selector = _make_selector(
        sequence=9, release_id="stable-0009", version="5.1.3", tag_name="v5.1.3"
    )
    resolved, _ = _make_resolved_release(selector)

    stager = FakeStageService()
    session = FakeUpdaterSession(success=True)

    request = RepairRequest(
        selector=selector,
        components=("core",),
    )

    result = repair_installed_release(
        request=request,
        exact_release_resolver=lambda _: resolved,
        updater_verifier=FakeUpdaterVerifier(trusted=True),
        stage_service=stager,
        updater_session=session,
        install_root=tmp_path,
        file_checker=lambda _r, _rel: _make_dummy_report(selector),
    )

    assert result.success is True
    assert result.before_version == "5.1.3"
    assert result.after_version == "5.1.3"
    assert result.resolved_tag == "v5.1.3"
    assert result.repaired_components == ("core",)
    assert stager.staged_calls[0]["components"] == ("core",)


def test_repair_both_launcher_and_core(tmp_path: Path) -> None:
    selector = _make_selector(
        sequence=9, release_id="stable-0009", version="5.1.3", tag_name="v5.1.3"
    )
    resolved, _ = _make_resolved_release(selector)

    stager = FakeStageService()
    session = FakeUpdaterSession(success=True)

    request = RepairRequest(
        selector=selector,
        components=("launcher", "core"),
    )

    result = repair_installed_release(
        request=request,
        exact_release_resolver=lambda _: resolved,
        updater_verifier=FakeUpdaterVerifier(trusted=True),
        stage_service=stager,
        updater_session=session,
        install_root=tmp_path,
        file_checker=lambda _r, _rel: _make_dummy_report(selector),
    )

    assert result.success is True
    assert result.repaired_components == ("launcher", "core")
    assert stager.staged_calls[0]["components"] == ("launcher", "core")


def test_repair_rejects_latest_substitution(tmp_path: Path) -> None:
    selector = _make_selector(
        sequence=9, release_id="stable-0009", version="5.1.3", tag_name="v5.1.3"
    )
    # Resolver returns a release with sequence 10 (latest substitution!)
    newer_selector = _make_selector(
        sequence=10, release_id="stable-0010", version="5.1.4", tag_name="v5.1.4"
    )
    resolved_latest, _ = _make_resolved_release(newer_selector)

    request = RepairRequest(
        selector=selector,
        components=("launcher",),
    )

    with pytest.raises(RepairError) as exc_info:
        repair_installed_release(
            request=request,
            exact_release_resolver=lambda _: resolved_latest,
            updater_verifier=FakeUpdaterVerifier(trusted=True),
            stage_service=FakeStageService(),
            updater_session=FakeUpdaterSession(success=True),
            install_root=tmp_path,
            file_checker=lambda _r, _rel: _make_dummy_report(selector),
        )
    assert "latest" in str(exc_info.value).lower() or "mismatch" in str(exc_info.value).lower()


def test_repair_rejects_wrong_tag(tmp_path: Path) -> None:
    selector = _make_selector(
        sequence=9, release_id="stable-0009", version="5.1.3", tag_name="v5.1.3"
    )
    # Mismatched tag
    mismatched_selector = _make_selector(
        sequence=9, release_id="stable-0009", version="5.1.3", tag_name="v5.1.4"
    )
    resolved_wrong_tag, _ = _make_resolved_release(mismatched_selector)

    request = RepairRequest(
        selector=selector,
        components=("launcher",),
    )

    with pytest.raises(RepairError) as exc_info:
        repair_installed_release(
            request=request,
            exact_release_resolver=lambda _: resolved_wrong_tag,
            updater_verifier=FakeUpdaterVerifier(trusted=True),
            stage_service=FakeStageService(),
            updater_session=FakeUpdaterSession(success=True),
            install_root=tmp_path,
            file_checker=lambda _r, _rel: _make_dummy_report(selector),
        )
    assert "tag" in str(exc_info.value).lower() or "mismatch" in str(exc_info.value).lower()


def test_repair_rejects_wrong_repo(tmp_path: Path) -> None:
    selector = _make_selector()
    resolved_wrong_repo, _ = _make_resolved_release(
        selector, repository="attacker/Neko-Family-Proxy"
    )

    request = RepairRequest(
        selector=selector,
        components=("launcher",),
    )

    with pytest.raises(RepairError) as exc_info:
        repair_installed_release(
            request=request,
            exact_release_resolver=lambda _: resolved_wrong_repo,
            updater_verifier=FakeUpdaterVerifier(trusted=True),
            stage_service=FakeStageService(),
            updater_session=FakeUpdaterSession(success=True),
            install_root=tmp_path,
            file_checker=lambda _r, _rel: _make_dummy_report(selector),
        )
    assert "repository" in str(exc_info.value).lower() or "repo" in str(exc_info.value).lower()


def test_repair_revalidates_updater_and_aborts_with_zero_mutation_when_updater_untrusted(
    tmp_path: Path,
) -> None:
    selector = _make_selector()
    resolved, _ = _make_resolved_release(selector)

    verifier = FakeUpdaterVerifier(trusted=False, reinstall_required=True)
    stager = FakeStageService()
    session = FakeUpdaterSession()

    request = RepairRequest(
        selector=selector,
        components=("launcher",),
    )

    with pytest.raises((ReinstallRequiredError, RepairNotAllowed)) as exc_info:
        repair_installed_release(
            request=request,
            exact_release_resolver=lambda _: resolved,
            updater_verifier=verifier,
            stage_service=stager,
            updater_session=session,
            install_root=tmp_path,
            file_checker=lambda _r, _rel: _make_dummy_report(selector),
        )

    assert "reinstall" in str(exc_info.value).lower() or "untrusted" in str(exc_info.value).lower()
    # Ensure ZERO mutation: stager and updater_session were never invoked!
    assert len(stager.staged_calls) == 0
    assert len(session.apply_calls) == 0


def test_repair_fails_when_post_repair_file_check_fails(tmp_path: Path) -> None:
    selector = _make_selector()
    resolved, _ = _make_resolved_release(selector)

    request = RepairRequest(
        selector=selector,
        components=("launcher",),
    )

    # Post-repair file check still reports launcher hash mismatch!
    broken_report = _make_dummy_report(selector, launcher_status=IntegrityStatus.HASH_MISMATCH)

    with pytest.raises(RepairError) as exc_info:
        repair_installed_release(
            request=request,
            exact_release_resolver=lambda _: resolved,
            updater_verifier=FakeUpdaterVerifier(trusted=True),
            stage_service=FakeStageService(),
            updater_session=FakeUpdaterSession(success=True),
            install_root=tmp_path,
            file_checker=lambda _r, _rel: broken_report,
        )
    assert (
        "post-repair" in str(exc_info.value).lower() or "integrity" in str(exc_info.value).lower()
    )


# -----------------------------------------------------------------------------
# Integration Tests: Stage Service, Apply Service, and Broker IPC
# -----------------------------------------------------------------------------


def test_stage_repair_downloads_only_requested_components(tmp_path: Path) -> None:
    from neko_launcher.infrastructure.software_update_pending_store import PendingUpdateStore
    from neko_launcher.infrastructure.software_update_stage import (
        SoftwareUpdateStageError,
        SoftwareUpdateStageService,
    )

    selector = _make_selector()
    resolved, _ = _make_resolved_release(
        selector,
        launcher_size=100,
        launcher_sha=hashlib.sha256(b"L" * 100).hexdigest(),
        core_size=200,
        core_sha=hashlib.sha256(b"C" * 200).hexdigest(),
    )

    downloader = FakeDownloader(
        payloads={
            "https://example.com/NekoLauncher.exe": b"L" * 100,
            "https://example.com/NekoProxyCore.zip": b"C" * 200,
        }
    )

    pending_store = PendingUpdateStore(
        root_dir=tmp_path,
        key_registry=get_test_key_registry(),
        updater_protocol=1,
    )

    stage_svc = SoftwareUpdateStageService(
        pending_store=pending_store,
        asset_downloader=downloader,  # type: ignore[arg-type]
    )

    # 1. Launcher-only repair
    pending = stage_svc.stage_repair(resolved, components=("launcher",))
    assert pending.release_sequence == selector.sequence
    assert pending.release_id == selector.release_id
    assert pending.changed_components == ("launcher",)
    assert pending.launcher_artifact is not None
    assert pending.launcher_artifact.is_file()
    assert pending.core_artifact is None
    # Verify downloader was called ONLY for launcher
    urls = [c["initial_url"] for c in downloader.download_calls]
    assert "https://example.com/NekoLauncher.exe" in urls
    assert "https://example.com/NekoProxyCore.zip" not in urls

    # 2. Reject updater or empty
    with pytest.raises(SoftwareUpdateStageError):
        stage_svc.stage_repair(resolved, components=("updater",))
    with pytest.raises(SoftwareUpdateStageError):
        stage_svc.stage_repair(resolved, components=())


def test_software_update_apply_service_prepare_repair_sends_ipc_intent(tmp_path: Path) -> None:
    from neko_launcher.infrastructure.software_update_apply import (
        SoftwareUpdateApplyService,
    )

    selector = _make_selector()
    l_bytes = b"L" * 100
    l_sha = hashlib.sha256(l_bytes).hexdigest()
    resolved, env_bytes = _make_resolved_release(
        selector,
        launcher_size=100,
        launcher_sha=l_sha,
    )

    # Create dummy Updater binary for trust verification
    updater_bin = tmp_path / "NekoUpdater.exe"
    u_bytes = b"U" * 4096
    updater_bin.write_bytes(u_bytes)

    # Mock pending update
    gen_dir = tmp_path / "gen"
    gen_dir.mkdir(parents=True, exist_ok=True)
    l_art = gen_dir / "launcher.artifact"
    l_art.write_bytes(l_bytes)

    pending = VerifiedPendingUpdate(
        release_id=selector.release_id,
        release_sequence=selector.sequence,
        changed_components=("launcher",),
        envelope_bytes=env_bytes,
        generation_dir=gen_dir,
        launcher_artifact=l_art,
        core_artifact=None,
    )

    # Channel simulation
    tx_id = "1" * 32
    req_id = "2" * 32

    class DummyChannel:
        def __init__(self) -> None:
            self.sent: list[dict[str, Any]] = []

        def send_message(
            self, type: str, body: dict[str, Any], message_id: str | None = None
        ) -> str:
            self.sent.append({"type": type, "body": body})
            return "msg-1"

        def receive_message(self, timeout_s: float = 5.0) -> Any:
            last_type = self.sent[-1]["type"]
            if last_type == "BEGIN":
                return MagicMock(
                    type="REQUEST_READY",
                    message_id="msg-1",
                    body={
                        "accepted": True,
                        "request_id": req_id,
                        "transaction_id": tx_id,
                        "changed": {"launcher": True, "core": False},
                        "error": None,
                    },
                )
            elif last_type == "APPLY":
                return MagicMock(
                    type="APPLY_RESULT",
                    message_id="msg-1",
                    body={
                        "accepted": True,
                        "transaction_id": tx_id,
                        "error": None,
                    },
                )
            raise RuntimeError("Unexpected message")

        def close(self) -> None:
            pass

    dummy_channel = DummyChannel()
    dummy_proc = MagicMock()

    apply_svc = SoftwareUpdateApplyService(
        root_dir=tmp_path,
        spawner=lambda *args, **kwargs: dummy_proc,
        channel_factory=lambda: dummy_channel,
    )

    # Re-mock updater verification so dummy updater is trusted
    from unittest.mock import patch

    with patch(
        "neko_launcher.infrastructure.software_update_apply.verify_installed_updater"
    ) as mock_ver:
        mock_ver.return_value = MagicMock(trusted=True, reinstall_required=False)
        prep = apply_svc.prepare_repair(pending)
        prep.release()

    # Verify BEGIN payload contained intent="repair" and repair_components=["launcher"]
    assert len(dummy_channel.sent) >= 2
    begin_msg = dummy_channel.sent[0]
    assert begin_msg["type"] == "BEGIN"
    assert begin_msg["body"]["intent"] == "repair"
    assert begin_msg["body"]["repair_components"] == ["launcher"]

    # Verify APPLY payload contained expected IDs
    apply_msg = dummy_channel.sent[1]
    assert apply_msg["type"] == "APPLY"
    assert apply_msg["body"]["transaction_id"] == tx_id
    assert apply_msg["body"]["request_id"] == req_id


def test_broker_coordinator_handles_repair_intent_and_same_sequence(tmp_path: Path) -> None:
    import base64
    from neko_launcher.updater.broker import BrokerCoordinator
    from neko_launcher.updater.slot_selector import SelectionResult, SelectionStatus
    from neko_launcher.updater.state_models import Binding, Generation, State

    class FakeSlotStore:
        def __init__(self, initial_state: State | None = None) -> None:
            self.state = initial_state
            self.slot = "a"

        def load(self) -> SelectionResult:
            return SelectionResult(SelectionStatus.SELECTED, self.state, self.slot, None)

        def write_state(self, new_state: State) -> SelectionResult:
            self.state = new_state
            self.slot = "b" if self.slot == "a" else "a"
            return SelectionResult(SelectionStatus.SELECTED, self.state, self.slot, None)

    selector = _make_selector(
        sequence=9, release_id="stable-0009", version="5.1.3", tag_name="v5.1.3"
    )
    l_bytes = b"L" * 1024
    c_bytes = b"C" * 2048
    l_sha = hashlib.sha256(l_bytes).hexdigest()
    c_sha = hashlib.sha256(c_bytes).hexdigest()
    resolved, env_bytes = _make_resolved_release(
        selector,
        launcher_size=1024,
        launcher_sha=l_sha,
        core_size=2048,
        core_sha=c_sha,
    )
    env_b64 = base64.b64encode(env_bytes).decode("ascii")

    # Initial state: already committed at sequence 9!
    binding_9 = Binding(
        release_sequence=9,
        release_id="stable-0009",
        payload_sha256=resolved.authenticated_release.payload_sha256,
    )
    committed_gen = Generation(
        binding=binding_9,
        launcher_identity_sha256=l_sha,
        core_identity_sha256=c_sha,
    )
    state = State(
        schema_version=1,
        revision=1,
        installation_id="f" * 32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=committed_gen,
        previous=None,
        highwater=binding_9,
        observed=binding_9,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={binding_9.payload_sha256: env_b64},
    )

    slot_store = FakeSlotStore(state)
    coordinator = BrokerCoordinator(tmp_path, slot_store, get_test_key_registry())

    # Begin with intent="repair", repair_components=["launcher"]
    res = coordinator.begin(env_b64, intent="repair", repair_components=["launcher"])
    assert res.accepted is True
    assert res.changed == {"launcher": True, "core": False}
    assert res.request_id is not None
    assert res.transaction_id is not None

    # Verify transaction in state recorded repair_components
    cur = slot_store.load().state
    assert cur is not None
    assert cur.transaction is not None
    assert cur.transaction.repair_components == ("launcher",)

    # Place incoming artifact
    incoming = tmp_path / "incoming" / res.request_id
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "launcher.artifact").write_bytes(l_bytes)

    # Apply through coordinator with verifier bypassed
    coordinator.published_verifier = MagicMock()
    # Mock old release layout so build_generation can read old core
    old_id = f"g-{9:020d}-{binding_9.payload_sha256}"
    old_core = tmp_path / "releases" / old_id / "ProxyCore"
    old_core.mkdir(parents=True, exist_ok=True)
    (old_core / "NekoProxyCore.exe").write_bytes(b"core-exe")
    (old_core / "core-manifest.json").write_bytes(c_bytes)

    from unittest.mock import patch

    with patch(
        "neko_launcher.updater.generation_builder.verify_canonical_core_bundle"
    ) as mock_core:
        mock_core.return_value = MagicMock(valid=True, manifest_sha256=c_sha)
        apply_res = coordinator.apply(res.transaction_id, res.request_id)
        assert apply_res.accepted is True
