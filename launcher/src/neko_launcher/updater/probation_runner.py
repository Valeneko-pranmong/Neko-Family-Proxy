"""Candidate probation runner executing credential-free self-test."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SelfTestResult:
    passed: bool
    error_code: str | None = None
    reason: str | None = None


def run_probation_self_test(
    generation_dir: Path,
    skip_tk: bool = False,
    core_preflight_timeout_s: float = 30.0,
) -> SelfTestResult:
    """Execute credential-free probation verifying own EXE, Core bundle, Core preflight, and Tk event loop."""
    raise NotImplementedError("run_probation_self_test not implemented")
