from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import tests as _root_tests
_launcher_tests_dir = str(Path(__file__).resolve().parent)
if hasattr(_root_tests, "__path__") and _launcher_tests_dir not in _root_tests.__path__:
    _root_tests.__path__.append(_launcher_tests_dir)

from neko_launcher.updater.canonical_json import canonical_json_dumps  # noqa: E402
from tests.software_update_helpers import signed_envelope, valid_v2_release_document  # noqa: E402


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "installer" / "scripts" / "build_beta_installer.py"
HEX_A = "a" * 64
HEX_B = "b" * 64
CORE_AUTHORITY = "operator-approved-core-authority"

TEST_AUTH_KEY_ID = "neko-update-profile-v512-1"
TEST_AUTH_PRIV = Ed25519PrivateKey.from_private_bytes(b"a" * 32)
TEST_AUTH_PUB = TEST_AUTH_PRIV.public_key().public_bytes_raw()
TEST_AUTH_REGISTRY = {TEST_AUTH_KEY_ID: TEST_AUTH_PUB}

TEST_REL_KEY_ID = "test-rel-key-1"
TEST_REL_PRIV = Ed25519PrivateKey.from_private_bytes(b"r" * 32)
TEST_REL_PUB = TEST_REL_PRIV.public_key().public_bytes_raw()


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("phase3_build_beta_installer", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        module.PROFILE_AUTHORITY_PUBLIC_KEYS = dict(TEST_AUTH_REGISTRY)
    return module


def _candidate_api(module: ModuleType) -> tuple[Any, Any]:
    parse_args = getattr(module, "parse_args", None)
    build_candidate = getattr(module, "build_candidate", None)
    assert callable(parse_args), "candidate builder must expose parse_args(argv)"
    assert callable(build_candidate), "candidate builder must expose build_candidate(args)"
    return parse_args, build_candidate


def _argv(
    stage: Path,
    launcher_hash: str = HEX_A,
    updater_hash: str = HEX_B,
    baseline_envelope: Path | str | None = None,
    trust_profile: Path | str | None = None,
) -> list[str]:
    env_path = str(baseline_envelope if baseline_envelope is not None else stage / "baseline_envelope.json")
    prof_path = str(trust_profile if trust_profile is not None else stage / "trust_profile.json")
    return [
        "--candidate-dir",
        str(stage),
        "--launcher-sha256",
        launcher_hash,
        "--updater-sha256",
        updater_hash,
        "--core-authority",
        CORE_AUTHORITY,
        "--release-version",
        "5.1.3",
        "--baseline-envelope",
        env_path,
        "--trust-profile",
        prof_path,
    ]


def _stage(tmp_path: Path) -> Path:
    stage = tmp_path / "candidate"
    payload = stage / "payload"
    core = payload / "CoreBundle"
    prereqs = payload / "Prereqs"
    (core / "bin").mkdir(parents=True)
    prereqs.mkdir()
    (payload / "NekoLauncher.exe").write_bytes(b"launcher")
    (payload / "NekoUpdater.exe").write_bytes(b"updater")
    (core / "bin" / "v2ray-sn.exe").write_bytes(b"v2ray")
    (core / "runtime-settings.nkps").write_bytes(b"sealed")
    core_manifest_bytes = (
        '{"source_commit": "' + CORE_AUTHORITY + '", "files": '
        '[{"path": "bin/v2ray-sn.exe", "sha256": "' + _digest(b"v2ray")
        + '", "size": 5}], '
        '"v2ray_sn_exe_hash": "' + _digest(b"v2ray") + '"}'
    ).encode("utf-8")
    (core / "core-manifest.json").write_bytes(core_manifest_bytes)
    (prereqs / "windowsdesktop-runtime-6.0.36-win-x64.exe").write_bytes(b"dotnet")

    # Create default valid envelope & trust profile in stage dir
    stage.mkdir(parents=True, exist_ok=True)
    profile_payload = {
        "channel": "stable",
        "owner": "Valeneko-pranmong",
        "profile_id": "proof-v512",
        "release_keys": [{"key_id": TEST_REL_KEY_ID, "public_key_hex": TEST_REL_PUB.hex()}],
        "repository": "Neko-Family-Proxy-Updates-Proof",
    }
    payload_bytes = canonical_json_dumps(profile_payload)
    sig_bytes = TEST_AUTH_PRIV.sign(payload_bytes)
    profile_envelope = {
        "key_id": TEST_AUTH_KEY_ID,
        "payload": profile_payload,
        "schema_version": 1,
        "signature_b64": base64.b64encode(sig_bytes).decode("ascii"),
    }
    (stage / "trust_profile.json").write_bytes(canonical_json_dumps(profile_envelope) + b"\n")

    doc = valid_v2_release_document(
        sequence=1,
        release_id="rel-0001",
        channel="stable",
        launcher_sha=_digest(b"launcher"),
        launcher_size=len(b"launcher"),
        updater_sha=_digest(b"updater"),
        updater_size=len(b"updater"),
        core_installed_sha=_digest(core_manifest_bytes),
        core_sha=_digest(b"core-zip"),
        core_size=1024,
    )
    env_dict = signed_envelope(doc, key_id=TEST_REL_KEY_ID, private_key=TEST_REL_PRIV)
    (stage / "baseline_envelope.json").write_bytes(canonical_json_dumps(env_dict) + b"\n")

    return stage


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_import_is_side_effect_free_and_paths_are_worktree_relative() -> None:
    module = _load_builder()
    assert Path(module.REPO).resolve() == REPOSITORY_ROOT.resolve(), (
        "REPO must derive from build_beta_installer.py, not historical E:\\Github\\Neko-Family-Proxy"
    )
    assert Path(module.ISS_PATH).resolve() == (REPOSITORY_ROOT / "installer" / "beta.iss").resolve()


def test_candidate_authorities_are_explicit_and_canonical() -> None:
    module = _load_builder()
    parse_args, _ = _candidate_api(module)

    required_options = (
        "--launcher-sha256",
        "--updater-sha256",
        "--core-authority",
        "--baseline-envelope",
        "--trust-profile",
    )
    for omitted in required_options:
        argv = _argv(Path("candidate"))
        index = argv.index(omitted)
        del argv[index : index + 2]
        with pytest.raises(SystemExit):
            parse_args(argv)

    for option in ("--launcher-sha256", "--updater-sha256"):
        for malformed in ("A" * 64, "a" * 63, "g" * 64):
            argv = _argv(Path("candidate"))
            argv[argv.index(option) + 1] = malformed
            with pytest.raises(SystemExit):
                parse_args(argv)


def test_candidate_mode_has_no_implicit_historical_launcher_authority() -> None:
    module = _load_builder()
    historical = getattr(module, "APPROVED_LAUNCHER_SHA256", None)
    assert historical is None, (
        "candidate builder must remove APPROVED_LAUNCHER_SHA256 as an implicit authority; "
        "the operator must supply --launcher-sha256"
    )


def test_candidate_mode_cannot_use_historical_launcher_default() -> None:
    module = _load_builder()
    parse_args, _ = _candidate_api(module)
    historical = getattr(module, "APPROVED_LAUNCHER_SHA256", None)
    assert historical is None or parse_args(_argv(Path("candidate"))).launcher_sha256 != historical, (
        "candidate mode must not inherit APPROVED_LAUNCHER_SHA256"
    )


@pytest.mark.parametrize(
    ("target", "approved"),
    (("launcher", "0" * 64), ("updater", "0" * 64)),
)
def test_stale_binary_authority_fails_before_iscc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    approved: str,
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    launcher_hash = approved if target == "launcher" else _digest(b"launcher")
    updater_hash = approved if target == "updater" else _digest(b"updater")
    iscc_called = False

    def forbidden_find_iscc() -> str:
        nonlocal iscc_called
        iscc_called = True
        raise AssertionError("find_iscc reached before authority validation")

    monkeypatch.setattr(module, "find_iscc", forbidden_find_iscc)
    with pytest.raises((SystemExit, ValueError), match="sha|hash|mismatch"):
        build_candidate(parse_args(_argv(stage, launcher_hash, updater_hash)))
    assert not iscc_called


def test_matching_explicit_hashes_reach_controlled_later_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    observed: list[str] = []

    def controlled_iscc() -> str:
        observed.append("find_iscc")
        raise RuntimeError("CONTROLLED_LATER_GATE")

    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0})())
    monkeypatch.setattr(module, "find_iscc", controlled_iscc)
    with pytest.raises(RuntimeError, match="CONTROLLED_LATER_GATE"):
        build_candidate(
            parse_args(_argv(stage, _digest(b"launcher"), _digest(b"updater")))
        )
    assert observed == ["find_iscc"]

