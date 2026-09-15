from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.enrollment import validate_enrollment_trust_binding
from neko_launcher.updater.trust_profile import load_installed_update_trust_profile
from tests.software_update_helpers import signed_envelope, valid_v2_release_document


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


def _make_enrollment_install(tmp_path: Path) -> tuple[Path, dict[str, bytes], str, Ed25519PrivateKey]:
    install = tmp_path / "app"
    install.mkdir(parents=True, exist_ok=True)

    launcher_bytes = b"launcher-binary-v512"
    updater_bytes = b"updater-binary-v512"
    core_manifest_bytes = b'{"source_commit":"c512","files":[]}'

    (install / "NekoLauncher.exe").write_bytes(launcher_bytes)
    (install / "NekoUpdater.exe").write_bytes(updater_bytes)
    proxy_core = install / "ProxyCore"
    proxy_core.mkdir(parents=True, exist_ok=True)
    (proxy_core / "core-manifest.json").write_bytes(core_manifest_bytes)

    auth_priv = Ed25519PrivateKey.generate()
    auth_pub = auth_priv.public_key().public_bytes_raw()
    auth_key_id = "test-profile-auth-1"

    rel_priv = Ed25519PrivateKey.generate()
    rel_pub = rel_priv.public_key().public_bytes_raw()
    rel_key_id = "test-rel-key-1"

    profile_payload = {
        "channel": "stable",
        "owner": "Valeneko-pranmong",
        "profile_id": "proof-v512",
        "release_keys": [{"key_id": rel_key_id, "public_key_hex": rel_pub.hex()}],
        "repository": "Neko-Family-Proxy-Updates-Proof",
    }
    payload_bytes = canonical_json_dumps(profile_payload)
    sig_bytes = auth_priv.sign(payload_bytes)
    profile_envelope = {
        "key_id": auth_key_id,
        "payload": profile_payload,
        "schema_version": 1,
        "signature_b64": base64.b64encode(sig_bytes).decode("ascii"),
    }
    trust_dir = install / "trust"
    trust_dir.mkdir(parents=True, exist_ok=True)
    (trust_dir / "update-profile-v1.json").write_bytes(canonical_json_dumps(profile_envelope) + b"\n")

    doc = valid_v2_release_document(
        sequence=1,
        release_id="rel-0001",
        channel="stable",
        launcher_sha=hashlib.sha256(launcher_bytes).hexdigest(),
        launcher_size=len(launcher_bytes),
        updater_sha=hashlib.sha256(updater_bytes).hexdigest(),
        updater_size=len(updater_bytes),
        core_installed_sha=hashlib.sha256(core_manifest_bytes).hexdigest(),
        core_sha=hashlib.sha256(b"dummy-core").hexdigest(),
        core_size=1024,
    )
    env_dict = signed_envelope(doc, key_id=rel_key_id, private_key=rel_priv)
    baseline_dir = install / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / "release-v2.json").write_bytes(canonical_json_dumps(env_dict) + b"\n")

    return install, {auth_key_id: auth_pub}, auth_key_id, auth_priv


def test_main_enroll_baseline_happy_path_and_idempotence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install, auth_keys, _, _ = _make_enrollment_install(tmp_path)

    monkeypatch.setattr("neko_launcher.updater.root_validator.get_expected_install_root", lambda: install)
    monkeypatch.setattr("neko_launcher.updater.trust.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr("neko_launcher.updater.trust_profile.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)

    monkeypatch.setattr(
        "neko_launcher.main.build_window",
        lambda: (_ for _ in ()).throw(AssertionError("UI must not be built")),
    )

    # 1. First enrollment run exits 0 and creates enrollment.bin
    monkeypatch.setattr(sys, "argv", ["NekoLauncher.exe", "--enroll-baseline"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    marker_path = install / "state" / "enrollment.bin"
    assert marker_path.exists(), "enrollment.bin must be written"

    verified_profile = load_installed_update_trust_profile(install)
    marker = validate_enrollment_trust_binding(install, verified_profile)
    assert marker.profile_id == "proof-v512"
    assert marker.keyset_sha256 == verified_profile.keyset_sha256

    # 2. Second enrollment run is idempotent, also exits 0
    with pytest.raises(SystemExit) as exc_info2:
        main()
    assert exc_info2.value.code == 0


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--key", "foo"],
        ["--profile", "bar"],
        ["--sequence", "1"],
        ["--release-id", "r1"],
        ["--channel", "beta"],
        ["--trust-root", "tr"],
        ["--path", "some/path"],
        ["arbitrary"],
    ],
)
def test_main_enroll_baseline_rejects_extra_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_args: list[str]
) -> None:
    install, auth_keys, _, _ = _make_enrollment_install(tmp_path)
    monkeypatch.setattr("neko_launcher.updater.root_validator.get_expected_install_root", lambda: install)
    monkeypatch.setattr("neko_launcher.updater.trust.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr("neko_launcher.updater.trust_profile.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr(
        "neko_launcher.main.build_window",
        lambda: (_ for _ in ()).throw(AssertionError("UI must not be built")),
    )

    monkeypatch.setattr(sys, "argv", ["NekoLauncher.exe", "--enroll-baseline"] + extra_args)
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_main_enroll_baseline_fails_on_profile_authority_tamper_before_release_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install, auth_keys, _, _ = _make_enrollment_install(tmp_path)
    monkeypatch.setattr("neko_launcher.updater.root_validator.get_expected_install_root", lambda: install)
    monkeypatch.setattr("neko_launcher.updater.trust.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr("neko_launcher.updater.trust_profile.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr(
        "neko_launcher.main.build_window",
        lambda: (_ for _ in ()).throw(AssertionError("UI must not be built")),
    )

    # Tamper trust profile byte
    prof_path = install / "trust" / "update-profile-v1.json"
    data = bytearray(prof_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    prof_path.write_bytes(bytes(data))

    monkeypatch.setattr(sys, "argv", ["NekoLauncher.exe", "--enroll-baseline"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_main_enroll_baseline_fails_on_tampered_release_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install, auth_keys, _, _ = _make_enrollment_install(tmp_path)
    monkeypatch.setattr("neko_launcher.updater.root_validator.get_expected_install_root", lambda: install)
    monkeypatch.setattr("neko_launcher.updater.trust.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr("neko_launcher.updater.trust_profile.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr(
        "neko_launcher.main.build_window",
        lambda: (_ for _ in ()).throw(AssertionError("UI must not be built")),
    )

    # Tamper baseline release envelope byte
    env_path = install / "baseline" / "release-v2.json"
    data = bytearray(env_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    env_path.write_bytes(bytes(data))

    monkeypatch.setattr(sys, "argv", ["NekoLauncher.exe", "--enroll-baseline"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_main_enroll_baseline_fails_when_fixed_paths_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install, auth_keys, _, _ = _make_enrollment_install(tmp_path)
    monkeypatch.setattr("neko_launcher.updater.root_validator.get_expected_install_root", lambda: install)
    monkeypatch.setattr("neko_launcher.updater.trust.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr("neko_launcher.updater.trust_profile.PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)
    monkeypatch.setattr(
        "neko_launcher.main.build_window",
        lambda: (_ for _ in ()).throw(AssertionError("UI must not be built")),
    )

    # Remove baseline release envelope
    (install / "baseline" / "release-v2.json").unlink()

    monkeypatch.setattr(sys, "argv", ["NekoLauncher.exe", "--enroll-baseline"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0
