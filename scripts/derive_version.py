def get_next_patch(releases: list[dict], extra_tags: list[str] = None) -> str:
    if extra_tags is None:
        extra_tags = get_remote_tags()
    stable_patches = []
    occupied_tags = set(extra_tags)
    
    for r in releases:
        t = r.get("tag_name", "")
        if t:
            occupied_tags.add(t)
        # Distinguish stable from prerelease via GitHub metadata and tag shape
        if r.get("prerelease") is False and t.startswith("v5.1.") and "-" not in t:
            try:
                stable_patches.append(int(t.split(".")[2]))
            except ValueError:
                pass

    next_patch = max(stable_patches) + 1 if stable_patches else 0
    
    while f"v5.1.{next_patch}" in occupied_tags:
        next_patch += 1

    return f"v5.1.{next_patch}"

def get_release_sequence(version: str) -> int:
    """
    Derives the deterministic release_sequence without hardcoding constants.
    v5.1.X maps to sequence X + 4.
    e.g. v5.1.3 -> 7, v5.1.4 -> 8, v5.1.5 -> 9.
    """
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