def test_core_manifest_list_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    core = stage / "payload" / "CoreBundle"

    (core / "dummy.dll").write_bytes(b"dummy")

    list_manifest = {
        "source_commit": CORE_AUTHORITY,
        "v2ray_sn_exe_hash": _digest(b"v2ray"),
        "files": [
            {
                "path": "dummy.dll",
                "size": 5,
                "sha256": _digest(b"dummy")
            }
        ]
    }
    (core / "core-manifest.json").write_text(json.dumps(list_manifest), encoding="utf-8")

    doc = valid_v2_release_document(
        sequence=1,
        release_id="rel-0001",
        channel="stable",
        launcher_sha=_digest(b"launcher"),
        launcher_size=len(b"launcher"),
        updater_sha=_digest(b"updater"),
        updater_size=len(b"updater"),
        core_installed_sha=_digest((core / "core-manifest.json").read_bytes()),
        core_sha=_digest(b"core-zip"),
        core_size=1024,
    )
    env_dict = signed_envelope(doc, key_id=TEST_REL_KEY_ID, private_key=TEST_REL_PRIV)
    (stage / "baseline_envelope.json").write_bytes(canonical_json_dumps(env_dict) + b"\n")

    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0})())

    def controlled_iscc() -> str:
        raise RuntimeError("CONTROLLED_LATER_GATE")
    monkeypatch.setattr(module, "find_iscc", controlled_iscc)

    with pytest.raises(RuntimeError, match="CONTROLLED_LATER_GATE"):
        build_candidate(parse_args(_argv(stage, _digest(b"launcher"), _digest(b"updater"))))

