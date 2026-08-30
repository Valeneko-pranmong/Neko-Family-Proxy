"""Phase 1 RED tests for semantic network presentation-domain models.

These tests are derived from ``docs/current/dashboard-redesign-plan.md`` v1.2,
sections 4.2 and 1.3. They intentionally cover the smallest contract needed
for the foundation phase:

* ``NetworkHopRole`` is a ``str``/``Enum`` with the four semantic roles.
* ``HopConnectionState`` is a ``str``/``Enum`` with three states.
* ``NetworkHop`` and ``NetworkPath`` are immutable (frozen) dataclasses.
* ``NetworkPath`` accepts an empty tuple, a valid 4-role path, and an optional
  ``proxy_rtt_ms`` of ``None``, ``0``, or a positive integer.
* ``NetworkPath`` rejects a negative ``proxy_rtt_ms`` with ``ValueError``.
* Neither dataclass introduces raw ``ip``, ``hostname``, ``port``, ``bangkok``,
  or ``per_hop_latency_ms`` fields.

Phase 1 must not add a producer for ``proxy_rtt_ms``; the default is ``None``.

Import shape (Phase 1 TDD repair)
---------------------------------
The Phase 1 symbols are intentionally NOT imported at module-import time.
Tests resolve them through helper functions on the ``models`` module so that a
missing symbol produces a normal ``pytest.fail`` assertion failure (or an
``AttributeError`` inside the test body) instead of an ``ImportError`` during
collection. This keeps the RED phase a true failing-test signal rather than a
collection / test-framework error.
"""

from __future__ import annotations

import dataclasses
from enum import Enum

import pytest

from neko_launcher.domain import models as domain_models


_FORBIDDEN_FIELDS = {"ip", "hostname", "port", "bangkok", "per_hop_latency_ms"}


# ---------------------------------------------------------------------------
# Symbol resolution helpers
# ---------------------------------------------------------------------------


def _require_symbol(name: str) -> object:
    """Return ``domain_models.<name>`` or fail the test if it is missing.

    A missing Phase 1 symbol becomes a regular assertion failure here, NOT a
    collection-time ``ImportError``.
    """
    symbol = getattr(domain_models, name, None)
    if symbol is None:
        pytest.fail(
            f"Phase 1 production symbol {name!r} is missing from "
            f"neko_launcher.domain.models (required by plan v1.2 §4.2 / §1.3)"
        )
    return symbol


def _require_attr(owner: object, name: str) -> object:
    attr = getattr(owner, name, None)
    if attr is None:
        pytest.fail(
            f"Phase 1 production attribute {name!r} is missing on "
            f"{owner!r} (required by plan v1.2 §4.2 / §1.3)"
        )
    return attr


# ---------------------------------------------------------------------------
# NetworkHopRole
# ---------------------------------------------------------------------------


def test_network_hop_role_is_str_enum() -> None:
    cls = _require_symbol("NetworkHopRole")
    assert isinstance(cls, type), "NetworkHopRole must be a class"
    assert issubclass(cls, Enum), "NetworkHopRole must be an Enum"
    assert issubclass(cls, str), "NetworkHopRole must be a str subclass"


def test_network_hop_role_members() -> None:
    cls = _require_symbol("NetworkHopRole")
    # Resolve each member by name; missing => normal pytest fail.
    local_device = _require_attr(cls, "LOCAL_DEVICE")
    local_proxy_engine = _require_attr(cls, "LOCAL_PROXY_ENGINE")
    remote_proxy = _require_attr(cls, "REMOTE_PROXY")
    game_network = _require_attr(cls, "GAME_NETWORK")
    assert local_device == "local_device"
    assert local_proxy_engine == "local_proxy_engine"
    assert remote_proxy == "remote_proxy"
    assert game_network == "game_network"
    assert {member.value for member in cls} == {
        "local_device",
        "local_proxy_engine",
        "remote_proxy",
        "game_network",
    }


def test_network_hop_role_constructs_from_str_value() -> None:
    cls = _require_symbol("NetworkHopRole")
    # str mix-in allows construction by value.
    assert cls("local_device") is _require_attr(cls, "LOCAL_DEVICE")
    assert cls("game_network") is _require_attr(cls, "GAME_NETWORK")


# ---------------------------------------------------------------------------
# HopConnectionState
# ---------------------------------------------------------------------------


def test_hop_connection_state_is_str_enum() -> None:
    cls = _require_symbol("HopConnectionState")
    assert isinstance(cls, type), "HopConnectionState must be a class"
    assert issubclass(cls, Enum), "HopConnectionState must be an Enum"
    assert issubclass(cls, str), "HopConnectionState must be a str subclass"


def test_hop_connection_state_members() -> None:
    cls = _require_symbol("HopConnectionState")
    success = _require_attr(cls, "SUCCESS")
    connecting = _require_attr(cls, "CONNECTING")
    unavailable = _require_attr(cls, "UNAVAILABLE")
    assert success == "success"
    assert connecting == "connecting"
    assert unavailable == "unavailable"
    assert {member.value for member in cls} == {
        "success",
        "connecting",
        "unavailable",
    }


# ---------------------------------------------------------------------------
# NetworkHop (frozen/immutable)
# ---------------------------------------------------------------------------


