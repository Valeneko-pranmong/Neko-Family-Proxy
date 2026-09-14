from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Literal, Protocol, runtime_checkable

from scripts.project_release_audit_ledger import (
    ArtifactCustodyEvidence,
    QUALIFICATION_STATUS_KNOWN_BROKEN,
)

HISTORICAL_INSTALLER_NAME = "NekoFamilyProxy-Installer.exe"
HISTORICAL_INSTALLER_SIZE = 212293271
HISTORICAL_INSTALLER_SHA256 = "e069aa2b268d134ca16d038bef58c176d237e01201e638c63e07f5832803e3f7"
HISTORICAL_VERIFIER_PATH = "installer/scripts/verify-core-install.ps1"
HISTORICAL_FAILURE_EXIT_CODE = 6
BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE = "FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE"

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class ForensicCaptureError(ValueError):
    """Base error for repository forensic capture operations."""


class ForensicArtifactCustodyIncompleteError(ForensicCaptureError):
    """Artifact custody verification failure or mismatch (FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE)."""

    def __init__(self, message: str = BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE) -> None:
        if BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE not in message:
            message = f"{message} ({BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE})"
        super().__init__(message)
        self.blocker_code = BLOCKER_FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE


@dataclass(frozen=True)
class RepositoryIdentity:
    numeric_id: int
    node_id: str
    owner: str
    name: str
    default_branch: str
    default_head_sha: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ForensicSnapshot:
    repository: RepositoryIdentity
    repository_identity_sha256: str
    release_inventory_sha256: str
    asset_inventory_sha256: str
    ref_inventory_sha256: str
    complete_forensic_inventory_sha256: str
    canonical_repository_json: bytes
    canonical_releases_json: bytes
    canonical_assets_json: bytes
    canonical_refs_json: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository.to_dict(),
            "repository_identity_sha256": self.repository_identity_sha256,
            "release_inventory_sha256": self.release_inventory_sha256,
            "asset_inventory_sha256": self.asset_inventory_sha256,
            "ref_inventory_sha256": self.ref_inventory_sha256,
            "complete_forensic_inventory_sha256": self.complete_forensic_inventory_sha256,
        }


@dataclass(frozen=True)
class KnownBrokenEvidenceV1:
    repository_id: int
    repository_node_id: str
    release_id: int
    asset_id: int
    installer_size: int
    installer_sha256: str
    historical_source_commit: str
    historical_verifier_path: str
    historical_verifier_sha256: str
    historical_failure_exit_code: int
    historical_failure_output_sha256: str
    historical_core_payload_sha256: str
    source_build_provenance_sha256: str
    schema_version: int = 1
    qualification_status: Literal["KNOWN_BROKEN_UNQUALIFIED"] = QUALIFICATION_STATUS_KNOWN_BROKEN

    def __post_init__(self) -> None:
        validate_known_broken_evidence(self)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnownBrokenEvidenceV1:
        return cls(
            schema_version=data.get("schema_version", 1),
            repository_id=data["repository_id"],
            repository_node_id=data["repository_node_id"],
            release_id=data["release_id"],
            asset_id=data["asset_id"],
            installer_size=data["installer_size"],
            installer_sha256=data["installer_sha256"],
            historical_source_commit=data["historical_source_commit"],
            historical_verifier_path=data["historical_verifier_path"],
            historical_verifier_sha256=data["historical_verifier_sha256"],
            historical_failure_exit_code=data["historical_failure_exit_code"],
            historical_failure_output_sha256=data["historical_failure_output_sha256"],
            historical_core_payload_sha256=data["historical_core_payload_sha256"],
            source_build_provenance_sha256=data["source_build_provenance_sha256"],
            qualification_status=data.get("qualification_status", QUALIFICATION_STATUS_KNOWN_BROKEN),
        )


