from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


@dataclass(frozen=True)
class Job:
    name: str
    text: str


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def indented_block(text: str, key: str, indent: int) -> str:
    lines = text.splitlines()
    start_pattern = re.compile(rf"^{' ' * indent}{re.escape(key)}:\s*(?:#.*)?$")
    for index, line in enumerate(lines):
        if not start_pattern.match(line):
            continue
        block = [line]
        for candidate in lines[index + 1 :]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                break
            block.append(candidate)
        return "\n".join(block)
    raise AssertionError(f"release.yml is missing the {key!r} mapping")


def jobs(text: str) -> list[Job]:
    jobs_block = indented_block(text, "jobs", 0)
    headings = list(re.finditer(r"(?m)^  ([A-Za-z0-9_-]+):\s*$", jobs_block))
    return [
        Job(
            match.group(1),
            jobs_block[match.start() : headings[index + 1].start()]
            if index + 1 < len(headings)
            else jobs_block[match.start() :],
        )
        for index, match in enumerate(headings)
    ]


def publication_jobs(text: str) -> list[Job]:
    return [job for job in jobs(text) if "gh release create" in job.text.lower()]


def scalar(block: str, key: str) -> str | None:
    match = re.search(rf"(?mi)^\s*{re.escape(key)}:\s*([^#\n]+?)\s*$", block)
    return match.group(1).strip(" '\"") if match else None


def assert_manual_publish_expression(expression: str, *, location: str) -> None:
    normalized = " ".join(expression.lower().split())
    has_manual_event = bool(
        re.search(
            r"github\.event_name\s*==\s*['\"]workflow_dispatch['\"]",
            normalized,
        )
    )
    has_explicit_opt_in = bool(
        re.search(
            r"(?:inputs|github\.event\.inputs)\.publish_release\s*==\s*"
            r"(?:true|['\"]true['\"])",
            normalized,
        )
    )
    assert has_manual_event and has_explicit_opt_in, (
        "tag push can reach release publication: "
        f"{location} must require github.event_name == 'workflow_dispatch' AND "
        "publish_release == true"
    )


def test_tag_push_remains_a_candidate_build_trigger() -> None:
    text = workflow_text()
    push = indented_block(indented_block(text, "on", 0), "push", 2)

    assert re.search(r"(?m)^\s+-\s*['\"]?v\*['\"]?\s*$", push), (
        "release.yml must retain the v* tag-push candidate-build trigger"
    )


def test_candidate_build_preserves_launcher_and_updater_outputs() -> None:
    text = workflow_text()
    candidate_jobs = [
        job
        for job in jobs(text)
        if "NekoLauncher.spec" in job.text and "actions/upload-artifact@" in job.text
    ]
    assert len(candidate_jobs) == 1, (
        "exactly one candidate job must build NekoLauncher.spec and upload its output"
    )
    candidate = candidate_jobs[0].text

    required = {
        "launcher build": "NekoLauncher.spec",
        "updater build": "NekoUpdater.spec",
        "updater self-check": "NekoUpdater.exe --self-check",
        "updater carry into release": "launcher\\dist\\NekoUpdater.exe",
        "checksum manifest": "SHA256SUMS.txt",
        "candidate artifact upload": "actions/upload-artifact@",
    }
    missing = [label for label, marker in required.items() if marker not in candidate]
    assert not missing, "candidate build is missing: " + ", ".join(missing)
    assert "installer\\NekoLauncher.iss" not in candidate, (
        "candidate build must preserve Unit Task5 removal of the legacy installer spec"
    )


def test_tag_push_and_ordinary_push_cannot_publish_a_release() -> None:
    text = workflow_text()
    publishers = publication_jobs(text)
    assert publishers, "release.yml must retain a GitHub release publication path"

    for publisher in publishers:
        job_if = scalar(publisher.text, "if")
        if job_if is not None:
            assert_manual_publish_expression(job_if, location=f"job {publisher.name!r} if")
            continue

        release_step = publisher.text.lower().split("gh release create", 1)[0]
        step_if_matches = list(re.finditer(r"(?mi)^\s*if:\s*(.+?)\s*$", release_step))
        expression = step_if_matches[-1].group(1) if step_if_matches else ""
        assert_manual_publish_expression(
            expression,
            location=f"the gh release create step in job {publisher.name!r}",
        )


def test_manual_dispatch_requires_false_by_default_boolean_opt_in() -> None:
    dispatch = indented_block(indented_block(workflow_text(), "on", 0), "workflow_dispatch", 2)
    inputs = indented_block(dispatch, "inputs", 4)
    publish_release = indented_block(inputs, "publish_release", 6)

    assert scalar(publish_release, "type") == "boolean", (
        "workflow_dispatch.publish_release must be a boolean input"
    )
    assert scalar(publish_release, "default") == "false", (
        "workflow_dispatch.publish_release must default to false"
    )


def test_only_publication_has_contents_write_permission() -> None:
    text = workflow_text()
    publishers = publication_jobs(text)
    assert publishers, "release.yml must have a publication job"

    top = text.split("\njobs:", 1)[0]
    top_permissions = indented_block(top, "permissions", 0) if "permissions:" in top else ""
    assert scalar(top_permissions, "contents") != "write", (
        "workflow-level contents: write also grants candidate builds publication authority"
    )

    publisher_names = {job.name for job in publishers}
    for job in jobs(text):
        permission = (
            scalar(indented_block(job.text, "permissions", 4), "contents")
            if re.search(r"(?m)^    permissions:\s*$", job.text)
            else scalar(top_permissions, "contents")
        )
        if job.name in publisher_names:
            assert permission == "write", f"publication job {job.name!r} needs contents: write"
        else:
            assert permission in {None, "read"}, (
                f"non-publication job {job.name!r} must not have contents: write"
            )


def test_publication_consumes_the_candidate_artifact_without_rebuilding() -> None:
    text = workflow_text()
    publishers = publication_jobs(text)
    assert publishers, "release.yml must have a publication job"
    uploads = re.findall(r"(?mi)^\s*name:\s*([^#\n]+?)\s*$", text)

    for publisher in publishers:
        lowered = publisher.text.lower()
        assert "actions/download-artifact@" in lowered, (
            f"publication job {publisher.name!r} must download the authorized candidate artifact"
        )
        assert "pyinstaller" not in lowered and ".spec" not in lowered, (
            f"publication job {publisher.name!r} must not independently rebuild candidates"
        )
        assert "sha256sums.txt" in lowered, (
            f"publication job {publisher.name!r} must publish the candidate checksum manifest"
        )
        assert any(name.strip(" '\"") in publisher.text for name in uploads), (
            f"publication job {publisher.name!r} must name an artifact produced by this workflow"
        )


def test_release_contract_requires_no_additional_secrets() -> None:
    assert not re.search(r"\bsecrets\s*\.", workflow_text(), re.IGNORECASE), (
        "the release contract must use scoped github.token permissions, not secrets.*"
    )
