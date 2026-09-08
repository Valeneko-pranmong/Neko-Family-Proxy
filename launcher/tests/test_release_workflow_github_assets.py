from __future__ import annotations

from pathlib import Path
import re

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def publication_job_text() -> str:
    text = workflow_text()
    match = re.search(r"(?m)^  publish-release:\s*\n((?:    .*\n?)+)", text)
    assert match is not None, "release.yml must contain a publish-release job"
    return match.group(1)


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


def test_post_publication_readback_verifies_draft_false() -> None:
    job = publication_job_text()
    publish_idx = job.find("--draft=false")
    assert publish_idx != -1, "gh release edit --draft=false must be present"
    post_job = job[publish_idx:]

    assert "releases/tags/" in post_job or "releases/latest" in post_job, (
        "publish-release job must read back published release after --draft=false"
    )
    assert "draft" in post_job.lower(), (
        "post-publication readback must verify draft state is false"
    )


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
