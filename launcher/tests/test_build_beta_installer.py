from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "installer" / "scripts" / "build_beta_installer.py"
HEX_A = "a" * 64
HEX_B = "b" * 64
CORE_AUTHORITY = "operator-approved-core-authority"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("phase3_build_beta_installer", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _candidate_api(module: ModuleType) -> tuple[Any, Any]:
    parse_args = getattr(module, "parse_args", None)
    build_candidate = getattr(module, "build_candidate", None)
    assert callable(parse_args), "candidate builder must expose parse_args(argv)"
    assert callable(build_candidate), "candidate builder must expose build_candidate(args)"
    return parse_args, build_candidate


def _argv(stage: Path, launcher_hash: str = HEX_A, updater_hash: str = HEX_B) -> list[str]:
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
    (core / "core-manifest.json").write_text(
        '{"source_commit": "' + CORE_AUTHORITY + '", "files": {}, '
        '"v2ray_sn_exe_hash": "' + _digest(b"v2ray") + '"}',
        encoding="utf-8",
    )
    (prereqs / "windowsdesktop-runtime-6.0.36-win-x64.exe").write_bytes(b"dotnet")
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
    assert "OutputBaseFilename=NekoFamilyProxy-Setup" in iss_text, "Output exactly NekoFamilyProxy-Setup.exe"
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
        "files": {
            "bin/v2ray-sn.exe": v2ray_hash,
        },
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
        "files": {
            "bin/v2ray-sn.exe": v2ray_hash,
        },
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
            (out_dir / "NekoFamilyProxy-Setup.exe").write_bytes(b"mock_installer")
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if args and str(args[0]).endswith("NekoUpdater.exe"):
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        return real_subprocess_run(args, **kwargs)

    monkeypatch.setattr(module, "APPROVED_V2RAY_SHA256", v2ray_hash)
    monkeypatch.setattr(module, "DOTNET_RUNTIME_SHA256_PIN", _digest(b"dotnet"))
    monkeypatch.setattr(module, "find_iscc", mock_find_iscc)
    monkeypatch.setattr(module.subprocess, "run", mock_subprocess_run)

    argv = [
        "--candidate-dir",
        str(stage),
        "--launcher-sha256",
        _digest(b"launcher"),
        "--updater-sha256",
        _digest(b"updater"),
        "--core-authority",
        candidate_authority,
        "--release-version",
        "5.1.3",
    ]

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
            (out_dir / "NekoFamilyProxy-Setup.exe").write_bytes(b"mock_installer")
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
    assert record["installer_file"] == "NekoFamilyProxy-Setup.exe"
