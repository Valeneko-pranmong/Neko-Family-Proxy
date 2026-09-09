from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
REQUIRED_ASSETS = (
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)
RELEASE_ID = "987654"
RELEASE_TAG = "v5.1.0"
EXPECTED_TARGET = "a" * 40


def publication_job_text() -> str:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^  publish-release:\s*$.*?(?=^  [a-zA-Z0-9_-]+:\s*$|\Z)", text)
    assert match is not None
    return match.group(0)


def workflow_step_run(name: str) -> str:
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    marker = f"      - name: {name}"
    start = lines.index(marker)
    run_index = next(i for i in range(start + 1, len(lines)) if lines[i] == "        run: |")
    body: list[str] = []
    for line in lines[run_index + 1 :]:
        if line and not line.startswith("          "):
            break
        body.append(line[10:] if line else "")
    assert body
    return "\n".join(body)


def release_payload(*, draft: bool, release_id: str = RELEASE_ID, tag: str = RELEASE_TAG) -> dict:
    return {
        "id": int(release_id),
        "draft": draft,
        "prerelease": False,
        "tag_name": tag,
        "target_commitish": EXPECTED_TARGET,
        "assets": [
            {"id": index + 101, "name": name, "size": (index + 1) * 100}
            for index, name in enumerate(REQUIRED_ASSETS)
        ],
    }


@pytest.fixture
def publication_harness(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    fake_bin = tmp_path / "bin"
    metadata = tmp_path / "release" / "metadata"
    fake_bin.mkdir()
    metadata.mkdir(parents=True)
    bindings = {name: index + 101 for index, name in enumerate(REQUIRED_ASSETS)}
    (metadata / "initial-asset-bindings.json").write_text(json.dumps(bindings), encoding="utf-8")

    fake_gh = fake_bin / "fake_gh.py"
    fake_gh.write_text(
        """import json, os, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ['FAKE_GH_LOG'])
with log.open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(args) + '\\n')
endpoint = args[1] if len(args) > 1 and args[0] == 'api' else ''
state_path = Path(os.environ['FAKE_GH_STATE'])
state = json.loads(state_path.read_text()) if state_path.exists() else {'id_gets': 0, 'latest': 0}
base = json.loads(os.environ['FAKE_RELEASE_JSON'])
if '--method' in args:
    valid = endpoint.endswith('/' + os.environ['RELEASE_ID']) and '-F' in args and 'draft=false' in args and '-f' in args and 'make_latest=true' in args
    if not valid:
        print('invalid PATCH typing or target', file=sys.stderr)
        sys.exit(42)
    print(json.dumps(base))
elif endpoint.endswith('/latest'):
    state['latest'] += 1
    result = dict(base)
    if state['latest'] < int(os.environ['FAKE_MATCH_AT']):
        result['id'] = 111
        result['tag_name'] = 'v0.0.1'
    print(json.dumps(result))
elif endpoint.endswith('/' + os.environ['RELEASE_ID']):
    state['id_gets'] += 1
    result = dict(base)
    result['draft'] = state['id_gets'] == 1
    print(json.dumps(result))
else:
    print('unexpected endpoint: ' + endpoint, file=sys.stderr)
    sys.exit(43)
state_path.write_text(json.dumps(state))
""",
        encoding="utf-8",
    )
    (fake_bin / "gh.cmd").write_text(f'@python "{fake_gh}" %*\r\n', encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "GH_REPO": "owner/repository",
            "RELEASE_ID": RELEASE_ID,
            "RELEASE_TAG": RELEASE_TAG,
            "EXPECTED_TARGET": EXPECTED_TARGET,
            "FAKE_GH_LOG": str(tmp_path / "gh.log"),
            "FAKE_GH_STATE": str(tmp_path / "state.json"),
            "FAKE_RELEASE_JSON": json.dumps(release_payload(draft=False)),
        }
    )
    return tmp_path, env


def run_publication_harness(tmp_path: Path, env: dict[str, str], match_at: int) -> subprocess.CompletedProcess[str]:
    env["FAKE_MATCH_AT"] = str(match_at)
    script = "\n".join(
        (
            "function Start-Sleep { param([int]$Seconds) Add-Content -Path $env:FAKE_SLEEP_LOG -Value $Seconds }",
            workflow_step_run("Revalidate bindings and publish by immutable ID"),
            workflow_step_run("Verify published release and latest resolution"),
        )
    )
    env["FAKE_SLEEP_LOG"] = str(tmp_path / "sleep.log")
    script_path = tmp_path / "harness.ps1"
    script_path.write_text(script, encoding="utf-8")
    return subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def invocation_log(tmp_path: Path) -> list[list[str]]:
    return [json.loads(line) for line in (tmp_path / "gh.log").read_text(encoding="utf-8").splitlines()]


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