def test_core_manifest_list_schema_malformed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    core = stage / "payload" / "CoreBundle"

    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0})())

    # Missing sha256
    (core / "core-manifest.json").write_text(json.dumps({
        "source_commit": CORE_AUTHORITY,
        "v2ray_sn_exe_hash": _digest(b"v2ray"),
        "files": [{"path": "dummy.dll"}]
    }), encoding="utf-8")

    with pytest.raises(KeyError, match="sha256"):
        build_candidate(parse_args(_argv(stage, _digest(b"launcher"), _digest(b"updater"))))

def test_static_beta_iss_inspection() -> None:
    iss_text = (REPOSITORY_ROOT / "installer" / "beta.iss").read_text(encoding="utf-8")
    assert "g_CoreVerifyOK and g_DotnetOK and g_DriverOK" in iss_text, "LaunchAllowed must check driver"
    assert "OutputBaseFilename=NekoFamilyProxy-Installer" in iss_text, "Output exactly NekoFamilyProxy-Installer.exe"
    assert "#ifndef MyAppVersion" in iss_text, "MyAppVersion must be overrideable"
    assert "#ifndef MyAppDisplayVersion" in iss_text, "MyAppDisplayVersion must be overrideable"
    assert "#ifndef CoreAuthority" in iss_text, "CoreAuthority must be overrideable"
    assert '#define CoreAuthority ""' in iss_text, "CoreAuthority must default to empty"
    assert 'RunPSFile(VerifyScript, \' -CoreDir "\' + CoreDir + \'" -ExpectedCommit "{#CoreAuthority}"\', RC)' in iss_text or \
           'RunPSFile(VerifyScript, \' -CoreDir "\' + CoreDir + \'" -CoreAuthority "{#CoreAuthority}"\', RC)' in iss_text, \
           "Post-install verifier must receive candidate-specific CoreAuthority"
    assert "Please install the runtime" not in iss_text, "must not instruct manual install"
    assert "ต้องติดตั้ง Microsoft .NET Desktop Runtime" not in iss_text, "must not instruct manual install"
    assert "Please run this same Setup again and allow the required Windows UAC prompt" in iss_text, "must instruct rerunning setup"
    assert "หากยังพบปัญหานี้อยู่ โปรดติดต่อผู้ดูแล" in iss_text, "must instruct contacting operator on failure"


def test_beta_iss_64bit_powershell_redirection_guard() -> None:
    iss_text = (REPOSITORY_ROOT / "installer" / "beta.iss").read_text(encoding="utf-8")
    assert "{sysnative}" in iss_text, "beta.iss must use {sysnative} on 64-bit Windows to avoid 32-bit WOW64 redirection"
    assert "IsWin64" in iss_text, "beta.iss must check IsWin64 for powershell path"


def test_ensure_netfilter2_clean_encoding_no_bom() -> None:
    ps1_text = (REPOSITORY_ROOT / "installer" / "scripts" / "ensure-netfilter2.ps1").read_text(encoding="utf-8")
    assert "-Encoding UTF8" not in ps1_text, "ensure-netfilter2.ps1 must not write UTF-8 BOM to ResultFile"


def test_beta_iss_baseline_enrollment_contract() -> None:
    iss_text = (REPOSITORY_ROOT / "installer" / "beta.iss").read_text(encoding="utf-8")
    assert r'{#PayloadDir}\trust\update-profile-v1.json' in iss_text and r'{app}\trust' in iss_text, (
        "beta.iss must install exact trust/update-profile-v1.json to {app}/trust"
    )
    assert r'{#PayloadDir}\baseline\release-v2.json' in iss_text and r'{app}\baseline' in iss_text, (
        "beta.iss must install exact baseline/release-v2.json to {app}/baseline"
    )
    assert "--enroll-baseline" in iss_text, "beta.iss must invoke --enroll-baseline"
    assert "g_EnrollmentOK" in iss_text, "beta.iss must track enrollment outcome"
    assert "g_EnrollmentOK" in iss_text.split("function LaunchAllowed")[1].split("end;")[0], (
        "LaunchAllowed must require g_EnrollmentOK to suppress normal launch on nonzero enrollment"
    )


def test_verify_core_install_no_stale_fixed_authority_in_script() -> None:
    ps1_path = REPOSITORY_ROOT / "installer" / "scripts" / "verify-core-install.ps1"
    ps1_text = ps1_path.read_text(encoding="utf-8")

    stale_commit = "33f97ae0110075089f39b1e123890f931417d907"
    assert stale_commit not in ps1_text, (
        "verify-core-install.ps1 must not hardcode stale authority " f"{stale_commit}"
    )
    assert "$ExpectedCommit" in ps1_text or "$CoreAuthority" in ps1_text, (
        "verify-core-install.ps1 must accept candidate authority as an explicit parameter"
    )
    assert "param(" in ps1_text and "ExpectedCommit" in ps1_text, (
        "verify-core-install.ps1 param block must include ExpectedCommit"
    )


