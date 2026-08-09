from __future__ import annotations

import pytest

from neko_launcher.application.production_authorization import (
    CURRENT_PRODUCTION_AUTHORIZATION,
    create_production_proxy_gateway,
)


def test_current_release_pins_the_same_s0_contract_as_core() -> None:
    gate = CURRENT_PRODUCTION_AUTHORIZATION

    assert gate.contract_id == "NEKO-AUTH-S0"
    assert gate.contract_revision == "s0-rc1"
    assert gate.contract_package_sha256 == (
        "6697351b6b280afc566fedaaa1a6cfe207b1ea1d803c2eb613b4c1a891e192df"
    )


def test_current_release_enables_complete_minimal_v1_authorization() -> None:
    gate = CURRENT_PRODUCTION_AUTHORIZATION

    assert gate.is_ready
    assert gate.blockers == ()


def test_ready_release_rejects_the_pending_gateway_factory() -> None:
    with pytest.raises(
        RuntimeError,
        match="approved production authorization adapters are composed in main",
    ):
        create_production_proxy_gateway()
