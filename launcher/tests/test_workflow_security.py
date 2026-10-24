from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
_ACTION_PIN = re.compile(r"@[0-9a-f]{40}(?:\s|$)")


def _workflow_paths() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.yml"))


def test_all_workflow_actions_are_pinned_to_full_commit_shas() -> None:
    for path in _workflow_paths():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "uses:" in line and "actions/" in line:
                assert _ACTION_PIN.search(line), (
                    f"{path.name}: unpinned action: {line.strip()}"
                )


def _checkout_blocks(text: str):
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "uses: actions/checkout@" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        block = [line]
        for candidate in lines[index + 1 :]:
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate.strip() and candidate_indent <= indent:
                break
            block.append(candidate)
        yield "\n".join(block)


def test_checkout_steps_do_not_persist_credentials() -> None:
    for path in _workflow_paths():
        blocks = list(_checkout_blocks(path.read_text(encoding="utf-8")))
        assert blocks, f"{path.name} has no checkout step"
        for block in blocks:
            assert "persist-credentials: false" in block, (
                f"{path.name}: checkout step persists credentials:\n{block}"
            )
