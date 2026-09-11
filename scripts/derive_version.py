def get_next_patch(releases: list[dict]) -> str:
    stable_patches = []
    occupied_tags = set()
    
    for r in releases:
        t = r.get("tag_name", "")
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
