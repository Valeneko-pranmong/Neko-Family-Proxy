from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Protocol, Sequence

try:
    from scripts.project_release_audit_ledger import (
        ReleaseAuditEvent,
    )
    from scripts.verify_human_release_assets import (
        CANONICAL_HUMAN_REPO,
        FORBIDDEN_HUMAN_ASSETS,
        REQUIRED_HUMAN_ASSET,
        REQUIRED_HUMAN_ASSETS,
    )
except ModuleNotFoundError:
    from project_release_audit_ledger import (  # type: ignore[no-redef]
        ReleaseAuditEvent,
    )
    from verify_human_release_assets import (  # type: ignore[no-redef]
        CANONICAL_HUMAN_REPO,
        FORBIDDEN_HUMAN_ASSETS,
        REQUIRED_HUMAN_ASSET,
        REQUIRED_HUMAN_ASSETS,
    )

__all__ = [
    "CANONICAL_HUMAN_REPO",
    "CommandExecutor",
    "FORBIDDEN_HUMAN_ASSETS",
    "HumanPublishError",
    "HumanPublishResult",
    "InstallerPublishError",
    "REQUIRED_HUMAN_ASSET",
    "REQUIRED_HUMAN_ASSETS",
    "main",
    "publish_human_release",
]

class HumanPublishError(Exception):
    """Raised when canonical human release staging, precondition check, or publication fails."""

InstallerPublishError = HumanPublishError

class HumanPublishResult:
    pass

class CommandExecutor(Protocol):
    def run(self, args: list[str], *, capture_output: bool = True, stdout: Any = None, check: bool = False) -> Any: ...

def publish_human_release(
    *,
    tag: str,
    target_commit: str,
    installer_path: Path | str,
    body: str,
    deletion_evidence: ReleaseAuditEvent,
    executor: CommandExecutor | None = None,
    repo: str = CANONICAL_HUMAN_REPO,
    title: str | None = None,
) -> HumanPublishResult:
    """Publish canonical human release from validated draft."""
    raise HumanPublishError("Normal 5.x human releases are superseded by unified canonical releases. See publish_unified_release.")

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish canonical human release from validated draft",
        allow_abbrev=False,
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--installer-path", required=True, type=Path)
    parser.add_argument("--body-file", required=True, type=Path)
    parser.add_argument("--audit-ledger", required=True, type=Path)
    parser.add_argument("--repo", default=CANONICAL_HUMAN_REPO)
    parser.add_argument("--title")
    return parser.parse_args(argv)

def main(argv: Sequence[str] | None = None) -> int:
    parse_args(argv)
    raise HumanPublishError("Normal 5.x human releases are superseded by unified canonical releases. See publish_unified_release.")

if __name__ == "__main__":
    import sys
    sys.exit(main())
