from __future__ import annotations

import sys
from uuid import uuid4

import pytest

from neko_launcher.main import (
    _acquire_instance_mutex,
    _release_instance_mutex,
)
from neko_launcher.infrastructure.unavailable_gateway import (
    AuthorizationPendingProxyGateway,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex behavior")
def test_instance_mutex_rejects_a_second_launcher_process() -> None:
    name = f"Local\\NekoFamilyProxyLauncher-Test-{uuid4()}"
    first = _acquire_instance_mutex(name)
    assert first is not None
    try:
        assert _acquire_instance_mutex(name) is None
    finally:
        _release_instance_mutex(first)

    replacement = _acquire_instance_mutex(name)
    assert replacement is not None
    _release_instance_mutex(replacement)


def test_pending_authorization_contract_fails_closed_without_starting_core() -> None:
    gateway = AuthorizationPendingProxyGateway()

    with pytest.raises(RuntimeError, match="authorization integration is unavailable"):
        gateway.start()

    gateway.stop()
