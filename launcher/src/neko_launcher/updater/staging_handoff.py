"""Broker staging and download handoff protocol coordinator."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from neko_launcher.updater.state_models import State


@dataclass(frozen=True)
class RequestReadyResult:
    accepted: bool
    request_id: str | None = None
    transaction_id: str | None = None
    changed: dict[str, bool] | None = None
    error: str | None = None


@dataclass(frozen=True)
class ApplyResult:
    accepted: bool
    error: str | None = None


def handle_begin_request(
    root_dir: Path,
    current_state: State,
    envelope_b64: str,
    public_keys: Mapping[str, bytes],
) -> tuple[RequestReadyResult, State | None]:
    """Handle BEGIN from Launcher, authenticate envelope, create incoming dir, and formulate next State."""
    raise NotImplementedError("handle_begin_request not implemented")


def handle_apply_request(
    root_dir: Path,
    current_state: State,
    transaction_id: str,
    request_id: str,
) -> ApplyResult:
    """Handle APPLY from Launcher, verify on-disk artifacts match expected hashes, and formulate next State."""
    raise NotImplementedError("handle_apply_request not implemented")
