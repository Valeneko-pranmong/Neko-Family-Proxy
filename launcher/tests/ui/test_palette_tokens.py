"""Phase 1 RED tests for semantic PinkPalette node tokens.

These tests are derived from ``docs/current/dashboard-redesign-plan.md`` v1.2,
sections 4.4 and 1.3. The dashboard plan requires the following semantic role
tokens, each as a strict ``#RRGGBB`` literal, with every role having a
matching surface token:

* ``node_local`` / ``node_local_surface``
* ``node_engine`` / ``node_engine_surface``
* ``node_remote`` / ``node_remote_surface``
* ``node_game`` / ``node_game_surface``

Token names must be semantic roles and must NOT encode raw address or
infrastructure fields (no IP, hostname, port, or city names).

Import shape (Phase 1 TDD repair)
---------------------------------
Phase 1 token attributes are intentionally NOT imported by name. Tests
resolve them through ``getattr`` on the ``PinkPalette`` / ``PALETTE`` objects
so that a missing token becomes a normal ``pytest.fail`` assertion failure
instead of an ``AttributeError`` raised during collection or test setup.
"""

from __future__ import annotations

import re

import pytest

from neko_launcher.ui import theme as ui_theme


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


_ROLE_SURFACE_PAIRS: tuple[tuple[str, str], ...] = (
    ("node_local", "node_local_surface"),
    ("node_engine", "node_engine_surface"),
    ("node_remote", "node_remote_surface"),
    ("node_game", "node_game_surface"),
)


_FORBIDDEN_TOKEN_SUBSTRINGS = (
    "ip",
    "host",
    "port",
    "bangkok",
    "tokyo",
    "pso2_server",
    "address",
    "endpoint",
)


# ---------------------------------------------------------------------------
# Required tokens exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token_name", [name for pair in _ROLE_SURFACE_PAIRS for name in pair])
def test_required_palette_token_exists(token_name: str) -> None:
    PinkPalette = getattr(ui_theme, "PinkPalette", None)
    if PinkPalette is None:
        pytest.fail("PinkPalette is missing from neko_launcher.ui.theme")
    assert hasattr(PinkPalette, token_name), (
        f"PinkPalette is missing required Phase 1 token: {token_name!r}"
    )


# ---------------------------------------------------------------------------
# Every node token is a strict #RRGGBB
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token_name", [name for pair in _ROLE_SURFACE_PAIRS for name in pair])
def test_palette_token_is_strict_hex_color(token_name: str) -> None:
    PinkPalette = getattr(ui_theme, "PinkPalette", None)
    if PinkPalette is None:
        pytest.fail("PinkPalette is missing from neko_launcher.ui.theme")
    if not hasattr(PinkPalette, token_name):
        pytest.fail(f"Phase 1 token {token_name!r} is missing on PinkPalette")
    value = getattr(PinkPalette, token_name)
    assert isinstance(value, str), f"{token_name} must be a str"
    assert _HEX_COLOR.match(value), (
        f"{token_name} must be strict #RRGGBB, got {value!r}"
    )


@pytest.mark.parametrize(
    ("role_token", "surface_token"), _ROLE_SURFACE_PAIRS
)
def test_each_role_has_a_surface_counterpart(role_token: str, surface_token: str) -> None:
    PinkPalette = getattr(ui_theme, "PinkPalette", None)
    if PinkPalette is None:
        pytest.fail("PinkPalette is missing from neko_launcher.ui.theme")
    if not hasattr(PinkPalette, role_token):
        pytest.fail(f"Phase 1 token {role_token!r} is missing on PinkPalette")
    if not hasattr(PinkPalette, surface_token):
        pytest.fail(f"Phase 1 token {surface_token!r} is missing on PinkPalette")
    role_value = getattr(PinkPalette, role_token)
    surface_value = getattr(PinkPalette, surface_token)
    # Surface is a separate (and visually distinct) color from its role token.
    assert _HEX_COLOR.match(role_value)
    assert _HEX_COLOR.match(surface_value)
    assert role_value != surface_value


# ---------------------------------------------------------------------------
# Singleton PALETTE instance exposes the same tokens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token_name", [name for pair in _ROLE_SURFACE_PAIRS for name in pair])
def test_palette_singleton_exposes_node_tokens(token_name: str) -> None:
    palette = getattr(ui_theme, "PALETTE", None)
    if palette is None:
        pytest.fail("PALETTE singleton is missing from neko_launcher.ui.theme")
    assert hasattr(palette, token_name), (
        f"PALETTE singleton is missing required Phase 1 token: {token_name!r}"
    )


# ---------------------------------------------------------------------------
# Semantic naming: tokens are roles, not raw address fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token_name", [name for pair in _ROLE_SURFACE_PAIRS for name in pair])
def test_node_token_names_are_semantic_roles(token_name: str) -> None:
    lowered = token_name.lower()
    for forbidden in _FORBIDDEN_TOKEN_SUBSTRINGS:
        assert forbidden not in lowered, (
            f"token {token_name!r} encodes a raw address/infrastructure field "
            f"({forbidden!r}); use a semantic role instead"
        )
