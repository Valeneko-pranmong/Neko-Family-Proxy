"""Tests verifying removal of obsolete distribution grant and software update client."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

INFRA_PACKAGE = "neko_launcher.infrastructure"
CLIENT_MODULE = "neko_launcher.infrastructure.software_update_client"


def test_obsolete_software_update_client_module_is_removed() -> None:
    """The obsolete Admin software_update_client module must be removed."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(CLIENT_MODULE)


def test_no_obsolete_grant_gateway_symbols() -> None:
    """Infrastructure and client must not export ArtifactGrant or HttpArtifactGrantGateway."""
    infra = importlib.import_module(INFRA_PACKAGE)
    assert not hasattr(infra, "ArtifactGrant")
    assert not hasattr(infra, "HttpArtifactGrantGateway")
    assert not hasattr(infra, "HttpUpdateManifestGateway")

    try:
        client = importlib.import_module(CLIENT_MODULE)
    except ModuleNotFoundError:
        return
    assert not hasattr(client, "ArtifactGrant"), "ArtifactGrant must be removed"
    assert not hasattr(client, "HttpArtifactGrantGateway"), "HttpArtifactGrantGateway must be removed"
    assert not hasattr(client, "HttpUpdateManifestGateway"), "HttpUpdateManifestGateway must be removed"


def test_no_neko_distribution_capability_grammar() -> None:
    """No NekoDistribution authorization grammar or capability handling in client."""
    try:
        client = importlib.import_module(CLIENT_MODULE)
    except ModuleNotFoundError:
        return
    client_file = getattr(client, "__file__", None)
    assert client_file is not None
    source = Path(client_file).read_text(encoding="utf-8")
    assert "NekoDistribution" not in source, "NekoDistribution authorization grammar must be removed"
    assert "grant_core" not in source, "Core capability grant method must be removed"


def test_no_legacy_grant_or_manifest_endpoints() -> None:
    """No legacy Admin grant or manifest route constants in client."""
    try:
        client = importlib.import_module(CLIENT_MODULE)
    except ModuleNotFoundError:
        return
    client_file = getattr(client, "__file__", None)
    assert client_file is not None
    source = Path(client_file).read_text(encoding="utf-8")
    assert "/api/software-update/artifact-grant" not in source, "Legacy grant route must be removed"
    assert "/api/software-update/manifest" not in source, "Legacy manifest route must be removed"