def _setup_verified_core_dir(
    core_dir: Path,
    source_commit: str,
    v2ray_bytes: bytes,
    v2ray_hash: str,
) -> None:
    bin_dir = core_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    v2ray_target = bin_dir / "v2ray-sn.exe"
    v2ray_target.write_bytes(v2ray_bytes)

    (core_dir / "runtime-settings.nkps").write_bytes(b"nkps-content")

    manifest = {
        "source_commit": source_commit,
        "v2ray_sn_exe_hash": v2ray_hash,
        "files": [
            {
                "path": "bin/v2ray-sn.exe",
                "size": len(v2ray_bytes),
                "sha256": v2ray_hash,
            }
        ],
    }
    (core_dir / "core-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _run_verify_ps1(
    core_dir: Path,
    authority: str | None = None,
    param_flag: str = "-ExpectedCommit",
    expected_v2ray_hash: str | None = None,
) -> tuple[int, str]:
    production_script = REPOSITORY_ROOT / "installer" / "scripts" / "verify-core-install.ps1"
    if expected_v2ray_hash is not None:
        script_text = production_script.read_text(encoding="utf-8")
        test_script = core_dir.parent / "verify-core-install.test.ps1"
        test_script.write_text(
            script_text.replace(
                "a219f435671fb214c0c530084c65e576fdc1404f40b187b5586e869d2a3e4dff",
                expected_v2ray_hash,
            ),
            encoding="utf-8",
        )
        script_path = str(test_script)
    else:
        script_path = str(production_script)

    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        script_path,
        "-CoreDir",
        str(core_dir),
    ]
    if authority is not None:
        cmd.extend([param_flag, authority])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def test_production_approved_v2ray_sha256_pins_remain_intact() -> None:
    expected_pin = "a219f435671fb214c0c530084c65e576fdc1404f40b187b5586e869d2a3e4dff"
    module = _load_builder()
    assert module.APPROVED_V2RAY_SHA256 == expected_pin, (
        "Production APPROVED_V2RAY_SHA256 in build_beta_installer.py must remain unchanged"
    )
    ps1_text = (REPOSITORY_ROOT / "installer" / "scripts" / "verify-core-install.ps1").read_text(
        encoding="utf-8"
    )
    assert f"$v2rayExpected = '{expected_pin}'" in ps1_text, (
        "verify-core-install.ps1 must hardcode approved production v2ray hash"
    )


def test_post_install_verifier_accepts_matching_candidate_authority_and_rejects_mismatch(tmp_path: Path) -> None:
    core_dir = tmp_path / "ProxyCore"
    candidate_commit = "6ab94bb"
    v2ray_bytes = b"synthetic-v2ray-sn-fixture-bytes-for-authority-check"
    v2ray_hash = _digest(v2ray_bytes)
    _setup_verified_core_dir(core_dir, candidate_commit, v2ray_bytes, v2ray_hash)

    # 1. Matching candidate authority via -ExpectedCommit passes
    rc, out = _run_verify_ps1(core_dir, candidate_commit, "-ExpectedCommit", expected_v2ray_hash=v2ray_hash)
    assert rc == 0, f"Expected 0 on matching authority, got {rc}: {out}"
    assert "PASS: core manifest verified" in out

    # 2. Matching candidate authority via -CoreAuthority alias passes
    rc, out = _run_verify_ps1(core_dir, candidate_commit, "-CoreAuthority", expected_v2ray_hash=v2ray_hash)
    assert rc == 0, f"Expected 0 on matching alias authority, got {rc}: {out}"
    assert "PASS: core manifest verified" in out

    # 3. Old stale fixed authority (33f97ae...) fails closed with exit code 4
    stale_commit = "33f97ae0110075089f39b1e123890f931417d907"
    rc, out = _run_verify_ps1(core_dir, stale_commit, "-ExpectedCommit", expected_v2ray_hash=v2ray_hash)
    assert rc == 4, f"Expected 4 on stale authority mismatch, got {rc}: {out}"
    assert "FAIL: source_commit mismatch" in out

    # 4. Arbitrary different authority fails closed with exit code 4
    rc, out = _run_verify_ps1(core_dir, "0000000000000000000000000000000000000000", "-ExpectedCommit", expected_v2ray_hash=v2ray_hash)
    assert rc == 4, f"Expected 4 on authority mismatch, got {rc}: {out}"
    assert "FAIL: source_commit mismatch" in out

    # 5. Missing / omitted authority fails closed with exit code 4
    rc, out = _run_verify_ps1(core_dir, None, expected_v2ray_hash=v2ray_hash)
    assert rc == 4, f"Expected 4 on omitted authority, got {rc}: {out}"
    assert "FAIL: source_commit mismatch" in out

    # 6. Whitespace authority fails closed with exit code 4
    rc, out = _run_verify_ps1(core_dir, "   ", "-ExpectedCommit", expected_v2ray_hash=v2ray_hash)
    assert rc == 4, f"Expected 4 on whitespace authority, got {rc}: {out}"
    assert "FAIL: source_commit mismatch" in out

    # 7. Hash mismatch fails closed with exit code 7
    rc, out = _run_verify_ps1(core_dir, candidate_commit, "-ExpectedCommit", expected_v2ray_hash="0" * 64)
    assert rc == 7, f"Expected 7 on v2ray hash mismatch, got {rc}: {out}"
    assert "FAIL: v2ray-sn.exe hash mismatch" in out


