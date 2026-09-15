from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Protocol, Sequence

try:
    from scripts.project_release_audit_ledger import (
        EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
        VERIFIED_DELETED_RESULT,
        ReleaseAuditEvent,
        validate_release_audit_event,
        verify_release_audit_ledger,
    )
    from scripts.verify_human_release_assets import (
        CANONICAL_HUMAN_REPO,
        FORBIDDEN_HUMAN_ASSETS,
        REQUIRED_HUMAN_ASSET,
        REQUIRED_HUMAN_ASSETS,
        HumanReleaseVerificationError,
        validate_human_release_body,
        verify_human_release_assets,
    )
except ModuleNotFoundError:
    from project_release_audit_ledger import (  # type: ignore[no-redef]
        EVENT_TYPE_INSTALLER_REPOSITORY_DELETED,
        VERIFIED_DELETED_RESULT,
        ReleaseAuditEvent,
        validate_release_audit_event,
        verify_release_audit_ledger,
    )
    from verify_human_release_assets import (  # type: ignore[no-redef]
        CANONICAL_HUMAN_REPO,
        FORBIDDEN_HUMAN_ASSETS,
        REQUIRED_HUMAN_ASSET,
        REQUIRED_HUMAN_ASSETS,
        HumanReleaseVerificationError,
        validate_human_release_body,
        verify_human_release_assets,
    )

__all__ = [
    "CANONICAL_HUMAN_REPO",
    "CommandExecutor",
    "FORBIDDEN_HUMAN_ASSETS",
    "HumanPublishError",
    "HumanPublishResult",
    "InstallerPublishError",
    "REQUIRED_HUMAN_ASSET",
    "REQUIRED_HUMAN_ASSETS",
    "main",
    "publish_human_release",
]

_SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class HumanPublishError(Exception):
    """Raised when canonical human release staging, precondition check, or publication fails."""


InstallerPublishError = HumanPublishError


@dataclass(frozen=True)
class HumanPublishResult:
    status: str
    release_id: int | None = None
    tag_name: str = ""
    target_commit: str = ""
    repo: str = ""
    installer_asset_id: int | None = None
    installer_size: int | None = None
    installer_sha256: str = ""
    error: str | None = None


class CommandExecutor(Protocol):
    def run(
        self,
        args: list[str],
        *,
        capture_output: bool = True,
        stdout: Any = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]: ...


