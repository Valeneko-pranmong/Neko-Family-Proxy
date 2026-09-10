from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
REQUIRED_ASSETS = (
    "NekoFamilyProxy-Setup.exe",
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)
RELEASE_ID = "987654"
RELEASE_TAG = "v5.1.3"
EXPECTED_TARGET = "a" * 40


def publication_job_text() -> str:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^  staged-verification:\s*$.*?(?=^  [a-zA-Z0-9_-]+:\s*$|\Z)", text)
    assert match is not None
    return match.group(0)


def workflow_step_run(name: str) -> str:
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    marker = f"      - name: {name}"
    start = lines.index(marker)
    run_index = next(i for i in range(start + 1, len(lines)) if lines[i] == "        run: |" or lines[i].startswith("        run: "))
    if lines[run_index] == "        run: |":
        body: list[str] = []
        for line in lines[run_index + 1 :]:
            if line and not line.startswith("          "):
                break
            body.append(line[10:] if line else "")
        assert body
        return "\n".join(body)
    return lines[run_index][13:]


def test_noncanonical_repository_is_rejected_before_first_release_api(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh_log = tmp_path / "gh.log"
    fake_gh = fake_bin / "gh.cmd"
    fake_gh.write_text(f'@echo called>>"{gh_log}"\r\n', encoding="utf-8")
    script_path = tmp_path / "canonical-guard.ps1"
    script_path.write_text(
        workflow_step_run("Validate transitional publication authority inputs locally"),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "GH_REPO": "copied-owner/Neko-Family-Proxy",
            "RELEASE_ID": RELEASE_ID,
            "RELEASE_TAG": RELEASE_TAG,
            "EXPECTED_TARGET": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
        }
    )
    result = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "canonical repository" in (result.stdout + result.stderr).lower()
    assert not gh_log.exists(), "canonical guard must fail before any gh invocation"


def test_fetches_staged_prerelease_by_numeric_release_id_and_locks_initial_bindings() -> None:
    job = publication_job_text()
    assert 'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"' in job
    for assertion in (
        "[string]$release.id -ne [string]$env:RELEASE_ID",
        "$release.draft -ne $false",
        "$release.prerelease -ne $true",
        "$release.tag_name -cne $env:RELEASE_TAG",
        "$release.target_commitish.ToLowerInvariant() -ne $env:EXPECTED_TARGET.ToLowerInvariant()",
    ):
        assert assertion in job
    assert "release/metadata/draft-release.json" in job
    assert "$initialAssetBindings = @{}" in job
    assert "$matches.Count -ne 1" in job
    assert "$initialAssetBindings[$requiredName] = $assetId" in job


def test_downloads_exact_required_assets_by_id_as_raw_nonempty_bytes() -> None:
    job = publication_job_text()
    for name in REQUIRED_ASSETS:
        assert name in job
    assert 'ArgumentList.Add("repos/$env:GH_REPO/releases/assets/$assetId")' in job
    assert 'ArgumentList.Add("Accept: application/octet-stream")' in job
    assert '[System.IO.File]::Create("release/remote-verification/$requiredName")' in job
    stderr_start = "$stderrTask = $process.StandardError.ReadToEndAsync()"
    stdout_copy = "$process.StandardOutput.BaseStream.CopyTo($outputStream)"
    wait_for_exit = "$process.WaitForExit()"
    stderr_result = "$errorText = $stderrTask.GetAwaiter().GetResult()"
    assert job.index(stderr_start) < job.index(stdout_copy) < job.index(wait_for_exit) < job.index(stderr_result)
    assert "$process.StandardError.ReadToEnd()" not in job
    assert ".ExitCode -ne 0" in job
    assert ".Length -le 0" in job
    assert "browser_download_url" not in job


def test_verifier_uses_repository_authority_and_requires_prerelease() -> None:
    job = publication_job_text()
    for expected in (
        "scripts/verify_github_release_assets.py",
        "--release-json release/metadata/draft-release.json",
        "--download-dir release/remote-verification",
        '--expected-tag "$env:RELEASE_TAG"',
        '--expected-target "$env:EXPECTED_TARGET"',
        "--require-prerelease",
    ):
        assert expected in job
    assert "--public-key" not in job
    assert "--trusted-key-id" not in job


def test_verifies_negative_resolution_for_latest() -> None:
    job = publication_job_text()
    assert "Verify negative resolution for latest" in job
    assert 'gh api "repos/$env:GH_REPO/releases/latest"' in job
    assert 'throw "Latest release unexpectedly resolved to staged prerelease ID."' in job


def test_publication_job_neither_builds_uploads_nor_signs_assets() -> None:
    job = publication_job_text().lower()
    for forbidden in (
        "pyinstaller",
        "gh release create",
        "gh release upload",
        "build_software_release_v2.py",
        "private key",
    ):
        assert forbidden not in job