def test_candidate_build_record_and_post_install_verification_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)

    candidate_authority = "6ab94bb"
    stage = tmp_path / "candidate"
    payload = stage / "payload"
    core = payload / "CoreBundle"
    prereqs = payload / "Prereqs"
    (core / "bin").mkdir(parents=True)
    prereqs.mkdir()
    (payload / "NekoLauncher.exe").write_bytes(b"launcher")
    (payload / "NekoUpdater.exe").write_bytes(b"updater")
    (core / "runtime-settings.nkps").write_bytes(b"sealed")
    (prereqs / "windowsdesktop-runtime-6.0.36-win-x64.exe").write_bytes(b"dotnet")

    v2ray_bytes = b"synthetic-v2ray-sn-for-build-record-agreement"
    v2ray_hash = _digest(v2ray_bytes)
    (core / "bin" / "v2ray-sn.exe").write_bytes(v2ray_bytes)

    manifest = {
        "source_commit": candidate_authority,
        "v2ray_sn_exe_hash": v2ray_hash,
        "files": [
            {
                "path": "bin/v2ray-sn.exe",
                "size": len(v2ray_bytes),
                "sha256": v2ray_hash,
            }
        ],
    }
    (core / "core-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    real_subprocess_run = subprocess.run
    iscc_invoked_args = []

    def mock_find_iscc() -> str:
        return "mock_iscc.exe"

    def mock_subprocess_run(args, **kwargs) -> Any:
        if args and args[0] == "mock_iscc.exe":
            iscc_invoked_args.extend(args)
            out_dir = stage / "out"
            out_dir.mkdir(exist_ok=True)
            (out_dir / "NekoFamilyProxy-Installer.exe").write_bytes(b"mock_installer")
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if args and str(args[0]).endswith("NekoUpdater.exe"):
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return real_subprocess_run(args, **kwargs)

    monkeypatch.setattr(module, "APPROVED_V2RAY_SHA256", v2ray_hash)
    monkeypatch.setattr(module, "DOTNET_RUNTIME_SHA256_PIN", _digest(b"dotnet"))
    monkeypatch.setattr(module, "find_iscc", mock_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", mock_subprocess_run)

    prof_file, env_file, _ = _make_keys_and_files(stage)
    (stage / "trust_profile.json").write_bytes(prof_file.read_bytes())
    (stage / "baseline_envelope.json").write_bytes(env_file.read_bytes())

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater"))
    argv[argv.index("--core-authority") + 1] = candidate_authority

    # Build candidate accepts the candidate authority
    ret = build_candidate(parse_args(argv))
    assert ret == 0

    # Build record records the exact core_authority
    record_path = stage / "out" / "build-record.json"
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["core_authority"] == candidate_authority

    # ISCC received the exact core_authority define
    assert f"/DCoreAuthority={candidate_authority}" in iscc_invoked_args

    # Verification of the staged CoreBundle using the build record's core_authority passes
    rc, out = _run_verify_ps1(core, record["core_authority"], expected_v2ray_hash=v2ray_hash)
    assert rc == 0, f"Expected 0 with record authority, got {rc}: {out}"
    assert "PASS: core manifest verified" in out

    # Verification with mismatched authority fails closed with exit code 4
    rc, out = _run_verify_ps1(core, "different_authority", expected_v2ray_hash=v2ray_hash)
    assert rc == 4, f"Expected 4 with mismatched authority, got {rc}: {out}"
    assert "FAIL: source_commit mismatch" in out

    # Verification with mismatched v2ray hash fails closed with exit code 7
    rc, out = _run_verify_ps1(core, record["core_authority"], expected_v2ray_hash="0" * 64)
    assert rc == 7, f"Expected 7 with mismatched v2ray hash, got {rc}: {out}"
    assert "FAIL: v2ray-sn.exe hash mismatch" in out


def test_builder_record_contains_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)

    def mock_find_iscc() -> str:
        return "mock_iscc.exe"

    def mock_subprocess_run(args, **kwargs) -> Any:
        if args and args[0] == "mock_iscc.exe":
            assert "/DMyAppVersion=5.1.3" in args
            assert "/DMyAppDisplayVersion=5.1.3" in args
            assert f"/DCoreAuthority={CORE_AUTHORITY}" in args
            assert not any(a.startswith("/DAppVersion=") for a in args)
            out_dir = stage / "out"
            out_dir.mkdir(exist_ok=True)
            (out_dir / "NekoFamilyProxy-Installer.exe").write_bytes(b"mock_installer")
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        # Mock for updater --self-check
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(module, "APPROVED_V2RAY_SHA256", _digest(b"v2ray"))
    monkeypatch.setattr(module, "DOTNET_RUNTIME_SHA256_PIN", _digest(b"dotnet"))
    monkeypatch.setattr(module, "find_iscc", mock_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", mock_subprocess_run)

    assert build_candidate(parse_args(_argv(stage, _digest(b"launcher"), _digest(b"updater")))) == 0

    record_path = stage / "out" / "build-record.json"
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert "core_installed_identity" in record
    manifest_bytes = (stage / "payload" / "CoreBundle" / "core-manifest.json").read_bytes()
    assert record["core_installed_identity"] == _digest(manifest_bytes)
    assert record["release_version"] == "5.1.3"
    assert "installer_version" not in record
    assert record["installer_file"] == "NekoFamilyProxy-Installer.exe"


def _make_keys_and_files(tmp_path: Path, channel: str = "stable") -> tuple[Path, Path, dict[str, bytes]]:
    auth_priv = TEST_AUTH_PRIV
    auth_pub = TEST_AUTH_PUB
    auth_key_id = TEST_AUTH_KEY_ID

    rel_priv = TEST_REL_PRIV
    rel_pub = TEST_REL_PUB
    rel_key_id = TEST_REL_KEY_ID

    profile_payload = {
        "channel": channel,
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
    profile_bytes = canonical_json_dumps(profile_envelope) + b"\n"
    profile_path = tmp_path / "update-profile-v1.json"
    profile_path.write_bytes(profile_bytes)

    launcher_bytes = b"launcher"
    updater_bytes = b"updater"
    manifest_file = tmp_path / "payload" / "CoreBundle" / "core-manifest.json"
    if manifest_file.is_file():
        core_manifest_bytes = manifest_file.read_bytes()
    else:
        core_manifest_bytes = (
            '{"source_commit": "' + CORE_AUTHORITY + '", "files": '
            '[{"path": "bin/v2ray-sn.exe", "sha256": "' + _digest(b"v2ray")
            + '", "size": 5}], '
            '"v2ray_sn_exe_hash": "' + _digest(b"v2ray") + '"}'
        ).encode("utf-8")

    doc = valid_v2_release_document(
        sequence=1,
        release_id="rel-0001",
        channel=channel,
        launcher_sha=_digest(launcher_bytes),
        launcher_size=len(launcher_bytes),
        updater_sha=_digest(updater_bytes),
        updater_size=len(updater_bytes),
        core_installed_sha=_digest(core_manifest_bytes),
        core_sha=_digest(b"core-zip"),
        core_size=1024,
    )
    env_dict = signed_envelope(doc, key_id=rel_key_id, private_key=rel_priv)
    envelope_bytes = canonical_json_dumps(env_dict) + b"\n"
    envelope_path = tmp_path / "release-v2.json"
    envelope_path.write_bytes(envelope_bytes)

    return profile_path, envelope_path, {auth_key_id: auth_pub}


def test_builder_requires_signed_baseline_envelope(tmp_path: Path) -> None:
    module = _load_builder()
    parse_args, _ = _candidate_api(module)
    stage = _stage(tmp_path)
    argv = _argv(stage)
    idx = argv.index("--baseline-envelope")
    del argv[idx : idx + 2]
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_builder_requires_trust_profile(tmp_path: Path) -> None:
    module = _load_builder()
    parse_args, _ = _candidate_api(module)
    stage = _stage(tmp_path)
    argv = _argv(stage)
    idx = argv.index("--trust-profile")
    del argv[idx : idx + 2]
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_builder_stages_envelope_and_profile_byte_identical_and_records_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    profile_path, envelope_path, auth_keys = _make_keys_and_files(tmp_path)

    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        monkeypatch.setattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)

    def mock_find_iscc() -> str:
        return "mock_iscc.exe"

    def mock_subprocess_run(args, **kwargs) -> Any:
        if args and args[0] == "mock_iscc.exe":
            out_dir = stage / "out"
            out_dir.mkdir(exist_ok=True)
            (out_dir / "NekoFamilyProxy-Installer.exe").write_bytes(b"mock_installer")
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(module, "APPROVED_V2RAY_SHA256", _digest(b"v2ray"))
    monkeypatch.setattr(module, "DOTNET_RUNTIME_SHA256_PIN", _digest(b"dotnet"))
    monkeypatch.setattr(module, "find_iscc", mock_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", mock_subprocess_run)

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater")) + [
        "--baseline-envelope",
        str(envelope_path),
        "--trust-profile",
        str(profile_path),
    ]

    ret = build_candidate(parse_args(argv))
    assert ret == 0

    staged_envelope = stage / "payload" / "baseline" / "release-v2.json"
    staged_profile = stage / "payload" / "trust" / "update-profile-v1.json"
    assert staged_envelope.exists(), "baseline/release-v2.json must be staged"
    assert staged_profile.exists(), "trust/update-profile-v1.json must be staged"

    assert staged_envelope.read_bytes() == envelope_path.read_bytes(), "staged envelope must be byte-identical"
    assert staged_profile.read_bytes() == profile_path.read_bytes(), "staged trust profile must be byte-identical"

    record_path = stage / "out" / "build-record.json"
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert record["embedded_envelope_sha256"] == _digest(envelope_path.read_bytes())
    assert record["embedded_trust_profile_sha256"] == _digest(profile_path.read_bytes())
    assert record["profile_id"] == "proof-v512"
    assert "keyset_sha256" in record
    assert len(record["keyset_sha256"]) == 64


def test_builder_rejects_untrusted_profile_authority_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    profile_path, envelope_path, _ = _make_keys_and_files(tmp_path)

    other_priv = Ed25519PrivateKey.generate()
    other_pub = other_priv.public_key().public_bytes_raw()
    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        monkeypatch.setattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS", {"other-key": other_pub})

    iscc_called = False

    def forbidden_find_iscc() -> str:
        nonlocal iscc_called
        iscc_called = True
        raise AssertionError("find_iscc reached on untrusted profile")

    monkeypatch.setattr(module, "find_iscc", forbidden_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0})())

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater")) + [
        "--baseline-envelope",
        str(envelope_path),
        "--trust-profile",
        str(profile_path),
    ]
    with pytest.raises((getattr(module, "PrebuildGateError", ValueError), ValueError)):
        build_candidate(parse_args(argv))
    assert not iscc_called