def test_fetches_draft_by_numeric_release_id_and_locks_initial_bindings() -> None:
    job = publication_job_text()
    assert 'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"' in job
    for assertion in (
        "[string]$release.id -ne [string]$env:RELEASE_ID",
        "$release.draft -ne $true",
        "$release.prerelease -ne $false",
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


def test_verifier_uses_repository_authority_and_requires_draft() -> None:
    job = publication_job_text()
    for expected in (
        "scripts/verify_github_release_assets.py",
        "--release-json release/metadata/draft-release.json",
        "--download-dir release/remote-verification",
        '--expected-tag "$env:RELEASE_TAG"',
        '--expected-target "$env:EXPECTED_TARGET"',
        "--require-draft",
    ):
        assert expected in job
    assert "--public-key" not in job
    assert "--trusted-key-id" not in job


def test_revalidates_same_draft_and_asset_ids_before_patch() -> None:
    job = publication_job_text()
    between = job[job.index("scripts/verify_github_release_assets.py") : job.index("--method PATCH")]
    assert 'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"' in between
    assert "$current.draft -ne $true" in between
    assert "$current.prerelease -ne $false" in between
    assert "[string]$current.id -ne [string]$env:RELEASE_ID" in between
    assert "$currentMatches[0].id -ne $initialAssetBindings[$requiredName]" in between


def test_publishes_typed_draft_false_only_by_immutable_release_id() -> None:
    job = publication_job_text()
    expected = (
        'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID" '
        "--method PATCH -F draft=false -f make_latest=true"
    )
    assert expected in job
    assert job.index("scripts/verify_github_release_assets.py") < job.index(expected)
    assert "releases/tags/" not in job
    assert "gh release create" not in job
    assert "gh release upload" not in job


def test_behavior_patch_and_stale_latest_eventually_match(publication_harness: tuple[Path, dict[str, str]]) -> None:
    tmp_path, env = publication_harness
    result = run_publication_harness(tmp_path, env, match_at=3)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = invocation_log(tmp_path)
    patch = [call for call in calls if "--method" in call]
    assert patch == [["api", f"repos/owner/repository/releases/{RELEASE_ID}", "--method", "PATCH", "-F", "draft=false", "-f", "make_latest=true"]]
    latest = [call for call in calls if call[1].endswith("/latest")]
    assert len(latest) == 3
    assert (tmp_path / "sleep.log").read_text(encoding="utf-8").splitlines() == ["1", "2"]


def test_behavior_latest_exhaustion_fails_closed_at_bound(publication_harness: tuple[Path, dict[str, str]]) -> None:
    tmp_path, env = publication_harness
    result = run_publication_harness(tmp_path, env, match_at=99)
    assert result.returncode != 0
    assert "Latest release identity mismatch after bounded retries." in result.stderr
    calls = invocation_log(tmp_path)
    assert len([call for call in calls if call[1].endswith("/latest")]) == 5
    assert (tmp_path / "sleep.log").read_text(encoding="utf-8").splitlines() == ["1", "2", "3", "4"]


def test_post_publish_same_id_and_latest_preserve_state_and_bindings() -> None:
    job = publication_job_text()
    post = job[job.index("--method PATCH") :]
    for expected in (
        'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"',
        "$published.draft -ne $false",
        "$published.prerelease -ne $false",
        "$publishedMatches[0].id -ne $initialAssetBindings[$requiredName]",
        'gh api "repos/$env:GH_REPO/releases/latest"',
        "[string]$latest.id -ne [string]$env:RELEASE_ID",
        "$latest.draft -ne $false",
        "$latest.prerelease -ne $false",
        "$latest.tag_name -cne $env:RELEASE_TAG",
        "$latest.target_commitish.ToLowerInvariant() -ne $env:EXPECTED_TARGET.ToLowerInvariant()",
        "$latestMatches[0].id -ne $initialAssetBindings[$requiredName]",
        "$latestMatches[0].size -ne $publishedMatches[0].size",
    ):
        assert expected in post


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
