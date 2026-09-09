from __future__ import annotations

from pathlib import Path
import re

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def publication_job_text() -> str:
    text = workflow_text()
    lines = text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        if re.match(r"^  publish-release:\s*$", line):
            start_idx = idx
            break
    assert start_idx is not None, "release.yml must contain a publish-release job"
    block = [lines[start_idx]]
    for line in lines[start_idx + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= 2:
            break
        block.append(line)
    return "\n".join(block)


def test_publication_stages_and_uploads_four_required_assets() -> None:
    job = publication_job_text()
    required_assets = [
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
        "release-v2.json",
    ]
    upload_match = re.search(r"(?i)\bgh\s+release\s+upload\b[^\n]+", job)
    assert upload_match is not None, "publish-release job must contain a gh release upload command"
    upload_command = upload_match.group(0)

    for asset in required_assets:
        assert asset in upload_command, (
            f"gh release upload command must include required asset {asset!r}"
        )


def test_publication_upload_step_disables_clobber() -> None:
    job = publication_job_text()
    upload_match = re.search(r"(?i)\bgh\s+release\s+upload\b[^\n]+", job)
    assert upload_match is not None, "publish-release job must contain a gh release upload command"
    upload_command = upload_match.group(0)

    assert "--clobber" not in upload_command or "--clobber=false" in upload_command, (
        "gh release upload must not overwrite assets with --clobber enabled"
    )


def test_draft_release_read_back_by_release_id() -> None:
    job = publication_job_text()
    readback_match = re.search(
        r"repos/\$env:GH_REPO/releases/(\$releaseId|\$\{releaseId\}|\$id|\$\{id\})",
        job,
    )
    assert readback_match is not None, (
        "publish-release job must read back draft release by immutable release ID"
    )


def test_verifier_invoked_with_require_draft_flag() -> None:
    job = publication_job_text()
    verifier_match = re.search(
        r"scripts/verify_github_release_assets\.py\b[^\n]*--require-draft",
        job,
        re.DOTALL,
    )
    if not verifier_match:
        verifier_match = re.search(
            r"scripts[/\\]verify_github_release_assets\.py",
            job,
        )
        assert verifier_match is not None and "--require-draft" in job, (
            "scripts/verify_github_release_assets.py must be invoked with --require-draft"
        )


def test_post_publication_readback_uses_same_id_and_verifies_binding() -> None:
    job = publication_job_text()
    publish_idx = job.find("--method PATCH")
    assert publish_idx != -1, "GitHub API release PATCH must be present"
    post_job = job[publish_idx:]

    assert 'releases/$env:RELEASE_ID' in post_job
    assert "releases/tags/" not in post_job and "releases/latest" not in post_job
    for binding in (".id", ".draft", ".tag_name"):
        assert binding in post_job, f"post-publication readback must verify {binding}"


def test_no_synthetic_core_or_secret_signing_in_workflow() -> None:
    text = workflow_text()
    assert "build_software_release_v2.py" not in text, (
        "release.yml must not run local release signing with repository secrets"
    )
    assert not re.search(r"\bCompress-Archive\b[^\n]*NekoProxyCore\.zip", text, re.IGNORECASE), (
        "release.yml must not assemble a synthetic fake NekoProxyCore.zip"
    )


def test_workflow_rejects_source_archive_consumption() -> None:
    text = workflow_text()
    for forbidden in ("zipball_url", "tarball_url", "/archive/refs/"):
        assert forbidden not in text, f"release.yml must not consume source archive {forbidden!r}"


def test_publication_provisions_verifier_runtime_before_cli() -> None:
    job = publication_job_text()
    install_idx = job.find('python -m pip install -e ".\\launcher[release]"')
    verify_idx = job.find("scripts/verify_github_release_assets.py")
    assert install_idx != -1, "isolated publication job must install launcher release dependencies"
    assert verify_idx != -1 and install_idx < verify_idx, (
        "verifier runtime must be provisioned before invoking its CLI"
    )


def test_release_public_key_is_explicit_required_input_without_fallback() -> None:
    text = workflow_text()
    input_match = re.search(
        r"(?ms)^      release_public_key_path:\s*$.*?(?=^      [a-z_]+:|^  push:)",
        text,
    )
    assert input_match is not None
    assert re.search(r"(?m)^        required:\s*true\s*$", input_match.group(0))
    assert "neko-update-prod-1.pub" not in text
    assert "Test-Path $env:PUBLIC_KEY_PATH -PathType Leaf" in text


def test_required_assets_are_downloaded_by_same_release_asset_id_to_remote_directory() -> None:
    job = publication_job_text()
    assert "release/remote-verification" in job
    assert "repos/$env:GH_REPO/releases/assets/$assetId" in job
    assert "Accept: application/octet-stream" in job
    assert "browser_download_url" not in job
    assert re.search(r"foreach \(\$requiredName in \$requiredAssetNames\)", job)
    assert "--download-dir release/remote-verification" in job


def test_remote_download_selection_requires_four_names_once_and_ignores_extras() -> None:
    job = publication_job_text()
    for name in ("NekoLauncher.exe", "NekoUpdater.exe", "NekoProxyCore.zip", "release-v2.json"):
        assert name in job
    assert "$matches = @($release.assets | Where-Object { $_.name -ceq $requiredName })" in job
    assert "$matches.Count -ne 1" in job
    assert "foreach ($asset in $release.assets)" not in job


def test_publish_is_after_remote_byte_verification() -> None:
    job = publication_job_text()
    download_idx = job.find("releases/assets/$assetId")
    verify_idx = job.find("scripts/verify_github_release_assets.py")
    publish_idx = job.find("--draft=false")
    assert -1 not in (download_idx, verify_idx, publish_idx)
    assert download_idx < verify_idx < publish_idx
    assert "--download-dir release/remote-verification" in job
    assert "--download-dir release `" not in job
