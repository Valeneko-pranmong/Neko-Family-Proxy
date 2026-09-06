"""Early updater bootstrap dispatch hook before heavy application imports."""
from __future__ import annotations


def maybe_dispatch_updater_entry(argv: list[str]) -> bool:
    """Intercept --update-managed or --update-probation; returns True if fully handled and exiting."""
    raise NotImplementedError("maybe_dispatch_updater_entry not implemented")