class _SubprocessExecutor:
    def run(
        self,
        args: list[str],
        *,
        capture_output: bool = True,
        stdout: Any = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if stdout is not None:
            return subprocess.run(args, stdout=stdout, text=False, check=check)
        return subprocess.run(args, capture_output=capture_output, text=True, check=check)


def _validate_deletion_evidence(evidence: ReleaseAuditEvent | None) -> None:
    """Validate that caller supplied authoritative proof of G22 installer repository deletion."""
    if evidence is None:
        raise HumanPublishError(
            "Publisher refuses to start: deletion evidence must be supplied"
        )
    if not isinstance(evidence, ReleaseAuditEvent):
        raise HumanPublishError(
            f"Publisher refuses to start: expected ReleaseAuditEvent, got {type(evidence).__name__}"
        )

    if evidence.event_type != EVENT_TYPE_INSTALLER_REPOSITORY_DELETED:
        raise HumanPublishError(
            f"Publisher refuses to start: expected event_type {EVENT_TYPE_INSTALLER_REPOSITORY_DELETED!r}, "
            f"got {evidence.event_type!r}"
        )

    ev_dict = evidence.evidence
    if not isinstance(ev_dict, dict):
        raise HumanPublishError("Publisher refuses to start: evidence payload must be a dict")

    result = ev_dict.get("result")
    if result != VERIFIED_DELETED_RESULT:
        raise HumanPublishError(
            f"Publisher refuses to start: expected result {VERIFIED_DELETED_RESULT!r}, got {result!r}"
        )

    try:
        validate_release_audit_event(evidence)
    except Exception as err:
        raise HumanPublishError(
            f"Publisher refuses to start: deletion evidence schema invalid: {err}"
        ) from err


def publish_human_release(
    *,
    tag: str,
    target_commit: str,
    installer_path: Path | str,
    body: str,
    deletion_evidence: ReleaseAuditEvent,
    executor: CommandExecutor | None = None,
    repo: str = CANONICAL_HUMAN_REPO,
    title: str | None = None,
) -> HumanPublishResult:
    """Publish canonical human release from validated draft."""
    # Step 1: Prove G22 deletion-result ledger event was read back as INSTALLER_REPOSITORY_DELETED / VERIFIED_DELETED
    _validate_deletion_evidence(deletion_evidence)

    runner = executor or _SubprocessExecutor()

    # Precondition: validate target commit
    if not isinstance(target_commit, str) or not _SHA40_RE.fullmatch(target_commit.strip()):
        raise HumanPublishError("Target commit must be a 40-character hexadecimal SHA")
    target_commit = target_commit.strip().lower()

    # Precondition: validate tag
    if not isinstance(tag, str) or not tag.strip():
        raise HumanPublishError("Release tag must be a non-empty string")
    tag = tag.strip()

    # Precondition: validate installer asset locally
    inst_path = Path(installer_path)
    if not inst_path.is_file():
        raise HumanPublishError(f"Installer path does not exist or is not a file: {inst_path}")
    if inst_path.name != REQUIRED_HUMAN_ASSET:
        raise HumanPublishError(
            f"Installer file name mismatch: expected {REQUIRED_HUMAN_ASSET!r}, got {inst_path.name!r}"
        )

    installer_bytes = inst_path.read_bytes()
    local_size = len(installer_bytes)
    if local_size <= 0:
        raise HumanPublishError("Installer file is empty")
    local_sha256 = hashlib.sha256(installer_bytes).hexdigest().lower()

    # Step 7: Validate release body contract
    try:
        validate_human_release_body(body, tag=tag)
    except HumanReleaseVerificationError as err:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Release body contract failed: {err}",
        )

    # Step 2: First GitHub Release mutation is draft creation in main repo with draft=true, prerelease=false
    release_title = title or f"Neko Family Proxy {tag}"
    create_cmd = [
        "gh",
        "release",
        "create",
        tag,
        "--target",
        target_commit,
        "--verify-tag",
        "--draft",
        "--prerelease=false",
        "--repo",
        repo,
        "--title",
        release_title,
        "--notes",
        body,
    ]
    res_create = runner.run(create_cmd, capture_output=True)
    if res_create.returncode != 0:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft release creation failed with exit code {res_create.returncode}",
        )

    # Step 3: Exact Installer is uploaded
    upload_cmd = [
        "gh",
        "release",
        "upload",
        tag,
        str(inst_path),
        "--clobber=false",
        "--repo",
        repo,
    ]
    res_upload = runner.run(upload_cmd, capture_output=True)
    if res_upload.returncode != 0:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft asset upload failed with exit code {res_upload.returncode}",
        )

    # Live readback of draft
    discover_cmd = [
        "gh",
        "api",
        f"repos/{repo}/releases?per_page=100",
        "--paginate",
        "--slurp",
    ]
    res_disc = runner.run(discover_cmd, capture_output=True)
    if res_disc.returncode != 0:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft release discovery failed",
        )

    try:
        pages_or_list = json.loads(res_disc.stdout)
        if isinstance(pages_or_list, list) and pages_or_list and isinstance(pages_or_list[0], list):
            all_releases = [r for page in pages_or_list for r in page if isinstance(r, dict)]
        elif isinstance(pages_or_list, list):
            all_releases = [r for r in pages_or_list if isinstance(r, dict)]
        else:
            all_releases = []

        matching_drafts = [
            r
            for r in all_releases
            if r.get("draft") is True
            and r.get("tag_name") == tag
            and isinstance(r.get("target_commitish"), str)
            and r["target_commitish"].lower() == target_commit.lower()
        ]
    except Exception as err:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft discovery returned invalid JSON: {err}",
        )

    if len(matching_drafts) != 1:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft discovery expected exactly 1 draft, found {len(matching_drafts)}",
        )

    release_id = matching_drafts[0].get("id")
    if not isinstance(release_id, int) or release_id <= 0:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Invalid draft release ID",
        )

    # Detailed draft readback
    readback_cmd = ["gh", "api", f"repos/{repo}/releases/{release_id}"]
    res_rb = runner.run(readback_cmd, capture_output=True)
    if res_rb.returncode != 0:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft release readback API call failed",
        )

    try:
        draft_doc = json.loads(res_rb.stdout)
    except Exception as err:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft readback JSON parse failed: {err}",
        )

    # Step 4: Validate draft attributes
    if draft_doc.get("draft") is not True:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft readback shows draft is not true",
        )
    if draft_doc.get("prerelease") is True:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft readback shows prerelease is true",
        )
    if draft_doc.get("tag_name") != tag:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft readback tag mismatch: {draft_doc.get('tag_name')!r} != {tag!r}",
        )
    if str(draft_doc.get("target_commitish", "")).lower() != target_commit.lower():
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft readback target commit mismatch",
        )

    draft_body = draft_doc.get("body", "")
    try:
        validate_human_release_body(draft_body, tag=tag)
    except HumanReleaseVerificationError as err:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft body validation failed: {err}",
        )
    if draft_body.strip() != body.strip():
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft body does not match expected body",
        )

    assets = draft_doc.get("assets")
    if not isinstance(assets, list):
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft assets must be a list",
        )

    # Check forbidden machine assets
    for a in assets:
        if isinstance(a, dict) and a.get("name") in FORBIDDEN_HUMAN_ASSETS:
            return HumanPublishResult(
                status="DRAFT_VALIDATION_FAILED",
                release_id=release_id,
                tag_name=tag,
                target_commit=target_commit,
                repo=repo,
                error=f"Draft contains forbidden machine asset: {a.get('name')}",
            )

    # Exact one asset required
    if len(assets) != 1:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft must contain exactly one asset, found {len(assets)}",
        )

    asset = assets[0]
    if not isinstance(asset, dict):
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft asset entry must be an object",
        )

    if asset.get("name") != REQUIRED_HUMAN_ASSET:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft asset name mismatch: expected {REQUIRED_HUMAN_ASSET!r}, got {asset.get('name')!r}",
        )

    asset_id = asset.get("id")
    asset_size = asset.get("size")
    if not isinstance(asset_id, int) or asset_id <= 0:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Draft asset id is invalid",
        )
    if not isinstance(asset_size, int) or asset_size != local_size:
        return HumanPublishResult(
            status="DRAFT_VALIDATION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Draft asset size mismatch: remote {asset_size} != local {local_size}",
        )

    # Step 8: Hosted asset bytes are re-read/re-hashed through exact RA5 mechanism
    with tempfile.TemporaryDirectory(prefix="neko-human-verify-") as tmpdir:
        tmp_path = Path(tmpdir)
        downloaded_asset = tmp_path / REQUIRED_HUMAN_ASSET
        download_cmd = [
            "gh",
            "api",
            f"repos/{repo}/releases/assets/{asset_id}",
            "-H",
            "Accept: application/octet-stream",
        ]

        with open(downloaded_asset, "wb") as stream:
            try:
                res_dl = runner.run(download_cmd, capture_output=False, stdout=stream)
            except TypeError:
                res_dl = runner.run(download_cmd, capture_output=True)
                if res_dl.stdout:
                    if isinstance(res_dl.stdout, str):
                        stream.write(res_dl.stdout.encode("latin1"))
                    else:
                        stream.write(res_dl.stdout)
            stream.flush()
            os.fsync(stream.fileno())

        if res_dl.returncode != 0:
            return HumanPublishResult(
                status="DRAFT_VALIDATION_FAILED",
                release_id=release_id,
                tag_name=tag,
                target_commit=target_commit,
                repo=repo,
                error="Hosted asset download failed",
            )

        dl_size = downloaded_asset.stat().st_size
        dl_sha256 = hashlib.sha256(downloaded_asset.read_bytes()).hexdigest().lower()

        if dl_size != local_size:
            return HumanPublishResult(
                status="DRAFT_VALIDATION_FAILED",
                release_id=release_id,
                tag_name=tag,
                target_commit=target_commit,
                repo=repo,
                error=f"Hosted asset size mismatch: downloaded {dl_size} != local {local_size}",
            )
        if dl_sha256 != local_sha256:
            return HumanPublishResult(
                status="DRAFT_VALIDATION_FAILED",
                release_id=release_id,
                tag_name=tag,
                target_commit=target_commit,
                repo=repo,
                error=f"Hosted asset digest mismatch: downloaded {dl_sha256} != local {local_sha256}",
            )

        # Re-verify through verify_human_release_assets
        release_json_path = tmp_path / "draft_release.json"
        release_json_path.write_text(json.dumps(draft_doc), encoding="utf-8")
        try:
            verify_human_release_assets(
                release_json_path=release_json_path,
                installer_path=downloaded_asset,
                expected_tag=tag,
                expected_target=target_commit,
                require_draft=True,
                expected_repo=repo,
                expected_body=body,
            )
        except HumanReleaseVerificationError as err:
            return HumanPublishResult(
                status="DRAFT_VALIDATION_FAILED",
                release_id=release_id,
                tag_name=tag,
                target_commit=target_commit,
                repo=repo,
                error=f"Verifier rejected draft: {err}",
            )

    # Step 6: Only after draft validation PASS does publisher issue public promotion
    promote_cmd = [
        "gh",
        "release",
        "edit",
        tag,
        "--draft=false",
        "--repo",
        repo,
    ]
    res_prom = runner.run(promote_cmd, capture_output=True)
    if res_prom.returncode != 0:
        return HumanPublishResult(
            status="PROMOTION_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Public promotion command failed with exit code {res_prom.returncode}",
        )

    # Fresh public readback
    pub_readback_cmd = ["gh", "api", f"repos/{repo}/releases/tags/{tag}"]
    res_pub = runner.run(pub_readback_cmd, capture_output=True)
    if res_pub.returncode != 0:
        pub_readback_cmd = ["gh", "api", f"repos/{repo}/releases/latest"]
        res_pub = runner.run(pub_readback_cmd, capture_output=True)

    if res_pub.returncode != 0:
        return HumanPublishResult(
            status="PUBLIC_READBACK_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Fresh public readback API call failed",
        )

    try:
        pub_doc = json.loads(res_pub.stdout)
    except Exception as err:
        return HumanPublishResult(
            status="PUBLIC_READBACK_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error=f"Fresh public readback JSON parse failed: {err}",
        )

    if pub_doc.get("draft") is not False or pub_doc.get("prerelease") is not False:
        return HumanPublishResult(
            status="PUBLIC_READBACK_FAILED",
            release_id=release_id,
            tag_name=tag,
            target_commit=target_commit,
            repo=repo,
            error="Public readback showed draft or prerelease state not false",
        )

    return HumanPublishResult(
        status="SUCCESS",
        release_id=release_id,
        tag_name=tag,
        target_commit=target_commit,
        repo=repo,
        installer_asset_id=asset_id,
        installer_size=local_size,
        installer_sha256=local_sha256,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish canonical human release from validated draft",
        allow_abbrev=False,
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--installer-path", required=True, type=Path)
    parser.add_argument("--body-file", required=True, type=Path)
    parser.add_argument("--audit-ledger", required=True, type=Path)
    parser.add_argument("--repo", default=CANONICAL_HUMAN_REPO)
    parser.add_argument("--title")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.body_file.is_file():
        print(f"Error: body file not found: {args.body_file}", file=sys.stderr)
        return 1
    body = args.body_file.read_text(encoding="utf-8")

    if not args.audit_ledger.is_file():
        print(f"Error: audit ledger not found: {args.audit_ledger}", file=sys.stderr)
        return 1

    try:
        events = verify_release_audit_ledger(args.audit_ledger)
        deleted_events = [
            e for e in events if e.event_type == EVENT_TYPE_INSTALLER_REPOSITORY_DELETED
        ]
        if not deleted_events:
            print("Error: no INSTALLER_REPOSITORY_DELETED event in audit ledger", file=sys.stderr)
            return 1
        deletion_evidence = deleted_events[-1]
    except Exception as err:
        print(f"Error reading audit ledger: {err}", file=sys.stderr)
        return 1

    try:
        result = publish_human_release(
            tag=args.tag,
            target_commit=args.target_commit,
            installer_path=args.installer_path,
            body=body,
            deletion_evidence=deletion_evidence,
            repo=args.repo,
            title=args.title,
        )
    except HumanPublishError as err:
        safe_msg = re.sub(r"https?://\S+", "<sanitized-url>", str(err))
        print(f"Human release publication error: {safe_msg}", file=sys.stderr)
        return 1

    if result.status != "SUCCESS":
        safe_msg = re.sub(r"https?://\S+", "<sanitized-url>", str(result.error or result.status))
        print(f"Human release publication failed: {result.status} ({safe_msg})", file=sys.stderr)
        return 2

    print(
        f"Successfully published human release {result.tag_name} to {result.repo} "
        f"(release_id={result.release_id}, asset_id={result.installer_asset_id})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
