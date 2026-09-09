from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def indented_block(text: str, key: str, indent: int) -> str:
    lines = text.splitlines()
    pattern = re.compile(rf"^{' ' * indent}{re.escape(key)}:\s*(?:#.*)?$")
    for index, line in enumerate(lines):
        if not pattern.match(line):
            continue
        block = [line]
        for candidate in lines[index + 1 :]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                break
            block.append(candidate)
        return "\n".join(block)
    raise AssertionError(f"release.yml is missing the {key!r} mapping")


def scalar(block: str, key: str) -> str | None:
    match = re.search(rf"(?mi)^\s*{re.escape(key)}:\s*([^#\n]+?)\s*$", block)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def input_names(inputs: str) -> set[str]:
    return set(re.findall(r"(?m)^      ([A-Za-z0-9_-]+):\s*$", inputs))


def job(text: str, name: str) -> str:
    return indented_block(indented_block(text, "jobs", 0), name, 2)


def test_dispatch_has_only_immutable_publication_authority_inputs() -> None:
    dispatch = indented_block(indented_block(workflow_text(), "on", 0), "workflow_dispatch", 2)
    inputs = indented_block(dispatch, "inputs", 4)

    assert input_names(inputs) == {
        "publish_release",
        "release_id",
        "release_tag",
        "expected_target",
    }
    assert {
        "core_artifact_path",
        "signed_manifest_path",
        "release_public_key_path",
    }.isdisjoint(input_names(inputs))

    expected_contract = {
        "publish_release": {"required": "true", "type": "boolean", "default": "false"},
        "release_id": {"required": "true", "type": "string", "default": None},
        "release_tag": {"required": "true", "type": "string", "default": None},
        "expected_target": {"required": "true", "type": "string", "default": None},
    }
    for name, expected_metadata in expected_contract.items():
        input_block = indented_block(inputs, name, 6)
        assert {
            metadata: scalar(input_block, metadata)
            for metadata in ("required", "type", "default")
        } == expected_metadata


def test_build_installer_is_read_only_and_tag_push_only() -> None:
    text = workflow_text()
    build = job(text, "build-installer")
    push = indented_block(indented_block(text, "on", 0), "push", 2)

    assert scalar(build, "if") == "github.event_name == 'push'"
    assert scalar(indented_block(build, "permissions", 4), "contents") == "read"
    assert re.search(r"(?m)^\s+-\s*['\"]?v\*['\"]?\s*$", push)


def test_publication_job_is_independent_and_manually_authorized() -> None:
    publication = job(workflow_text(), "publish-release")

    assert not re.search(r"(?m)^\s+needs:\s*build-installer\s*$", publication)
    assert scalar(publication, "if") == (
        "github.event_name == 'workflow_dispatch' && inputs.publish_release == true"
    )
    assert scalar(indented_block(publication, "permissions", 4), "contents") == "write"


def test_publication_checks_out_exact_expected_target() -> None:
    publication = job(workflow_text(), "publish-release")
    checkout = next(
        step
        for step in re.split(r"(?m)(?=^      - )", publication)
        if "uses: actions/checkout@v6" in step
    )

    assert re.search(
        r"(?m)^\s+ref:\s*\$\{\{\s*inputs\.expected_target\s*}}\s*$", checkout
    )


def test_publication_locally_validates_all_authority_inputs() -> None:
    publication = job(workflow_text(), "publish-release")

    for name in ("release_id", "release_tag", "expected_target"):
        assert f"${{{{ inputs.{name} }}}}" in publication
    assert "^[0-9]+$" in publication
    assert "^v[0-9]+\\.[0-9]+\\.[0-9]+[0-9A-Za-z.-]*$" in publication
    assert "v5.1.0" in publication
    assert "^[0-9a-fA-F]{40}$" in publication
    assert ".ToLowerInvariant()" in publication


def test_publication_validates_the_actual_local_checkout_head() -> None:
    publication = job(workflow_text(), "publish-release")

    assert re.search(r"(?im)git\s+rev-parse\s+HEAD", publication)
    assert re.search(r"(?m)\$checkedOutSha\s*=.*git\s+rev-parse\s+HEAD", publication)
    assert re.search(r"(?m)\$LASTEXITCODE\s+-ne\s+0", publication)
    assert re.search(
        r"(?m)\$checkedOutSha\s+-notmatch\s+['\"]\^\[0-9a-fA-F\]\{40\}\$['\"]",
        publication,
    )
    assert "CHECKED_OUT_SHA:" not in publication
    assert "${{ github.sha }}" not in publication
    assert "$env:CHECKED_OUT_SHA" not in publication


def test_publication_does_not_build_transfer_stage_or_create_release_assets() -> None:
    publication = job(workflow_text(), "publish-release")
    lowered = publication.lower()

    assert "pyinstaller" not in lowered
    assert ".spec" not in lowered
    assert "actions/download-artifact" not in lowered
    assert "gh release create" not in lowered
    assert "gh release upload" not in lowered
    assert "stage approved update assets" not in lowered
    assert "repos/$env:gh_repo/releases/tags/" not in lowered
