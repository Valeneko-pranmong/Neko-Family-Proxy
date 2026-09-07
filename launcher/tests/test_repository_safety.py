from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
SAFETY_SCRIPT = REPOSITORY_ROOT / "scripts" / "check_repository_safety.py"


def load_safety_module():
    spec = importlib.util.spec_from_file_location("check_repository_safety", SAFETY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployable_legacy_email_recovery_is_rejected() -> None:
    safety = load_safety_module()

    errors = safety.validate_repository_contracts()

    assert not any("legacy email recovery" in error for error in errors)


def test_beta_installer_installs_updater_beside_launcher() -> None:
    installer = (REPOSITORY_ROOT / "installer" / "beta.iss").read_text(
        encoding="utf-8"
    )
    files_section = installer.split("[Files]", 1)[1].split("[", 1)[0]
    normalized = " ".join(files_section.lower().split())

    assert (
        'source: "{#payloaddir}\\nekoupdater.exe"' in normalized
        and 'destdir: "{app}"' in normalized
    ), "beta.iss must install {#PayloadDir}\\NekoUpdater.exe into {app}"


def test_beta_build_orchestrator_gates_updater_payload() -> None:
    orchestrator = (
        REPOSITORY_ROOT / "installer" / "scripts" / "build_beta_installer.py"
    ).read_text(encoding="utf-8")
    lowered = orchestrator.lower()
    updater_contexts = [
        lowered[max(0, match.start() - 300) : match.end() + 300]
        for match in re.finditer(r"nekoupdater\.exe", lowered)
    ]

    assert updater_contexts, (
        "build_beta_installer.py lacks staged PAYLOAD/NekoUpdater.exe path"
    )
    assert any("payload" in context for context in updater_contexts), (
        "build_beta_installer.py must stage NekoUpdater.exe from PAYLOAD"
    )
    assert any(
        any(gate in context for gate in ("isfile", "is_file", "exists", "sha256"))
        for context in updater_contexts
    ), "build_beta_installer.py must gate or record NekoUpdater.exe"


def test_release_workflow_builds_and_carries_updater_without_legacy_iss() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    lowered = workflow.lower()
    missing = []
    if "nekoupdater.spec" not in lowered:
        missing.append("NekoUpdater.spec build")
    if "launcher\\dist\\nekoupdater.exe" not in lowered:
        missing.append("launcher\\dist\\NekoUpdater.exe staging/copy")
    if "installer\\nekolauncher.iss" in lowered:
        missing.append("removal of nonexistent installer\\NekoLauncher.iss reference")

    assert not missing, "release.yml lacks: " + ", ".join(missing)