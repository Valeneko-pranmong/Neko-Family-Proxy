from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from release_dependency_audit import (  # noqa: E402
    DependencyAuditEvidence,
    DependencyFinding,
    audit_old_installer_dependency,
    build_dependency_snapshot,
    verify_audit_freshness,
)



def fake_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "TestRunner"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    for rel_path, content in files.items():
        file_path = repo / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def test_runtime_reference_to_old_installer_repo_is_operational_blocker(
    tmp_path: Path,
) -> None:
    repo = fake_repo(
        tmp_path,
        {"src/config.py": 'REPO = "Neko-Family-Proxy-Installer"\n'},
    )
    evidence = audit_old_installer_dependency(
        repo, build_dependency_snapshot(repo, external_inputs={})
    )
    assert evidence.operational_matches
    assert not evidence.historical_allowed_matches
    finding = evidence.operational_matches[0]
    assert isinstance(finding, DependencyFinding)
    assert finding.path == "src/config.py"
    assert finding.line == 1
    assert finding.kind in {"direct_reference", "repository_name_reference"}
    assert finding.text_digest == hashlib.sha256('REPO = "Neko-Family-Proxy-Installer"'.encode("utf-8")).hexdigest()


def test_split_constant_reference_is_operational_blocker(tmp_path: Path) -> None:
    repo = fake_repo(
        tmp_path,
        {
            "scripts/release.py": (
                'OWNER = "Valeneko-pranmong"\n'
                'REPO = "Neko-Family-Proxy-Installer"\n'
                'TARGET = f"https://api.github.com/repos/{OWNER}/{REPO}"\n'
            )
        },
    )
    evidence = audit_old_installer_dependency(
        repo, build_dependency_snapshot(repo, external_inputs={})
    )
    assert evidence.operational_matches
    kinds = [m.kind for m in evidence.operational_matches]
    assert any("split" in k for k in kinds) or any("api" in k for k in kinds) or any("direct" in k for k in kinds)
    paths = [m.path for m in evidence.operational_matches]
    assert all(p == "scripts/release.py" for p in paths)


def test_current_doc_and_generated_config_are_operational_blockers(
    tmp_path: Path,
) -> None:
    gen_config = tmp_path / "generated_release.json"
    gen_config.write_text(
        json.dumps({"installer_repo": "Valeneko-pranmong/Neko-Family-Proxy-Installer"}),
        encoding="utf-8",
    )
    repo = fake_repo(
        tmp_path,
        {
            "docs/current/operator_guide.md": (
                "Download the legacy installer from Valeneko-pranmong/Neko-Family-Proxy-Installer.\n"
            ),
            "README.md": "Installer repo: Neko-Family-Proxy-Installer\n",
        },
    )
    evidence = audit_old_installer_dependency(
        repo,
        build_dependency_snapshot(
            repo, external_inputs={"generated_release": gen_config}
        ),
    )
    assert evidence.operational_matches
    operational_paths = {m.path for m in evidence.operational_matches}
    assert "docs/current/operator_guide.md" in operational_paths
    assert "README.md" in operational_paths
    assert "generated_release" in operational_paths or str(gen_config) in operational_paths


def test_historical_only_superseded_doc_is_classified_as_historical_allowed(
    tmp_path: Path,
) -> None:
    repo = fake_repo(
        tmp_path,
        {
            "docs/superpowers/plans/historical_plan.md": (
                "# Historical Plan\n"
                "SUPERSEDED: Note that Valeneko-pranmong/Neko-Family-Proxy-Installer was deleted.\n"
            ),
            "docs/archive/legacy_notes.md": (
                "Historical note regarding Neko-Family-Proxy-Installer retirement.\n"
            ),
        },
    )
    evidence = audit_old_installer_dependency(
        repo, build_dependency_snapshot(repo, external_inputs={})
    )
    assert not evidence.operational_matches
    assert len(evidence.historical_allowed_matches) >= 2
    historical_paths = {m.path for m in evidence.historical_allowed_matches}
    assert "docs/superpowers/plans/historical_plan.md" in historical_paths
    assert "docs/archive/legacy_notes.md" in historical_paths


