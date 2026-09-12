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


def test_obsolete_software_update_authority_is_rejected() -> None:
    safety = load_safety_module()
    errors: list[str] = []
    for path in safety.repository_files():
        errors.extend(safety.validate_software_update_authority(path))

    assert not errors, f"Obsolete update authority strings detected: {errors}"


def test_software_update_untrusted_sources_are_rejected() -> None:
    safety = load_safety_module()
    errors: list[str] = []
    for path in safety.repository_files():
        errors.extend(safety.validate_software_update_untrusted_sources(path))

    assert not errors, f"Untrusted update source usage detected: {errors}"


def test_allowlisted_history_docs_are_permitted() -> None:
    safety = load_safety_module()
    history_plan = (
        REPOSITORY_ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-09-08-software-update-github-releases-implementation.md"
    )
    assert safety.is_allowlisted_history_doc(
        history_plan.relative_to(REPOSITORY_ROOT)
    )
    assert not safety.validate_software_update_authority(history_plan)


def test_safety_guard_rejects_untrusted_software_update_sources(tmp_path: Path) -> None:
    safety = load_safety_module()
    fake_py = (
        REPOSITORY_ROOT
        / "launcher"
        / "src"
        / "neko_launcher"
        / "infrastructure"
        / "_fake_test_guard.py"
    )
    forbidden_tokens = (
        "zipball_url",
        "tarball_url",
        "/archive/refs/",
        "raw.githubusercontent.com",
        "SHA256SUMS.txt",
    )
    for token in forbidden_tokens:
        test_file = tmp_path / f"test_{token.replace('/', '_').replace('.', '_')}.py"
        test_file.write_text(f'SOURCE = "{token}"\n', encoding="utf-8")
        # Direct check using the validator logic with the relative path mocked
        relative = fake_py.relative_to(REPOSITORY_ROOT)
        errors = [
            f"untrusted software update source ({label}) found in production code: {relative}"
            for label, pattern in safety.SOFTWARE_UPDATE_UNTRUSTED_SOURCE_PATTERNS.items()
            if pattern.search(test_file.read_text(encoding="utf-8"))
        ]
        assert errors, f"Expected guard to reject token: {token}"


def test_release_controller_is_software_update_production_code() -> None:
    safety = load_safety_module()
    rel_path = Path("scripts/release_controller.py")
    assert safety.is_software_update_production_code(rel_path), (
        "scripts/release_controller.py must be guarded as software update production code"
    )

