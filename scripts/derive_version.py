import json
import re
from pathlib import Path


def get_release_sequence(version: str) -> int:
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
    import json
    import subprocess
    out = subprocess.check_output(["gh", "release", "list", "--repo", "Valeneko-pranmong/Neko-Family-Proxy", "--json", "tagName,isPrerelease", "--limit", "100"])
    releases = json.loads(out)
    return [{"tag_name": r["tagName"], "prerelease": r["isPrerelease"]} for r in releases]

def _parse_target_data(data: dict) -> tuple[str, str, int, str]:
    intent = data.get("intent")
    if intent != "user_bug":
        raise ValueError("intent is closed or missing")

    stable = data.get("stable", "")
    target = data.get("target", "")
    seq = data.get("seq")
    stable_id = data.get("stable_id")

    if not stable or not target or seq is None or not stable_id:
        raise ValueError("Missing required fields in release_target.json")

    stable_match = re.match(r"^v5\.1\.(\d+)$", stable)
    target_match = re.match(r"^v5\.1\.(\d+)$", target)

    if not stable_match or not target_match:
        raise ValueError("Invalid stable or target format")

    stable_patch = int(stable_match.group(1))
    target_patch = int(target_match.group(1))

    if target_patch != stable_patch + 1:
        raise ValueError(f"exactly one patch increment from accepted stable is allowed (stable={stable}, target={target})")

    expected_seq = stable_patch + 4 + 1
    if seq != expected_seq:
        raise ValueError("sequence or stable_id mismatch")

    expected_stable_id = f"stable-{seq:04d}"
    if stable_id != expected_stable_id:
        raise ValueError("sequence or stable_id mismatch")

    return stable, target, seq, stable_id

def get_armed_target() -> tuple[str, str, int, str]:
    target_file = Path(__file__).resolve().parent.parent / "release_target.json"
    if not target_file.exists():
        raise ValueError("release_target.json not found")

    data = json.loads(target_file.read_text(encoding="utf-8"))
    return _parse_target_data(data)

def get_armed_target_from_sha(sha: str) -> tuple[str, str, int, str]:
    import json
    import subprocess
    try:
        out = subprocess.check_output(["git", "show", f"{sha}:release_target.json"])
        data = json.loads(out)
        return _parse_target_data(data)
    except subprocess.CalledProcessError:
        try:
            # Fallback to github raw
            out = subprocess.check_output(["gh", "api", f"repos/Valeneko-pranmong/Neko-Family-Proxy/contents/release_target.json?ref={sha}", "-q", ".content"])
            import base64
            data = json.loads(base64.b64decode(out).decode('utf-8'))
            return _parse_target_data(data)
        except Exception as e:
            raise ValueError(f"release_target.json not found in exact commit {sha}: {e}")

def get_armed_target_from_dir(source_dir: Path) -> tuple[str, str, int, str]:
    import json
    target_file = source_dir / "release_target.json"
    if not target_file.exists():
        raise ValueError("release_target.json not found in source directory")
    data = json.loads(target_file.read_text(encoding="utf-8"))
    return _parse_target_data(data)
