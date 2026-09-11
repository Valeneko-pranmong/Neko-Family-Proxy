import json
from pathlib import Path

def get_next_patch(releases: list[dict], extra_tags: list[str] = None) -> str:
    target_file = Path(__file__).resolve().parent.parent / "release_target.json"
    if target_file.exists():
        data = json.loads(target_file.read_text(encoding="utf-8"))
        target = data.get("target", "v5.1.3")
    else:
        target = "v5.1.3"

    for r in releases:
        if r.get("tag_name") == target and r.get("prerelease") is False:
            raise ValueError(f"Target {target} is already accepted as Stable. Require explicit PM intent to bump target.")

    return target

def get_release_sequence(version: str) -> int:
    target_file = Path(__file__).resolve().parent.parent / "release_target.json"
    if target_file.exists():
        data = json.loads(target_file.read_text(encoding="utf-8"))
        if version == data.get("target"):
            return data.get("seq", 7)

    import re
    if version.startswith("v5.1."):
        patch_str = version.split(".")[2]
        match = re.match(r"^(\d+)", patch_str)
        if match:
            patch = int(match.group(1))
            return patch + 4
    raise ValueError(f"Cannot derive sequence for version: {version}")

def get_release_id(sequence: int) -> str:
    return f"stable-{sequence:04d}"

def get_github_releases() -> list[dict]:
    import subprocess
    import json
    out = subprocess.check_output(["gh", "release", "list", "--repo", "Valeneko-pranmong/Neko-Family-Proxy", "--json", "tagName,isPrerelease", "--limit", "100"])
    releases = json.loads(out)
    return [{"tag_name": r["tagName"], "prerelease": r["isPrerelease"]} for r in releases]

def get_remote_tags() -> list[str]:
    import subprocess
    try:
        out = subprocess.check_output(["git", "ls-remote", "--tags", "origin"])
        tags = []
        for line in out.decode().splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[1].startswith("refs/tags/"):
                tag = parts[1].replace("refs/tags/", "")
                if tag.endswith("^{}"):
                    tag = tag[:-3]
                tags.append(tag)
        return tags
    except subprocess.CalledProcessError:
        return []
