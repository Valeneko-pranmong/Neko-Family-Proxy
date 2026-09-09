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
        "candidate artifact upload": "actions/upload-artifact@",
    }
    missing = [label for label, marker in required.items() if marker not in candidate]
    assert not missing, "candidate build is missing: " + ", ".join(missing)
    assert "installer\\NekoLauncher.iss" not in candidate, (
        "candidate build must preserve Unit Task5 removal of the legacy installer spec"
    )


def test_candidate_build_and_publication_do_not_produce_or_publish_unsigned_checksum_file() -> None:
    text = workflow_text()
    assert "sha256sums.txt" not in text.lower(), (
        "release.yml must not assemble or publish unsigned SHA256SUMS.txt"
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
        assert any(name.strip(" '\"") in publisher.text for name in uploads), (
            f"publication job {publisher.name!r} must name an artifact produced by this workflow"
        )


def test_release_contract_requires_no_additional_secrets() -> None:
    assert not re.search(r"\bsecrets\s*\.", workflow_text(), re.IGNORECASE), (
        "the release contract must use scoped github.token permissions, not secrets.*"
    )


def test_publication_has_explicit_repository_context_without_checkout() -> None:
    publishers = publication_jobs(workflow_text())
    assert publishers, "release.yml must have a publication job"

    for publisher in publishers:
        has_checkout = "actions/checkout@" in publisher.text.lower()
        has_gh_repo = bool(
            re.search(
                r"(?mi)^\s*GH_REPO:\s*['\"]?\$\{\{\s*github\.repository\s*}}['\"]?\s*$",
                publisher.text,
            )
        )
        has_repo_argument = bool(
            re.search(
                r"(?i)gh\s+release\s+create\b[^\n]*--repo(?:=|\s+)"
                r"['\"]?\$\{\{\s*github\.repository\s*}}['\"]?",
                publisher.text,
            )
        )
        assert has_checkout or has_gh_repo or has_repo_argument, (
            f"publication job {publisher.name!r} must check out the repository or bind "
            "gh explicitly to ${{ github.repository }} via GH_REPO/--repo"
        )


def test_manual_release_tag_resolves_to_current_run_sha_before_publication() -> None:
    publishers = publication_jobs(workflow_text())
    assert publishers, "release.yml must have a publication job"

    for publisher in publishers:
        lowered = publisher.text.lower()
        local_resolution = bool(
            re.search(r"\bgit\s+rev-list\s+-n\s*1\b", lowered)
            or re.search(r"\bgit\s+rev-parse\b[^\n]*\^\{\}", lowered)
        )
        api_ref_resolution = "gh api" in lowered and "/git/ref/tags/" in lowered
        annotated_tag_peeling = "/git/tags/" in lowered
        resolves_tag_commit = local_resolution or (
            api_ref_resolution and annotated_tag_peeling
        )
        compares_with_run_sha = bool(
            re.search(
                r"(?mi)^.*(?:-eq|-ne|==|!=).*\$\{\{\s*github\.sha\s*}}.*$|"
                r"^.*\$\{\{\s*github\.sha\s*}}.*(?:-eq|-ne|==|!=).*$",
                publisher.text,
            )
        )
        uses_explicit_release_tag = bool(
            re.search(r"inputs\.release_tag|\bRELEASE_TAG\b", publisher.text)
        )
        assert resolves_tag_commit and compares_with_run_sha and uses_explicit_release_tag, (
            f"publication job {publisher.name!r} must resolve the explicit release_tag "
            "(including annotated-tag peeling) and concretely compare its commit to "
            "${{ github.sha }} before publication"
        )


def test_publication_passes_release_tag_via_environment_not_powershell_source() -> None:
    publishers = publication_jobs(workflow_text())
    assert publishers, "release.yml must have a publication job"

    for publisher in publishers:
        steps = re.split(r"(?m)(?=^      - )", publisher.text)
        publication_steps = [step for step in steps if "gh release create" in step.lower()]
        assert len(publication_steps) == 1, (
            f"publication job {publisher.name!r} must have exactly one gh release create step"
        )
        publication_step = publication_steps[0]
        run_match = re.search(r"(?m)^        run:\s*", publication_step)
        assert run_match, "the publication step must have PowerShell source"
        run_source = publication_step[run_match.start() :]

        direct_interpolations = (
            "${{ inputs.release_tag }}",
            "${{ github.event.inputs.release_tag }}",
        )
        assert all(value not in run_source for value in direct_interpolations), (
            "gh release create PowerShell source must not directly interpolate the release tag"
        )
        assert re.search(
            r"(?mi)^\s*RELEASE_TAG:\s*['\"]?\$\{\{\s*inputs\.release_tag\s*}}['\"]?\s*$",
            publication_step,
        ), "the publication step must map inputs.release_tag to RELEASE_TAG"
        assert re.search(
            r"(?i)\bgh\s+release\s+create\s+(?:['\"]\$env:RELEASE_TAG['\"]|\$env:RELEASE_TAG)(?=\s)",
            run_source,
        ), "gh release create must receive $env:RELEASE_TAG as its tag argument"


def test_publication_creates_draft_release_first() -> None:
    publishers = publication_jobs(workflow_text())
    assert publishers, "release.yml must have a publication job"
    for publisher in publishers:
        assert re.search(r"(?i)\bgh\s+release\s+create\b[^\n]*--draft\b", publisher.text), (
            f"publication job {publisher.name!r} must create the release with --draft"
        )


def test_publication_persists_and_requires_immutable_release_id() -> None:
    publishers = publication_jobs(workflow_text())
    assert publishers, "release.yml must have a publication job"
    for publisher in publishers:
        assert re.search(r"release_id=\$releaseId.*GITHUB_(?:OUTPUT|ENV)", publisher.text, re.DOTALL)
        assert re.search(r"(?mi)^\s*RELEASE_ID:\s*\$\{\{\s*(?:steps\.[^.]+\.outputs\.release_id|env\.release_id)\s*}}", publisher.text)
        assert re.search(r"(?i)if\s*\(-not\s+\$env:RELEASE_ID\)\s*\{[^}]*throw", publisher.text)


def test_publication_patches_verified_release_by_id_after_fresh_identity_check() -> None:
    publishers = publication_jobs(workflow_text())
    assert publishers, "release.yml must have a publication job"
    for publisher in publishers:
        create_idx = publisher.text.find("gh release create")
        verifier_idx = publisher.text.find("verify_github_release_assets.py")
        final_read_idx = publisher.text.rfind('releases/$env:RELEASE_ID')
        patch_match = re.search(
            r'gh api "repos/\$env:GH_REPO/releases/\$env:RELEASE_ID"\s+--method PATCH[^\n]*-f draft=false',
            publisher.text,
        )
        assert create_idx != -1 and verifier_idx != -1 and patch_match is not None
        assert create_idx < verifier_idx < patch_match.start() < final_read_idx
        assert 'gh release edit "$env:RELEASE_TAG"' not in publisher.text


def test_immediate_prepublication_readback_revalidates_exact_required_name_id_bindings() -> None:
    publisher = publication_jobs(workflow_text())[0].text
    patch_idx = publisher.find("--method PATCH")
    assert patch_idx != -1
    prepublish = publisher[publisher.rfind("- name:", 0, patch_idx) : patch_idx]
    assert 'releases/$env:RELEASE_ID' in prepublish
    for binding in (".id", ".draft", ".tag_name", ".target_commitish", ".assets"):
        assert binding in prepublish, f"pre-publication identity check must validate {binding}"

    required_names = (
        "NekoLauncher.exe",
        "NekoUpdater.exe",
        "NekoProxyCore.zip",
        "release-v2.json",
    )
    for name in required_names:
        assert name in prepublish
    assert "foreach ($requiredName in $requiredAssetNames)" in prepublish
    assert "$verifiedMatches.Count -ne 1" in prepublish
    assert "$currentMatches.Count -ne 1" in prepublish
    assert "[string]$verifiedMatches[0].id -cne [string]$currentMatches[0].id" in prepublish
    assert "$expectedAssetIds" not in prepublish
    assert "$actualAssetIds" not in prepublish
    assert "throw" in prepublish


def test_immediate_prepublication_binding_check_ignores_unrelated_extra_assets() -> None:
    publisher = publication_jobs(workflow_text())[0].text
    patch_idx = publisher.find("--method PATCH")
    prepublish = publisher[publisher.rfind("- name:", 0, patch_idx) : patch_idx]

    assert "$verified.assets | Where-Object { $_.name -ceq $requiredName }" in prepublish
    assert "$current.assets | Where-Object { $_.name -ceq $requiredName }" in prepublish
    assert "Compare-Object" not in prepublish
    assert "foreach ($asset in $current.assets)" not in prepublish
    assert "foreach ($asset in $verified.assets)" not in prepublish


def test_publication_runs_verifier_before_publish() -> None:
    publisher = publication_jobs(workflow_text())[0].text
    assert publisher.find("gh release create") < publisher.find(
        "verify_github_release_assets.py"
    ) < publisher.find("--method PATCH")