def test_snapshot_freshness_fails_on_single_byte_change(tmp_path: Path) -> None:
    repo = fake_repo(
        tmp_path,
        {
            "src/clean.py": 'VALUE = "clean"\n',
            "docs/clean.md": "# Clean\n",
        },
    )
    snapshot = build_dependency_snapshot(repo, external_inputs={})
    evidence = audit_old_installer_dependency(repo, snapshot)
    assert not evidence.operational_matches
    assert verify_audit_freshness(repo, evidence, external_inputs={}) is True

    # Change one byte in audited file
    (repo / "src/clean.py").write_text('VALUE = "cleam"\n', encoding="utf-8")
    assert verify_audit_freshness(repo, evidence, external_inputs={}) is False


def test_snapshot_freshness_fails_on_external_input_change(tmp_path: Path) -> None:
    ext_file = tmp_path / "ext_cfg.json"
    ext_file.write_text('{"target": "clean"}', encoding="utf-8")
    repo = fake_repo(
        tmp_path,
        {"src/clean.py": 'VALUE = "clean"\n'},
    )
    snapshot = build_dependency_snapshot(
        repo, external_inputs={"ext_cfg": ext_file}
    )
    evidence = audit_old_installer_dependency(repo, snapshot)
    assert verify_audit_freshness(
        repo, evidence, external_inputs={"ext_cfg": ext_file}
    ) is True

    # Modify external input
    ext_file.write_text('{"target": "modified"}', encoding="utf-8")
    assert verify_audit_freshness(
        repo, evidence, external_inputs={"ext_cfg": ext_file}
    ) is False


def test_evidence_to_dict_and_from_dict_roundtrip(tmp_path: Path) -> None:
    repo = fake_repo(
        tmp_path,
        {"src/config.py": 'REPO = "Neko-Family-Proxy-Installer"\n'},
    )
    evidence = audit_old_installer_dependency(
        repo, build_dependency_snapshot(repo, external_inputs={})
    )
    as_dict = evidence.to_dict()
    restored = DependencyAuditEvidence.from_dict(as_dict)
    assert restored.input_snapshot_sha256 == evidence.input_snapshot_sha256
    assert restored.result_sha256 == evidence.result_sha256
    assert restored.approved_source_commit == evidence.approved_source_commit
    assert restored.tracked_tree_sha256 == evidence.tracked_tree_sha256
    assert len(restored.operational_matches) == len(evidence.operational_matches)
    assert restored.operational_matches[0].path == evidence.operational_matches[0].path
    assert restored.operational_matches[0].kind == evidence.operational_matches[0].kind


def test_cli_execution_with_json_out_and_exit_codes(tmp_path: Path) -> None:
    from release_dependency_audit import main as audit_main

    repo = fake_repo(
        tmp_path / "dirty",
        {"src/config.py": 'REPO = "Neko-Family-Proxy-Installer"\n'},
    )
    json_out = tmp_path / "artifacts" / "audit.json"
    exit_code = audit_main(["--repo", str(repo), "--json-out", str(json_out)])
    assert exit_code == 1
    assert json_out.is_file()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert len(data["operational_matches"]) == 1

    clean_repo = fake_repo(
        tmp_path / "clean",
        {"src/config.py": 'REPO = "clean"\n'},
    )
    clean_json_out = tmp_path / "artifacts" / "clean_audit.json"
    clean_exit = audit_main(
        ["--repo", str(clean_repo), "--json-out", str(clean_json_out)]
    )
    assert clean_exit == 0
    assert clean_json_out.is_file()
    clean_data = json.loads(clean_json_out.read_text(encoding="utf-8"))
    assert len(clean_data["operational_matches"]) == 0