def test_builder_rejects_one_byte_tampered_trust_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    profile_path, envelope_path, auth_keys = _make_keys_and_files(tmp_path)

    raw_prof = bytearray(profile_path.read_bytes())
    raw_prof[len(raw_prof) // 2] ^= 0x01
    profile_path.write_bytes(bytes(raw_prof))

    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        monkeypatch.setattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)

    iscc_called = False

    def forbidden_find_iscc() -> str:
        nonlocal iscc_called
        iscc_called = True
        raise AssertionError("find_iscc reached on tampered profile")

    monkeypatch.setattr(module, "find_iscc", forbidden_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0})())

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater")) + [
        "--baseline-envelope",
        str(envelope_path),
        "--trust-profile",
        str(profile_path),
    ]
    with pytest.raises((getattr(module, "PrebuildGateError", ValueError), ValueError)):
        build_candidate(parse_args(argv))
    assert not iscc_called


def test_builder_rejects_one_byte_tampered_baseline_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    profile_path, envelope_path, auth_keys = _make_keys_and_files(tmp_path)

    raw_env = bytearray(envelope_path.read_bytes())
    raw_env[len(raw_env) // 2] ^= 0x01
    envelope_path.write_bytes(bytes(raw_env))

    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        monkeypatch.setattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)

    iscc_called = False

    def forbidden_find_iscc() -> str:
        nonlocal iscc_called
        iscc_called = True
        raise AssertionError("find_iscc reached on tampered envelope")

    monkeypatch.setattr(module, "find_iscc", forbidden_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0})())

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater")) + [
        "--baseline-envelope",
        str(envelope_path),
        "--trust-profile",
        str(profile_path),
    ]
    with pytest.raises((getattr(module, "PrebuildGateError", ValueError), ValueError)):
        build_candidate(parse_args(argv))
    assert not iscc_called