def _validate_hex64(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _HEX64_RE.match(value):
        raise ForensicArtifactCustodyIncompleteError(
            f"{name} must be a 64-character lowercase hex string, got {value!r}"
        )


def _validate_hex40(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _HEX40_RE.match(value):
        raise ForensicArtifactCustodyIncompleteError(
            f"{name} must be a 40-character lowercase hex string, got {value!r}"
        )


def validate_known_broken_evidence(evidence: Any) -> None:
    """Validate KnownBrokenEvidenceV1 schema strictly."""
    if is_dataclass(evidence) and not isinstance(evidence, type):
        data = asdict(evidence)
    elif isinstance(evidence, dict):
        data = evidence
    else:
        raise ForensicArtifactCustodyIncompleteError(
            f"KnownBrokenEvidence must be a dict or dataclass, got {type(evidence).__name__}"
        )

    if data.get("schema_version") != 1:
        raise ForensicArtifactCustodyIncompleteError(
            f"KnownBrokenEvidence schema_version must be 1, got {data.get('schema_version')!r}"
        )

    for id_field in ("repository_id", "release_id", "asset_id", "installer_size"):
        val = data.get(id_field)
        if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise ForensicArtifactCustodyIncompleteError(
                f"KnownBrokenEvidence {id_field} must be a positive integer, got {val!r}"
            )

    node_id = data.get("repository_node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ForensicArtifactCustodyIncompleteError("KnownBrokenEvidence repository_node_id must be non-empty string")

    _validate_hex64(data.get("installer_sha256"), "installer_sha256")
    _validate_hex40(data.get("historical_source_commit"), "historical_source_commit")

    v_path = data.get("historical_verifier_path")
    if v_path != HISTORICAL_VERIFIER_PATH:
        raise ForensicArtifactCustodyIncompleteError(
            f"historical_verifier_path must be {HISTORICAL_VERIFIER_PATH!r}, got {v_path!r}"
        )

    _validate_hex64(data.get("historical_verifier_sha256"), "historical_verifier_sha256")

    code = data.get("historical_failure_exit_code")
    if code != HISTORICAL_FAILURE_EXIT_CODE:
        raise ForensicArtifactCustodyIncompleteError(
            f"historical_failure_exit_code must be {HISTORICAL_FAILURE_EXIT_CODE}, got {code!r}"
        )

    _validate_hex64(data.get("historical_failure_output_sha256"), "historical_failure_output_sha256")
    _validate_hex64(data.get("historical_core_payload_sha256"), "historical_core_payload_sha256")
    _validate_hex64(data.get("source_build_provenance_sha256"), "source_build_provenance_sha256")

    qual = data.get("qualification_status")
    if qual != QUALIFICATION_STATUS_KNOWN_BROKEN:
        raise ForensicArtifactCustodyIncompleteError(
            f"qualification_status must be {QUALIFICATION_STATUS_KNOWN_BROKEN!r}, got {qual!r}"
        )


@runtime_checkable
class GitHubExecutor(Protocol):
    def get(self, endpoint: str, *, params: dict[str, Any] | None = None) -> Any: ...


class FakeResponse:
    def __init__(self, data: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> None:
        self.data = data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> Any:
        return self.data


class FakeGitHubExecutor:
    def __init__(
        self,
        *,
        repo_data: dict[str, Any] | None = None,
        releases_pages: list[list[dict[str, Any]]] | None = None,
        refs: list[dict[str, Any]] | None = None,
        tags_objects: dict[str, dict[str, Any]] | None = None,
        commits: dict[str, dict[str, Any]] | None = None,
        broken_on_page: int | None = None,
    ) -> None:
        self.repo_data = repo_data or {}
        self.releases_pages = releases_pages or []
        self.refs = refs or []
        self.tags_objects = tags_objects or {}
        self.commits = commits or {}
        self.broken_on_page = broken_on_page
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, endpoint: str, *, params: dict[str, Any] | None = None) -> FakeResponse:
        self.calls.append((endpoint, params))
        ep = endpoint.strip("/")

        if ep.endswith("/releases"):
            page = (params or {}).get("page", 1)
            per_page = (params or {}).get("per_page", 30)
            if self.broken_on_page is not None and page == self.broken_on_page:
                return FakeResponse({"message": "Pagination error simulated"}, status_code=500)
            if 1 <= page <= len(self.releases_pages):
                items = self.releases_pages[page - 1]
                headers = {}
                link_parts = []
                if page < len(self.releases_pages):
                    link_parts.append(f'<{endpoint}?page={page + 1}&per_page={per_page}>; rel="next"')
                    link_parts.append(
                        f'<{endpoint}?page={len(self.releases_pages)}&per_page={per_page}>; rel="last"'
                    )
                if page > 1:
                    link_parts.append(f'<{endpoint}?page={page - 1}&per_page={per_page}>; rel="prev"')
                    link_parts.append(f'<{endpoint}?page=1&per_page={per_page}>; rel="first"')
                if link_parts:
                    headers["Link"] = ", ".join(link_parts)
                return FakeResponse(items, status_code=200, headers=headers)
            return FakeResponse([], status_code=200)

        if "/git/refs" in ep or "/git/matching-refs" in ep:
            return FakeResponse(self.refs, status_code=200)

        if "/git/tags/" in ep:
            sha = ep.split("/git/tags/")[-1]
            if sha in self.tags_objects:
                return FakeResponse(self.tags_objects[sha], status_code=200)
            return FakeResponse({"message": "Tag not found"}, status_code=404)

        if "/commits/" in ep:
            ref = ep.split("/commits/")[-1]
            if ref in self.commits:
                return FakeResponse(self.commits[ref], status_code=200)
            return FakeResponse({"sha": ref}, status_code=200)

        if ep.startswith("repos/") and len(ep.split("/")) == 3:
            return FakeResponse(self.repo_data, status_code=200)

        return FakeResponse({"message": "Not found"}, status_code=404)


class FakeDownloadExecutor:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.download_calls: list[tuple[str, Path]] = []

    def download(self, url: str, destination: Path) -> Path:
        self.download_calls.append((url, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.payload)
        return destination


def _parse_link_header(link_header: str | None) -> dict[str, str]:
    if not link_header:
        return {}
    links: dict[str, str] = {}
    for part in link_header.split(","):
        part = part.strip()
        if ";" in part:
            url_part, *rel_parts = part.split(";")
            url = url_part.strip().strip("<>")
            for rel_part in rel_parts:
                rel_part = rel_part.strip()
                if rel_part.startswith('rel="') and rel_part.endswith('"'):
                    rel = rel_part[5:-1]
                    links[rel] = url
    return links


def _get_api(executor: Any, endpoint: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, str]]:
    """Execute GET request using injected executor and return (json_data, headers)."""
    try:
        if hasattr(executor, "get"):
            resp = executor.get(endpoint, params=params)
        elif callable(executor):
            resp = executor(endpoint, params=params)
        else:
            raise ForensicCaptureError(f"Unsupported executor type: {type(executor).__name__}")
    except ForensicCaptureError:
        raise
    except Exception as err:
        raise ForensicCaptureError(f"GitHub API call to {endpoint} failed: {err}") from err

    if hasattr(resp, "status_code"):
        if resp.status_code != 200:
            raise ForensicCaptureError(
                f"GitHub API {endpoint} returned status {resp.status_code}: {getattr(resp, 'data', '')}"
            )
        data = resp.json() if callable(getattr(resp, "json", None)) else resp.data
        headers = getattr(resp, "headers", {}) or {}
        return data, headers
    elif isinstance(resp, (dict, list)):
        return resp, {}
    else:
        raise ForensicCaptureError(f"Unexpected response type from executor: {type(resp).__name__}")


def capture_repository_identity(owner: str, repo: str, executor: Any) -> RepositoryIdentity:
    """Capture immutable repository identity from GitHub API."""
    data, _ = _get_api(executor, f"repos/{owner}/{repo}")
    if not isinstance(data, dict):
        raise ForensicCaptureError(f"Repository API response must be a dict, got {type(data).__name__}")

    numeric_id = data.get("id")
    if not isinstance(numeric_id, int) or numeric_id <= 0:
        raise ForensicCaptureError(f"Repository numeric id missing or invalid: {numeric_id!r}")

    node_id = data.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ForensicCaptureError("Repository node_id missing or invalid")

    owner_obj = data.get("owner", {})
    owner_login = owner_obj.get("login") if isinstance(owner_obj, dict) else None
    if not owner_login:
        owner_login = owner

    name = data.get("name", repo)
    default_branch = data.get("default_branch", "main")

    commit_data, _ = _get_api(executor, f"repos/{owner}/{repo}/commits/{default_branch}")
    if isinstance(commit_data, dict):
        default_head_sha = commit_data.get("sha")
    else:
        default_head_sha = None

    if not default_head_sha or not isinstance(default_head_sha, str):
        raise ForensicCaptureError(f"Could not resolve default_head_sha for branch {default_branch}")

    return RepositoryIdentity(
        numeric_id=numeric_id,
        node_id=node_id,
        owner=owner_login,
        name=name,
        default_branch=default_branch,
        default_head_sha=default_head_sha.lower(),
    )


def capture_releases(owner: str, repo: str, executor: Any) -> list[dict[str, Any]]:
    """Capture ALL releases via paginated GitHub API."""
    all_releases: list[dict[str, Any]] = []
    page = 1
    per_page = 100

    while True:
        data, headers = _get_api(
            executor,
            f"repos/{owner}/{repo}/releases",
            params={"page": page, "per_page": per_page},
        )
        if not isinstance(data, list):
            raise ForensicCaptureError(f"Releases response on page {page} must be a list, got {type(data).__name__}")

        if not data:
            break

        for rel in data:
            if not isinstance(rel, dict):
                raise ForensicCaptureError("Release entry must be a dictionary")

            target = rel.get("target_commitish", "")
            if _HEX40_RE.match(target):
                resolved_commit = target.lower()
            else:
                commit_info, _ = _get_api(executor, f"repos/{owner}/{repo}/commits/{target}")
                resolved_commit = commit_info.get("sha", "").lower() if isinstance(commit_info, dict) else ""
                if not _HEX40_RE.match(resolved_commit):
                    raise ForensicCaptureError(
                        f"Could not resolve target_commitish {target!r} for release {rel.get('tag_name')!r}"
                    )

            rel_record = {
                "id": rel["id"],
                "tag_name": rel.get("tag_name", ""),
                "name": rel.get("name", ""),
                "draft": bool(rel.get("draft", False)),
                "prerelease": bool(rel.get("prerelease", False)),
                "target_commitish": target,
                "resolved_commit": resolved_commit,
                "created_at": rel.get("created_at", ""),
                "published_at": rel.get("published_at", ""),
                "assets": rel.get("assets", []),
            }
            all_releases.append(rel_record)

        link_header = headers.get("Link", "")
        links = _parse_link_header(link_header)
        if "next" in links:
            page += 1
        else:
            break

    return all_releases


def capture_assets(
    owner: str, repo: str, releases: list[dict[str, Any]], executor: Any
) -> list[dict[str, Any]]:
    """Capture ALL custom assets across all releases."""
    all_assets: list[dict[str, Any]] = []
    for rel in releases:
        rel_id = rel["id"]
        assets = rel.get("assets", [])
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_record = {
                "id": asset["id"],
                "release_id": rel_id,
                "name": asset.get("name", ""),
                "size": asset.get("size", 0),
                "download_url": asset.get("browser_download_url") or asset.get("url", ""),
                "content_type": asset.get("content_type", ""),
                "state": asset.get("state", ""),
            }
            all_assets.append(asset_record)
    return all_assets


def capture_refs(owner: str, repo: str, executor: Any) -> list[dict[str, Any]]:
    """Capture ALL tags (annotated with peeled commits, lightweight) and branch refs."""
    data, _ = _get_api(executor, f"repos/{owner}/{repo}/git/refs")
    if not isinstance(data, list):
        raise ForensicCaptureError(f"Git refs response must be a list, got {type(data).__name__}")

    all_refs: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ref_name = item.get("ref", "")
        node_id = item.get("node_id", "")
        obj = item.get("object", {})
        obj_type = obj.get("type", "")
        obj_sha = obj.get("sha", "").lower()

        if obj_type == "commit":
            peeled_commit = obj_sha
        elif obj_type == "tag":
            tag_obj, _ = _get_api(executor, f"repos/{owner}/{repo}/git/tags/{obj_sha}")
            peeled = tag_obj.get("object", {}) if isinstance(tag_obj, dict) else {}
            peeled_commit = peeled.get("sha", "").lower()
        else:
            peeled_commit = obj_sha

        all_refs.append(
            {
                "ref": ref_name,
                "node_id": node_id,
                "object_type": obj_type,
                "object_sha": obj_sha,
                "peeled_commit": peeled_commit,
            }
        )
    return all_refs


def capture_forensic_snapshot(owner: str, repo: str, executor: Any) -> ForensicSnapshot:
    """Capture complete repository forensic snapshot and produce canonical JSON inventories and digests."""
    repository = capture_repository_identity(owner, repo, executor)
    releases = capture_releases(owner, repo, executor)
    assets = capture_assets(owner, repo, releases, executor)
    refs = capture_refs(owner, repo, executor)

    canonical_repo_json = json.dumps(repository.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    repo_identity_sha = hashlib.sha256(canonical_repo_json).hexdigest()

    # Sort releases deterministically for order-independence
    sorted_releases = sorted(releases, key=lambda r: (r["id"], r.get("tag_name", "")))
    canonical_releases_json = json.dumps(sorted_releases, sort_keys=True, separators=(",", ":")).encode("utf-8")
    release_inventory_sha = hashlib.sha256(canonical_releases_json).hexdigest()

    # Sort assets deterministically
    sorted_assets = sorted(assets, key=lambda a: (a["id"], a.get("name", "")))
    canonical_assets_json = json.dumps(sorted_assets, sort_keys=True, separators=(",", ":")).encode("utf-8")
    asset_inventory_sha = hashlib.sha256(canonical_assets_json).hexdigest()

    # Sort refs deterministically
    sorted_refs = sorted(refs, key=lambda r: r["ref"])
    canonical_refs_json = json.dumps(sorted_refs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ref_inventory_sha = hashlib.sha256(canonical_refs_json).hexdigest()

    combined_inventory = {
        "repository": json.loads(canonical_repo_json.decode("utf-8")),
        "releases": json.loads(canonical_releases_json.decode("utf-8")),
        "assets": json.loads(canonical_assets_json.decode("utf-8")),
        "refs": json.loads(canonical_refs_json.decode("utf-8")),
    }
    canonical_combined_json = json.dumps(combined_inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    complete_inventory_sha = hashlib.sha256(canonical_combined_json).hexdigest()

    return ForensicSnapshot(
        repository=repository,
        repository_identity_sha256=repo_identity_sha,
        release_inventory_sha256=release_inventory_sha,
        asset_inventory_sha256=asset_inventory_sha,
        ref_inventory_sha256=ref_inventory_sha,
        complete_forensic_inventory_sha256=complete_inventory_sha,
        canonical_repository_json=canonical_repo_json,
        canonical_releases_json=canonical_releases_json,
        canonical_assets_json=canonical_assets_json,
        canonical_refs_json=canonical_refs_json,
    )


def build_known_broken_evidence(
    *,
    repository_id: int,
    repository_node_id: str,
    release_id: int,
    asset_id: int,
    installer_size: int,
    installer_sha256: str,
    historical_source_commit: str,
    historical_verifier_path: str,
    historical_verifier_sha256: str,
    historical_failure_exit_code: int,
    historical_failure_output_sha256: str,
    historical_core_payload_sha256: str,
    source_build_provenance_sha256: str,
    qualification_status: Literal["KNOWN_BROKEN_UNQUALIFIED"] = QUALIFICATION_STATUS_KNOWN_BROKEN,
) -> KnownBrokenEvidenceV1:
    """Construct and validate KnownBrokenEvidenceV1 record."""
    return KnownBrokenEvidenceV1(
        schema_version=1,
        repository_id=repository_id,
        repository_node_id=repository_node_id,
        release_id=release_id,
        asset_id=asset_id,
        installer_size=installer_size,
        installer_sha256=installer_sha256.lower(),
        historical_source_commit=historical_source_commit.lower(),
        historical_verifier_path=historical_verifier_path,
        historical_verifier_sha256=historical_verifier_sha256.lower(),
        historical_failure_exit_code=historical_failure_exit_code,
        historical_failure_output_sha256=historical_failure_output_sha256.lower(),
        historical_core_payload_sha256=historical_core_payload_sha256.lower(),
        source_build_provenance_sha256=source_build_provenance_sha256.lower(),
        qualification_status=qualification_status,
    )


def write_known_broken_evidence(
    evidence: KnownBrokenEvidenceV1 | dict[str, Any],
    custody_root: Path,
    filename: str = "known-broken-v512-installer-evidence.json",
) -> Path:
    """Write canonical KnownBrokenEvidenceV1 file to custody root and fsync."""
    validate_known_broken_evidence(evidence)
    ev_dict = evidence.to_dict() if hasattr(evidence, "to_dict") else evidence

    custody_root = Path(custody_root)
    custody_root.mkdir(parents=True, exist_ok=True)
    target_path = custody_root / filename

    data_bytes = json.dumps(ev_dict, indent=2, sort_keys=True).encode("utf-8")
    with open(target_path, "wb") as f:
        f.write(data_bytes)
        f.flush()
        os.fsync(f.fileno())

    return target_path


def custody_broken_installer(
    *,
    repository_id: int,
    repository_node_id: str,
    release_id: int,
    release_tag: str,
    asset_id: int,
    asset_name: str,
    custody_root: Path,
    installer_bytes: bytes | None = None,
    download_executor: Any | None = None,
    download_url: str | None = None,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    known_broken_evidence: KnownBrokenEvidenceV1 | dict[str, Any],
    captured_at: str | None = None,
) -> ArtifactCustodyEvidence:
    """Safely custody broken installer asset into custody_root and bind to known-broken evidence."""
    custody_root = Path(custody_root)
    custody_root.mkdir(parents=True, exist_ok=True)

    target_asset_path = custody_root / asset_name

    # Step A: obtain asset bytes into target_asset_path
    if installer_bytes is not None:
        target_asset_path.write_bytes(installer_bytes)
    elif download_executor is not None and download_url:
        if hasattr(download_executor, "download"):
            download_executor.download(download_url, target_asset_path)
        elif callable(download_executor):
            download_executor(download_url, target_asset_path)
        else:
            raise ForensicCaptureError(f"Unsupported download_executor: {type(download_executor).__name__}")
    else:
        raise ForensicCaptureError("Either installer_bytes or download_executor+download_url must be provided")

    if not target_asset_path.is_file():
        raise ForensicArtifactCustodyIncompleteError(
            f"Custodied installer file not found at {target_asset_path}"
        )

    # Step B: re-hash actual bytes
    actual_bytes = target_asset_path.read_bytes()
    actual_size = len(actual_bytes)
    actual_sha = hashlib.sha256(actual_bytes).hexdigest().lower()

    if expected_size is not None and actual_size != expected_size:
        raise ForensicArtifactCustodyIncompleteError(
            f"Installer size mismatch: expected {expected_size}, got {actual_size}"
        )

    if expected_sha256 is not None and actual_sha != expected_sha256.lower():
        raise ForensicArtifactCustodyIncompleteError(
            f"Installer sha256 mismatch: expected {expected_sha256.lower()}, got {actual_sha}"
        )

    # Step C: validate known-broken evidence against actual bytes and metadata
    validate_known_broken_evidence(known_broken_evidence)
    ev_dict = known_broken_evidence.to_dict() if hasattr(known_broken_evidence, "to_dict") else known_broken_evidence

    if ev_dict["installer_size"] != actual_size:
        raise ForensicArtifactCustodyIncompleteError(
            f"known_broken_evidence installer_size {ev_dict['installer_size']} does not match actual size {actual_size}"
        )

    if ev_dict["installer_sha256"] != actual_sha:
        raise ForensicArtifactCustodyIncompleteError(
            f"known_broken_evidence installer_sha256 {ev_dict['installer_sha256']} does not match actual sha {actual_sha}"
        )

    if ev_dict["repository_id"] != repository_id:
        raise ForensicArtifactCustodyIncompleteError(
            f"known_broken_evidence repository_id {ev_dict['repository_id']} != {repository_id}"
        )

    if ev_dict["release_id"] != release_id:
        raise ForensicArtifactCustodyIncompleteError(
            f"known_broken_evidence release_id {ev_dict['release_id']} != {release_id}"
        )

    if ev_dict["asset_id"] != asset_id:
        raise ForensicArtifactCustodyIncompleteError(
            f"known_broken_evidence asset_id {ev_dict['asset_id']} != {asset_id}"
        )

    # Step D: write evidence file into custody root
    evidence_filename = "known-broken-v512-installer-evidence.json"
    evidence_file_path = write_known_broken_evidence(known_broken_evidence, custody_root, evidence_filename)
    evidence_bytes = evidence_file_path.read_bytes()
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()

    if not captured_at:
        captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    elif not _RFC3339_RE.match(captured_at):
        raise ForensicArtifactCustodyIncompleteError(f"captured_at must be RFC3339 format, got {captured_at!r}")

    return ArtifactCustodyEvidence(
        repository_id=repository_id,
        repository_node_id=repository_node_id,
        release_id=release_id,
        release_tag=release_tag,
        asset_id=asset_id,
        asset_name=asset_name,
        size=actual_size,
        sha256=actual_sha,
        custody_path=str(target_asset_path.resolve()),
        captured_at=captured_at,
        known_broken_evidence_ref=evidence_filename,
        known_broken_evidence_sha256=evidence_sha256,
        qualification_status=QUALIFICATION_STATUS_KNOWN_BROKEN,
    )
