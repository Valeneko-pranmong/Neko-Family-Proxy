from __future__ import annotations

from pathlib import Path
import re

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
REQUIRED_ASSETS = (
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)


def publication_job_text() -> str:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^  publish-release:\s*$.*?(?=^  [a-zA-Z0-9_-]+:\s*$|\Z)", text)
    assert match is not None
    return match.group(0)


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
    assert stderr_start in job
    assert stdout_copy in job
    assert wait_for_exit in job
    assert stderr_result in job
    assert job.index(stderr_start) < job.index(stdout_copy)
    assert job.index(stdout_copy) < job.index(wait_for_exit)
    assert job.index(wait_for_exit) < job.index(stderr_result)
    assert "$process.StandardError.ReadToEnd()" not in job
    assert ".ExitCode -ne 0" in job
    assert ".Length -le 0" in job
    assert "browser_download_url" not in job


def test_verifier_uses_repository_authority_and_requires_draft() -> None:
    job = publication_job_text()
    assert "scripts/verify_github_release_assets.py" in job
    assert "--release-json release/metadata/draft-release.json" in job
    assert "--download-dir release/remote-verification" in job
    assert '--expected-tag "$env:RELEASE_TAG"' in job
    assert '--expected-target "$env:EXPECTED_TARGET"' in job
    assert "--require-draft" in job
    assert "--public-key" not in job
    assert "--trusted-key-id" not in job


def test_revalidates_same_draft_and_asset_ids_before_patch() -> None:
    job = publication_job_text()
    verify_index = job.index("scripts/verify_github_release_assets.py")
    patch_index = job.index("--method PATCH")
    between = job[verify_index:patch_index]
    assert 'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"' in between
    assert "$current.draft -ne $true" in between
    assert "$current.prerelease -ne $false" in between
    assert "[string]$current.id -ne [string]$env:RELEASE_ID" in between
    assert "$currentMatches[0].id -ne $initialAssetBindings[$requiredName]" in between


def test_publishes_only_by_immutable_release_id_after_verification() -> None:
    job = publication_job_text()
    expected = 'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID" --method PATCH -f draft=false'
    assert expected in job
    assert job.index("scripts/verify_github_release_assets.py") < job.index(expected)
    assert "releases/tags/" not in job
    assert "gh release create" not in job
    assert "gh release upload" not in job


def test_post_publish_same_id_and_latest_preserve_state_and_bindings() -> None:
    job = publication_job_text()
    post = job[job.index("--method PATCH") :]
    assert 'gh api "repos/$env:GH_REPO/releases/$env:RELEASE_ID"' in post
    assert "$published.draft -ne $false" in post
    assert "$published.prerelease -ne $false" in post
    assert "$publishedMatches[0].id -ne $initialAssetBindings[$requiredName]" in post
    assert 'gh api "repos/$env:GH_REPO/releases/latest"' in post
    assert "[string]$latest.id -ne [string]$env:RELEASE_ID" in post
    assert "$latest.draft -ne $false" in post
    assert "$latest.prerelease -ne $false" in post
    assert "$latest.tag_name -cne $env:RELEASE_TAG" in post
    assert "$latest.target_commitish.ToLowerInvariant() -ne $env:EXPECTED_TARGET.ToLowerInvariant()" in post
    assert "$latestMatches[0].id -ne $initialAssetBindings[$requiredName]" in post
    assert "$latestMatches[0].size -ne $publishedMatches[0].size" in post


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
