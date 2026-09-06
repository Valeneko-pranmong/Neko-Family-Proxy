"""Candidate probation runner executing credential-free self-test."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time

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

    # Tkinter probe
    if not skip_tk:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            callbacks_count = 0

            def _cb() -> None:
                nonlocal callbacks_count
                callbacks_count += 1

            root.after(5, _cb)
            root.after(10, _cb)
            root.update()
            time.sleep(0.02)
            root.update()
            root.destroy()
            if callbacks_count < 2:
                return SelfTestResult(
                    passed=False,
                    error_code="SELFTEST_FAILED",
                    reason=f"Tkinter event loop probe serviced only {callbacks_count} callbacks",
                )
        except Exception as err:
            return SelfTestResult(
                passed=False,
                error_code="SELFTEST_FAILED",
                reason=f"Tkinter event loop probe error: {err}",
            )

    return SelfTestResult(passed=True)
