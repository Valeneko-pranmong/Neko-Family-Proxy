#!/usr/bin/env python3
"""Exact-snapshot operational dependency audit for Installer repository retirement."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAUNCHER_SRC = _REPO_ROOT / "launcher" / "src"
if _LAUNCHER_SRC.exists() and str(_LAUNCHER_SRC) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_SRC))

try:
    from neko_launcher.updater.canonical_json import canonical_json_dumps
except ImportError:

    def canonical_json_dumps(obj: object) -> bytes:
        return json.dumps(
            obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")


_BLOCKED_DIR_PARTS = frozenset({
    ".git",
    ".venv",
    ".next",
    "node_modules",
    "__pycache__",
})

_BINARY_SUFFIXES = frozenset({
    ".dll",
    ".exe",
    ".gz",
    ".ico",
    ".p12",
    ".pem",
    ".pfx",
    ".png",
    ".rar",
    ".tar",
    ".ttf",
    ".zip",
})

_API_ROUTE_PATTERN = re.compile(
    r"https?://api\.github\.com/repos/[^/\s\"')]+/Neko-Family-Proxy-Installer\b",
    re.IGNORECASE,
)
_DOWNLOAD_URL_PATTERN = re.compile(
    r"(?:https?://github\.com/[^/\s\"')]+/Neko-Family-Proxy-Installer/releases/download/[^/\s\"')]+|releases/download/[^/\s\"')]*Neko-Family-Proxy-Installer[^/\s\"')]*)",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/[^/\s\"')]+/Neko-Family-Proxy-Installer\b",
    re.IGNORECASE,
)
_FULL_REPO_PATTERN = re.compile(
    r"\bValeneko-pranmong/Neko-Family-Proxy-Installer\b",
    re.IGNORECASE,
)
_DIRECT_REPO_PATTERN = re.compile(
    r"\bNeko-Family-Proxy-Installer\b",
)

_SPLIT_OWNER_PATTERN = re.compile(
    r"""(?:\b(?:OWNER|REPO_OWNER|GITHUB_OWNER|ORG|GITHUB_ORG)\s*=\s*["']Valeneko-pranmong["']|["']owner["']\s*:\s*["']Valeneko-pranmong["'])""",
    re.IGNORECASE,
)
_SPLIT_REPO_PATTERN = re.compile(
    r"""(?:\b(?:REPO|REPO_NAME|REPOSITORY|INSTALLER_REPO)\s*=\s*["'](?:Neko-Family-Proxy-)?Installer["']|["'](?:repo|installer_repo)["']\s*:\s*["'](?:Neko-Family-Proxy-)?Installer["'])""",
    re.IGNORECASE,
)

_SUPERSEDED_MARKER_PATTERN = re.compile(
    r"\b(superseded|historical|deprecated|archive[d]?|retire[d]?|retirement|deleted?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DependencyFinding:
    path: str
    line: int
    kind: str
    text_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "line": self.line,
            "path": self.path,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DependencyFinding:
        return cls(
            path=str(data["path"]),
            line=int(data["line"]),
            kind=str(data["kind"]),
            text_digest=str(data["text_digest"]),
        )


@dataclass(frozen=True)
class DependencyAuditEvidence:
    input_snapshot_sha256: str
    result_sha256: str
    approved_source_commit: str
    tracked_tree_sha256: str
    operational_matches: tuple[DependencyFinding, ...]
    historical_allowed_matches: tuple[DependencyFinding, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "approved_source_commit": self.approved_source_commit,
            "historical_allowed_matches": [
                f.to_dict() for f in self.historical_allowed_matches
            ],
            "input_snapshot_sha256": self.input_snapshot_sha256,
            "operational_matches": [f.to_dict() for f in self.operational_matches],
            "result_sha256": self.result_sha256,
            "tracked_tree_sha256": self.tracked_tree_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DependencyAuditEvidence:
        raw_operational = data.get("operational_matches") or []
        raw_historical = data.get("historical_allowed_matches") or []
        return cls(
            input_snapshot_sha256=str(data["input_snapshot_sha256"]),
            result_sha256=str(data["result_sha256"]),
            approved_source_commit=str(data["approved_source_commit"]),
            tracked_tree_sha256=str(data["tracked_tree_sha256"]),
            operational_matches=tuple(
                DependencyFinding.from_dict(item)  # type: ignore[arg-type]
                for item in raw_operational
            ),
            historical_allowed_matches=tuple(
                DependencyFinding.from_dict(item)  # type: ignore[arg-type]
                for item in raw_historical
            ),
        )


def _is_text_candidate(path: Path) -> bool:
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return False
    parts = set(path.parts)
    if parts & _BLOCKED_DIR_PARTS:
        return False
    return True


def _compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_dependency_snapshot(
    repo_root: Path,
    *,
    external_inputs: Mapping[str, Path] | None = None,
) -> dict[str, object]:
    """Build deterministic input snapshot of git-tracked files and external inputs."""
    repo_root = Path(repo_root).resolve()
    approved_source_commit = "UNCOMMITTED"
    tracked_tree_sha256 = "UNCOMMITTED"
    repo_identity = repo_root.name

    tracked_paths: list[Path] = []
    is_git_repo = False
    try:
        rev_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        approved_source_commit = rev_head.stdout.strip()
        is_git_repo = True

        rev_tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        tracked_tree_sha256 = rev_tree.stdout.strip()

        remote_res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if remote_res.returncode == 0 and remote_res.stdout.strip():
            repo_identity = remote_res.stdout.strip()

        ls_res = subprocess.run(
            ["git", "ls-files", "-z", "--cached"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        raw_items = ls_res.stdout.split(b"\0")
        for item in raw_items:
            if not item:
                continue
            decoded = item.decode("utf-8", errors="surrogateescape")
            tracked_paths.append(repo_root / decoded)
    except (subprocess.SubprocessError, OSError):
        is_git_repo = False

    if not is_git_repo:
        for p in repo_root.rglob("*"):
            if p.is_file():
                tracked_paths.append(p)

    tracked_files: dict[str, str] = {}
    for p in tracked_paths:
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(repo_root)
        except ValueError:
            continue
        if not _is_text_candidate(rel):
            continue
        tracked_files[rel.as_posix()] = _compute_file_sha256(p)

    sorted_tracked_files = dict(sorted(tracked_files.items()))

    if not is_git_repo:
        tracked_tree_sha256 = hashlib.sha256(
            canonical_json_dumps(sorted_tracked_files)
        ).hexdigest()

    ext_dict: dict[str, dict[str, str]] = {}
    if external_inputs:
        for key in sorted(external_inputs.keys()):
            ext_path = Path(external_inputs[key]).resolve()
            if ext_path.is_file():
                ext_dict[key] = {
                    "canonical_path": ext_path.as_posix(),
                    "sha256": _compute_file_sha256(ext_path),
                }
            else:
                ext_dict[key] = {
                    "canonical_path": ext_path.as_posix(),
                    "sha256": "MISSING",
                }

    return {
        "approved_source_commit": approved_source_commit,
        "external_inputs": ext_dict,
        "repository_identity": repo_identity,
        "tracked_files": sorted_tracked_files,
        "tracked_tree_sha256": tracked_tree_sha256,
    }


def _classify_finding_target(rel_path: str, content: str) -> str:
    """Classify target path into 'operational' or 'historical_allowed'."""
    p = Path(rel_path)
    parts = p.parts

    # Historical locations: docs/archive or docs/superpowers
    if len(parts) >= 2 and parts[0] == "docs" and parts[1] == "archive":
        return "historical_allowed"

    if len(parts) >= 2 and parts[0] == "docs" and parts[1] == "superpowers":
        # Superseded specs/plans with explicit marker are historical allowed
        if _SUPERSEDED_MARKER_PATTERN.search(content):
            return "historical_allowed"
        # If no explicit marker in superpowers, mark operational/blocker
        return "operational"

    # Unit/integration test suites are non-operational verification suites
    if any(part in {"tests", "test"} for part in parts):
        return "historical_allowed"

    # All other surfaces (src, launcher, scripts, installer, .github, docs/current, README, external) are operational
    return "operational"


def _scan_content_for_findings(
    display_path: str,
    content: str,
) -> list[DependencyFinding]:
    findings: list[DependencyFinding] = []
    lines = content.splitlines()

    has_split_owner = bool(_SPLIT_OWNER_PATTERN.search(content))
    has_split_repo = bool(_SPLIT_REPO_PATTERN.search(content))
    has_split_constant = has_split_owner and has_split_repo

    for idx, line in enumerate(lines, start=1):
        matched_kind: str | None = None
        if _API_ROUTE_PATTERN.search(line):
            matched_kind = "api_route"
        elif _DOWNLOAD_URL_PATTERN.search(line):
            matched_kind = "download_url"
        elif _URL_PATTERN.search(line):
            matched_kind = "url"
        elif _FULL_REPO_PATTERN.search(line):
            matched_kind = "full_repository_reference"
        elif _DIRECT_REPO_PATTERN.search(line):
            matched_kind = "direct_reference"
        elif has_split_constant:
            if _SPLIT_OWNER_PATTERN.search(line) or _SPLIT_REPO_PATTERN.search(line):
                matched_kind = "split_constant"
            elif (
                "OWNER" in line
                and "REPO" in line
                and ("http" in line or "/" in line or "{" in line)
            ):
                matched_kind = "split_constant"

        if matched_kind is not None:
            text_digest = hashlib.sha256(line.strip().encode("utf-8")).hexdigest()
            findings.append(
                DependencyFinding(
                    path=display_path,
                    line=idx,
                    kind=matched_kind,
                    text_digest=text_digest,
                )
            )

    return findings


def audit_old_installer_dependency(
    repo_root: Path,
    snapshot: dict[str, object],
) -> DependencyAuditEvidence:
    """Audit repo and external inputs for dependencies on retiring Installer repository."""
    repo_root = Path(repo_root).resolve()
    input_snapshot_sha256 = hashlib.sha256(canonical_json_dumps(snapshot)).hexdigest()
    approved_source_commit = str(snapshot.get("approved_source_commit", ""))
    tracked_tree_sha256 = str(snapshot.get("tracked_tree_sha256", ""))

    operational_findings: list[DependencyFinding] = []
    historical_findings: list[DependencyFinding] = []

    tracked_files = snapshot.get("tracked_files")
    if isinstance(tracked_files, dict):
        for rel_posix in sorted(tracked_files.keys()):
            file_path = repo_root / rel_posix
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            findings = _scan_content_for_findings(rel_posix, content)
            if not findings:
                continue

            category = _classify_finding_target(rel_posix, content)
            if category == "historical_allowed":
                historical_findings.extend(findings)
            else:
                operational_findings.extend(findings)

    external_inputs = snapshot.get("external_inputs")
    if isinstance(external_inputs, dict):
        for key in sorted(external_inputs.keys()):
            ext_entry = external_inputs[key]
            ext_path: Path | None = None
            if isinstance(ext_entry, dict):
                canon = ext_entry.get("canonical_path")
                if canon:
                    p = Path(canon)
                    if p.is_file():
                        ext_path = p
            elif isinstance(ext_entry, str):
                p = repo_root / key
                if p.is_file():
                    ext_path = p
                else:
                    p = Path(key)
                    if p.is_file():
                        ext_path = p

            if ext_path and ext_path.is_file():
                try:
                    content = ext_path.read_text(encoding="utf-8")
                    findings = _scan_content_for_findings(key, content)
                    operational_findings.extend(findings)
                except (UnicodeDecodeError, OSError):
                    pass

    operational_matches = tuple(
        sorted(operational_findings, key=lambda f: (f.path, f.line, f.kind))
    )
    historical_allowed_matches = tuple(
        sorted(historical_findings, key=lambda f: (f.path, f.line, f.kind))
    )

    result_payload = {
        "approved_source_commit": approved_source_commit,
        "historical_allowed_matches": [f.to_dict() for f in historical_allowed_matches],
        "input_snapshot_sha256": input_snapshot_sha256,
        "operational_matches": [f.to_dict() for f in operational_matches],
        "tracked_tree_sha256": tracked_tree_sha256,
    }
    result_sha256 = hashlib.sha256(canonical_json_dumps(result_payload)).hexdigest()

    return DependencyAuditEvidence(
        input_snapshot_sha256=input_snapshot_sha256,
        result_sha256=result_sha256,
        approved_source_commit=approved_source_commit,
        tracked_tree_sha256=tracked_tree_sha256,
        operational_matches=operational_matches,
        historical_allowed_matches=historical_allowed_matches,
    )


def verify_audit_freshness(
    repo_root: Path,
    evidence: DependencyAuditEvidence,
    *,
    external_inputs: Mapping[str, Path] | None = None,
) -> bool:
    """Verify that evidence matches the current state of repo and external inputs."""
    repo_root = Path(repo_root).resolve()
    try:
        fresh_snapshot = build_dependency_snapshot(
            repo_root, external_inputs=external_inputs
        )
        fresh_snapshot_sha256 = hashlib.sha256(
            canonical_json_dumps(fresh_snapshot)
        ).hexdigest()
        if fresh_snapshot_sha256 != evidence.input_snapshot_sha256:
            return False
        if (
            str(fresh_snapshot.get("approved_source_commit"))
            != evidence.approved_source_commit
        ):
            return False
        if (
            str(fresh_snapshot.get("tracked_tree_sha256"))
            != evidence.tracked_tree_sha256
        ):
            return False

        fresh_evidence = audit_old_installer_dependency(repo_root, fresh_snapshot)
        if fresh_evidence.result_sha256 != evidence.result_sha256:
            return False
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exact-snapshot operational dependency audit for Installer repository retirement."
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository root path (default: current directory)",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to output the evidence JSON",
    )
    parser.add_argument(
        "--external-input",
        action="append",
        default=[],
        help="External input in KEY=PATH format",
    )

    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()

    external_inputs: dict[str, Path] = {}
    for item in args.external_input:
        if "=" in item:
            key, val = item.split("=", 1)
            external_inputs[key.strip()] = Path(val.strip())

    snapshot = build_dependency_snapshot(repo_root, external_inputs=external_inputs)
    evidence = audit_old_installer_dependency(repo_root, snapshot)

    evidence_dict = evidence.to_dict()
    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(
            json.dumps(evidence_dict, indent=2).encode("utf-8") + b"\n"
        )
        print(f"Audit evidence written to: {out_path}")

    print(
        f"Audit input snapshot SHA-256: {evidence.input_snapshot_sha256}\n"
        f"Audit result SHA-256:         {evidence.result_sha256}\n"
        f"Operational matches:          {len(evidence.operational_matches)}\n"
        f"Historical allowed matches:   {len(evidence.historical_allowed_matches)}"
    )

    if evidence.operational_matches:
        print("\nOperational dependency blockers found:")
        for m in evidence.operational_matches:
            print(f"  [{m.kind}] {m.path}:{m.line}")
        return 1

    print("\nOperational dependency audit passed: zero operational matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