def test_network_hop_is_frozen_dataclass() -> None:
    cls = _require_symbol("NetworkHop")
    assert dataclasses.is_dataclass(cls), "NetworkHop must be a dataclass"
    assert cls.__dataclass_params__.frozen is True, "NetworkHop must be frozen"


def test_network_hop_minimal_construction() -> None:
    NetworkHopRole = _require_symbol("NetworkHopRole")
    HopConnectionState = _require_symbol("HopConnectionState")
    NetworkHop = _require_symbol("NetworkHop")
    hop = NetworkHop(
        role=_require_attr(NetworkHopRole, "LOCAL_DEVICE"),
        label="Your device",
    )
    assert hop.role is _require_attr(NetworkHopRole, "LOCAL_DEVICE")
    assert hop.label == "Your device"
    # Plan §4.2 defaults
    assert hop.location is None
    assert hop.connection_state is _require_attr(HopConnectionState, "UNAVAILABLE")


def test_network_hop_full_construction() -> None:
    NetworkHopRole = _require_symbol("NetworkHopRole")
    HopConnectionState = _require_symbol("HopConnectionState")
    NetworkHop = _require_symbol("NetworkHop")
    hop = NetworkHop(
        role=_require_attr(NetworkHopRole, "REMOTE_PROXY"),
        label="Neko Proxy",
        location="Japan/Tokyo",
        connection_state=_require_attr(HopConnectionState, "SUCCESS"),
    )
    assert hop.location == "Japan/Tokyo"
    assert hop.connection_state is _require_attr(HopConnectionState, "SUCCESS")


def test_network_hop_is_immutable() -> None:
    NetworkHopRole = _require_symbol("NetworkHopRole")
    NetworkHop = _require_symbol("NetworkHop")
    hop = NetworkHop(role=_require_attr(NetworkHopRole, "LOCAL_DEVICE"), label="Device")
    with pytest.raises(dataclasses.FrozenInstanceError):
        hop.label = "Other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NetworkPath (frozen/immutable, validation)
# ---------------------------------------------------------------------------


def test_network_path_is_frozen_dataclass() -> None:
    cls = _require_symbol("NetworkPath")
    assert dataclasses.is_dataclass(cls), "NetworkPath must be a dataclass"
    assert cls.__dataclass_params__.frozen is True, "NetworkPath must be frozen"


def test_network_path_default_is_empty_and_valid() -> None:
    NetworkPath = _require_symbol("NetworkPath")
    path = NetworkPath()
    assert path.hops == ()
    assert path.proxy_rtt_ms is None


def test_network_path_accepts_full_four_role_path() -> None:
    NetworkHopRole = _require_symbol("NetworkHopRole")
    NetworkHop = _require_symbol("NetworkHop")
    NetworkPath = _require_symbol("NetworkPath")
    path = NetworkPath(
        hops=(
            NetworkHop(role=_require_attr(NetworkHopRole, "LOCAL_DEVICE"), label="Your device"),
            NetworkHop(
                role=_require_attr(NetworkHopRole, "LOCAL_PROXY_ENGINE"),
                label="Neko Proxy Engine",
            ),
            NetworkHop(
                role=_require_attr(NetworkHopRole, "REMOTE_PROXY"),
                label="Neko Proxy",
                location="Japan/Tokyo",
            ),
            NetworkHop(
                role=_require_attr(NetworkHopRole, "GAME_NETWORK"),
                label="PSO2 JP",
            ),
        ),
    )
    assert len(path.hops) == 4
    assert path.hops[0].role is _require_attr(NetworkHopRole, "LOCAL_DEVICE")
    assert path.hops[-1].role is _require_attr(NetworkHopRole, "GAME_NETWORK")


def test_network_path_rtt_none_is_valid_unknown() -> None:
    NetworkPath = _require_symbol("NetworkPath")
    path = NetworkPath(proxy_rtt_ms=None)
    assert path.proxy_rtt_ms is None


def test_network_path_rtt_zero_is_valid_measured_value() -> None:
    NetworkPath = _require_symbol("NetworkPath")
    path = NetworkPath(proxy_rtt_ms=0)
    assert path.proxy_rtt_ms == 0


def test_network_path_rtt_positive_is_valid() -> None:
    NetworkPath = _require_symbol("NetworkPath")
    path = NetworkPath(proxy_rtt_ms=42)
    assert path.proxy_rtt_ms == 42


def test_network_path_rtt_negative_raises_value_error() -> None:
    NetworkPath = _require_symbol("NetworkPath")
    with pytest.raises(ValueError):
        NetworkPath(proxy_rtt_ms=-1)


def test_network_path_is_immutable() -> None:
    NetworkPath = _require_symbol("NetworkPath")
    path = NetworkPath()
    with pytest.raises(dataclasses.FrozenInstanceError):
        path.proxy_rtt_ms = 10  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Privacy / invariant: no raw network-address or per-hop-latency fields
# ---------------------------------------------------------------------------


def _all_field_names(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def test_network_hop_has_no_forbidden_raw_address_fields() -> None:
    NetworkHop = _require_symbol("NetworkHop")
    assert _all_field_names(NetworkHop).isdisjoint(_FORBIDDEN_FIELDS)


def test_network_path_has_no_forbidden_raw_address_fields() -> None:
    NetworkPath = _require_symbol("NetworkPath")
    assert _all_field_names(NetworkPath).isdisjoint(_FORBIDDEN_FIELDS)
