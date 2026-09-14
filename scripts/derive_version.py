from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Literal


@dataclass(frozen=True)
class ReleaseTargetIntent:
    source_base: str
    target: str
    intent: Literal["user_bug"]


@dataclass(frozen=True)
class ReleaseAllocation:
    sequence: int
    release_id: str
    ledger_entry_sha256: str
    component_set_sha256: str
    authenticated_bindings_sha256: str
    history_snapshot_sha256: str


_ALLOWED_RELEASE_TARGET_FIELDS = frozenset({"source_base", "target", "intent"})
_FORBIDDEN_RELEASE_TARGET_FIELDS = frozenset({"stable", "seq", "stable_id", "installer_repo"})


def parse_release_target_data(data: dict[str, Any]) -> ReleaseTargetIntent:
    if not isinstance(data, dict):
        raise ValueError("release_target.json data must be a dictionary")

    forbidden = [k for k in data if k in _FORBIDDEN_RELEASE_TARGET_FIELDS or k not in _ALLOWED_RELEASE_TARGET_FIELDS]
    if forbidden:
        raise ValueError(f"forbidden release-target field: {sorted(forbidden)}")

    intent = data.get("intent")
    if intent != "user_bug":
        raise ValueError("intent is closed or missing")

    source_base = data.get("source_base")
    target = data.get("target")

    if not source_base or not target:
        raise ValueError("Missing required fields in release_target.json")

    source_match = re.match(r"^v5\.1\.(\d+)$", str(source_base))
    target_match = re.match(r"^v5\.1\.(\d+)$", str(target))

    if not source_match or not target_match:
        raise ValueError("Invalid source_base or target format")

    source_patch = int(source_match.group(1))
    target_patch = int(target_match.group(1))

    if target_patch != source_patch + 1:
        raise ValueError(
            f"exactly one patch increment from accepted source_base is allowed (source_base={source_base}, target={target})"
        )

    return ReleaseTargetIntent(
        source_base=str(source_base),
        target=str(target),
        intent="user_bug",
    )


def load_release_target_intent(path: Path) -> ReleaseTargetIntent:
    if not path.is_file():
        raise ValueError(f"release target file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_release_target_data(data)


def get_release_id(sequence: int) -> str:
    return f"stable-{sequence:04d}"


def get_github_releases() -> list[dict]:
    import subprocess

    out = subprocess.check_output(
        [
            "gh",
            "release",
            "list",
            "--repo",
            "Valeneko-pranmong/Neko-Family-Proxy",
            "--json",
            "tagName,isPrerelease",
            "--limit",
            "100",
        ]
    )
    releases = json.loads(out)
    return [{"tag_name": r["tagName"], "prerelease": r["isPrerelease"]} for r in releases]


def get_armed_target() -> ReleaseTargetIntent:
    target_file = Path(__file__).resolve().parent.parent / "release_target.json"
    return load_release_target_intent(target_file)


def get_armed_target_from_sha(sha: str) -> ReleaseTargetIntent:
    import subprocess

    try:
        out = subprocess.check_output(["git", "show", f"{sha}:release_target.json"])
        data = json.loads(out)
        return parse_release_target_data(data)
    except subprocess.CalledProcessError:
        try:
            out = subprocess.check_output(
                [
                    "gh",
                    "api",
                    f"repos/Valeneko-pranmong/Neko-Family-Proxy/contents/release_target.json?ref={sha}",
                    "-q",
                    ".content",
                ]
            )
            import base64

            data = json.loads(base64.b64decode(out).decode("utf-8"))
            return parse_release_target_data(data)
        except Exception as e:
            raise ValueError(f"release_target.json not found in exact commit {sha}: {e}") from e


def get_armed_target_from_dir(source_dir: Path) -> ReleaseTargetIntent:
    target_file = source_dir / "release_target.json"
    return load_release_target_intent(target_file)