def test_builder_refuses_envelope_with_mismatched_component_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    profile_path, envelope_path, auth_keys = _make_keys_and_files(tmp_path)

    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        monkeypatch.setattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)

    iscc_called = False

    def forbidden_find_iscc() -> str:
        nonlocal iscc_called
        iscc_called = True
        raise AssertionError("find_iscc reached on mismatched component identity")

    monkeypatch.setattr(module, "find_iscc", forbidden_find_iscc)
    monkeypatch.setattr(module, "APPROVED_V2RAY_SHA256", _digest(b"v2ray"))
    monkeypatch.setattr(module, "DOTNET_RUNTIME_SHA256_PIN", _digest(b"dotnet"))
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    # 1. Launcher sha in envelope does not match staged launcher
    doc = valid_v2_release_document(
        sequence=1,
        release_id="rel-0001",
        launcher_sha="f" * 64,
        updater_sha=_digest(b"updater"),
        core_installed_sha=_digest((stage / "payload" / "CoreBundle" / "core-manifest.json").read_bytes()),
    )
    env_dict = signed_envelope(doc, key_id=TEST_REL_KEY_ID, private_key=TEST_REL_PRIV)
    envelope_path.write_bytes(canonical_json_dumps(env_dict) + b"\n")

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater")) + [
        "--baseline-envelope", str(envelope_path),
        "--trust-profile", str(profile_path),
    ]
    with pytest.raises((getattr(module, "PrebuildGateError", ValueError), ValueError)):
        build_candidate(parse_args(argv))
    assert not iscc_called

    # 2. Updater sha in envelope does not match staged updater
    doc2 = valid_v2_release_document(
        sequence=1,
        release_id="rel-0001",
        launcher_sha=_digest(b"launcher"),
        updater_sha="e" * 64,
        core_installed_sha=_digest((stage / "payload" / "CoreBundle" / "core-manifest.json").read_bytes()),
    )
    env_dict2 = signed_envelope(doc2, key_id=TEST_REL_KEY_ID, private_key=TEST_REL_PRIV)
    envelope_path.write_bytes(canonical_json_dumps(env_dict2) + b"\n")
    with pytest.raises((getattr(module, "PrebuildGateError", ValueError), ValueError)):
        build_candidate(parse_args(argv))
    assert not iscc_called

    # 3. Core installed identity in envelope does not match staged core manifest
    doc3 = valid_v2_release_document(
        sequence=1,
        release_id="rel-0001",
        launcher_sha=_digest(b"launcher"),
        updater_sha=_digest(b"updater"),
        core_installed_sha="c" * 64,
    )
    env_dict3 = signed_envelope(doc3, key_id=TEST_REL_KEY_ID, private_key=TEST_REL_PRIV)
    envelope_path.write_bytes(canonical_json_dumps(env_dict3) + b"\n")
    with pytest.raises((getattr(module, "PrebuildGateError", ValueError), ValueError)):
        build_candidate(parse_args(argv))
    assert not iscc_called


