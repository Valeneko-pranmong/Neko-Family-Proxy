"""Candidate probation runner executing credential-free self-test."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess

from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle


@dataclass(frozen=True)
class SelfTestResult:
    passed: bool
    error_code: str | None = None
    reason: str | None = None


def run_probation_self_test(
    generation_dir: Path,
    skip_tk: bool = False,
    core_preflight_timeout_s: float = 30.0,
) -> SelfTestResult:
    """Execute credential-free probation verifying own EXE, Core bundle, Core preflight, and Tk event loop."""
    launcher_exe = generation_dir / "NekoLauncher.exe"
    if not launcher_exe.exists():
        return SelfTestResult(
            passed=False,
            error_code="ARTIFACT_MISSING",
            reason=f"Launcher executable not found at '{launcher_exe}'",
        )

    core_dir = generation_dir / "ProxyCore"
    core_res = verify_canonical_core_bundle(core_dir)
    if not core_res.valid:
        return SelfTestResult(
            passed=False,
            error_code="CORE_INVENTORY_INVALID",
            reason=f"Core verification failed: {core_res.error}",
        )

    # Core preflight execution
    core_exe = core_dir / "NekoProxyCore.exe"
    if not core_exe.is_file():
        return SelfTestResult(
            passed=False,
            error_code="ARTIFACT_MISSING",
            reason="Core executable 'NekoProxyCore.exe' missing",
        )

    try:
        proc = subprocess.Popen(
            [str(core_exe.resolve()), "--update-preflight"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        req = json.dumps({"protocol_version": 1, "generation_id": generation_dir.name}) + "\n"
        try:
            stdout, _ = proc.communicate(input=req, timeout=core_preflight_timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return SelfTestResult(
                passed=False,
                error_code="SELFTEST_FAILED",
                reason="Core preflight execution timed out",
            )
        if proc.returncode != 0:
            return SelfTestResult(
                passed=False,
                error_code="SELFTEST_FAILED",
                reason=f"Core preflight exited with code {proc.returncode}",
            )

        resp = json.loads(stdout.strip())
        if resp.get("result") != "PASS":
            return SelfTestResult(
                passed=False,
                error_code="SELFTEST_FAILED",
                reason=f"Core preflight returned: {resp.get('code')}",
            )
    except Exception as err:
        return SelfTestResult(
            passed=False,
            error_code="SELFTEST_FAILED",
            reason=f"Core preflight execution error: {err}",
        )

    # Probe the candidate launcher's own Tk runtime instead of bundling Tcl/Tk
    # into this helper.
    if not skip_tk:
        try:
            probe = subprocess.run(
                [str(launcher_exe.resolve()), "--tk-self-test"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0,
            )
        except subprocess.TimeoutExpired:
            return SelfTestResult(
                passed=False,
                error_code="SELFTEST_FAILED",
                reason="Launcher Tk self-test timed out",
            )
        except Exception as err:
            return SelfTestResult(
                passed=False,
                error_code="SELFTEST_FAILED",
                reason=f"Launcher Tk self-test error: {err}",
            )
        if probe.returncode != 0:
            return SelfTestResult(
                passed=False,
                error_code="SELFTEST_FAILED",
                reason=f"Launcher Tk self-test exited with code {probe.returncode}",
            )

    return SelfTestResult(passed=True)