def test_builder_refuses_one_byte_difference_between_supplied_and_staged_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    profile_path, envelope_path, auth_keys = _make_keys_and_files(tmp_path)

    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        monkeypatch.setattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)

    iscc_called = False

    def forbidden_find_iscc() -> str:
        nonlocal iscc_called
        iscc_called = True
        raise AssertionError("find_iscc reached on tampered staged envelope")

    monkeypatch.setattr(module, "find_iscc", forbidden_find_iscc)
    monkeypatch.setattr(module, "APPROVED_V2RAY_SHA256", _digest(b"v2ray"))
    monkeypatch.setattr(module, "DOTNET_RUNTIME_SHA256_PIN", _digest(b"dotnet"))
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    real_open = open

    def fake_open(file, mode="r", *args, **kwargs):
        fh = real_open(file, mode, *args, **kwargs)
        if "baseline" in str(file) and "release-v2.json" in str(file) and "w" in mode:
            class TamperingWriter:
                def __init__(self, target):
                    self._target = target
                def write(self, data):
                    tampered = bytearray(data)
                    tampered[len(tampered) // 2] ^= 0x01
                    return self._target.write(bytes(tampered))
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return self._target.__exit__(*a)
            return TamperingWriter(fh)
        return fh

    monkeypatch.setattr("builtins.open", fake_open)

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater")) + [
        "--baseline-envelope", str(envelope_path),
        "--trust-profile", str(profile_path),
    ]
    with pytest.raises((getattr(module, "PrebuildGateError", ValueError), ValueError)):
        build_candidate(parse_args(argv))
    assert not iscc_called


def test_builder_record_contains_exact_envelope_provenance_and_verifies_key_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_builder()
    parse_args, build_candidate = _candidate_api(module)
    stage = _stage(tmp_path)
    profile_path, envelope_path, auth_keys = _make_keys_and_files(tmp_path)

    if hasattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS"):
        monkeypatch.setattr(module, "PROFILE_AUTHORITY_PUBLIC_KEYS", auth_keys)

    def mock_find_iscc() -> str:
        return "mock_iscc.exe"

    def mock_subprocess_run(args, **kwargs) -> Any:
        if args and args[0] == "mock_iscc.exe":
            out_dir = stage / "out"
            out_dir.mkdir(exist_ok=True)
            (out_dir / "NekoFamilyProxy-Installer.exe").write_bytes(b"mock_installer")
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(module, "APPROVED_V2RAY_SHA256", _digest(b"v2ray"))
    monkeypatch.setattr(module, "DOTNET_RUNTIME_SHA256_PIN", _digest(b"dotnet"))
    monkeypatch.setattr(module, "find_iscc", mock_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", mock_subprocess_run)

    argv = _argv(stage, _digest(b"launcher"), _digest(b"updater")) + [
        "--baseline-envelope", str(envelope_path),
        "--trust-profile", str(profile_path),
    ]

    ret = build_candidate(parse_args(argv))
    assert ret == 0

    record_path = stage / "out" / "build-record.json"
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert record["embedded_envelope_sha256"] == _digest(envelope_path.read_bytes())
    assert record["envelope_sha256"] == record["embedded_envelope_sha256"]
    assert record["key_id"] == TEST_REL_KEY_ID
    assert record["sequence"] == 1
    assert record["release_id"] == "rel-0001"
    assert "payload_sha256" in record
    assert len(record["payload_sha256"]) == 64

    # Independently re-verify the embedded envelope and require its verified key_id to equal record["key_id"]
    from neko_launcher.updater.canonical_json import canonical_json_loads
    from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
    from neko_launcher.updater.trust_profile import verify_update_trust_profile

    staged_envelope_path = stage / "payload" / "baseline" / "release-v2.json"
    staged_profile_path = stage / "payload" / "trust" / "update-profile-v1.json"
    re_verified_profile = verify_update_trust_profile(
        staged_profile_path.read_bytes(),
        profile_authority_public_keys=auth_keys,
    )
    re_verified_doc = canonical_json_loads(staged_envelope_path.read_bytes().strip())
    re_verified_set, re_verified_payload_sha = verify_release_envelope_v2(
        re_verified_doc,
        dict(re_verified_profile.release_public_keys),
    )
    assert re_verified_doc["key_id"] == record["key_id"]
    assert re_verified_set.release_sequence == record["sequence"]
    assert re_verified_set.release_id == record["release_id"]
    assert re_verified_payload_sha == record["payload_sha256"]


def test_builder_rejects_unsigned_provenance_flags(tmp_path: Path) -> None:
    module = _load_builder()
    parse_args, _ = _candidate_api(module)
    stage = _stage(tmp_path)
    with pytest.raises(SystemExit):
        parse_args(_argv(stage) + ["--sequence", "1"])
    with pytest.raises(SystemExit):
        parse_args(_argv(stage) + ["--key-id", "some-key"])
    with pytest.raises(SystemExit):
        parse_args(_argv(stage) + ["--release-id", "stable-0001"])
