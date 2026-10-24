from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.derive_version import ReleaseTargetIntent  # noqa: E402
from scripts import release_controller  # noqa: E402


def _write_declared_source(root: Path, version: str) -> Path:
    source = root / "source"
    init_path = source / "launcher" / "src" / "neko_launcher" / "__init__.py"
    init_path.parent.mkdir(parents=True)
    init_path.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    pyproject_path = source / "launcher" / "pyproject.toml"
    pyproject_path.parent.mkdir(parents=True, exist_ok=True)
    pyproject_path.write_text(
        f'[project]\nname = "neko-family-launcher"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return source


def _armed(source_base: str, target: str) -> ReleaseTargetIntent:
    return ReleaseTargetIntent(source_base=source_base, target=target, intent="user_bug")


def test_exact_tag_is_authoritative_and_matches_declared_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.6")
    monkeypatch.setattr(
        release_controller,
        "_release_tag_at_commit",
        lambda repo_root, commit: "v5.1.6",
    )

    resolution = release_controller.resolve_release_version(
        source,
        tmp_path,
        "a" * 40,
        armed_target=_armed("v5.1.1", "v5.1.2"),
    )

    assert resolution.version_tag == "v5.1.6"
    assert resolution.version == "5.1.6"
    assert resolution.source_base_tag == "v5.1.5"
    assert resolution.source_base_version == "5.1.5"
    assert resolution.requires_injection is False
    assert resolution.version_source == "tag"


def test_tag_must_match_declared_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.5")
    monkeypatch.setattr(
        release_controller,
        "_release_tag_at_commit",
        lambda repo_root, commit: "v5.1.6",
    )

    with pytest.raises(ValueError, match="does not match declared launcher version"):
        release_controller.resolve_release_version(source, tmp_path, "a" * 40)


def test_tag_discovery_ignores_prerelease_tags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.6")
    monkeypatch.setattr(
        release_controller.subprocess,
        "check_output",
        lambda *args, **kwargs: "v5.1.6\nv5.1.6-rc1\n",
    )

    resolution = release_controller.resolve_release_version(source, tmp_path, "a" * 40)

    assert resolution.version_tag == "v5.1.6"
    assert resolution.version_source == "tag"


def test_multiple_stable_tags_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.6")
    monkeypatch.setattr(
        release_controller.subprocess,
        "check_output",
        lambda *args, **kwargs: "v5.1.6\nv5.1.7\n",
    )

    with pytest.raises(ValueError, match="multiple release tags"):
        release_controller.resolve_release_version(source, tmp_path, "a" * 40)


def test_pyproject_used_when_no_tag_and_matches_armed_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.7")
    monkeypatch.setattr(
        release_controller, "_release_tag_at_commit", lambda repo_root, commit: None
    )

    resolution = release_controller.resolve_release_version(
        source,
        tmp_path,
        "a" * 40,
        armed_target=_armed("v5.1.6", "v5.1.7"),
    )

    assert resolution.version_tag == "v5.1.7"
    assert resolution.source_base_tag == "v5.1.6"
    assert resolution.requires_injection is False
    assert resolution.version_source == "pyproject"


def test_pyproject_overrides_stale_armed_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.7")
    monkeypatch.setattr(
        release_controller, "_release_tag_at_commit", lambda repo_root, commit: None
    )

    resolution = release_controller.resolve_release_version(
        source,
        tmp_path,
        "a" * 40,
        armed_target=_armed("v5.1.1", "v5.1.2"),
    )

    assert resolution.version_tag == "v5.1.7"
    assert resolution.source_base_tag == "v5.1.6"
    assert resolution.requires_injection is False
    assert resolution.version_source == "pyproject"


def test_legacy_path_injects_armed_target_when_pyproject_is_source_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.1")
    monkeypatch.setattr(
        release_controller, "_release_tag_at_commit", lambda repo_root, commit: None
    )

    resolution = release_controller.resolve_release_version(
        source,
        tmp_path,
        "a" * 40,
        armed_target=_armed("v5.1.1", "v5.1.2"),
    )

    assert resolution.version_tag == "v5.1.2"
    assert resolution.source_base_tag == "v5.1.1"
    assert resolution.requires_injection is True
    assert resolution.version_source == "release-target"


def test_idempotent_record_accepts_target_or_base_without_tag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        release_controller, "_release_tag_at_commit", lambda repo_root, commit: None
    )
    record = {
        "version_tag": "v5.1.7",
        "stable": "v5.1.6",
        "sequence": 8,
        "release_id": "stable-0008",
    }

    for declared in ("5.1.6", "5.1.7"):
        source = _write_declared_source(tmp_path / declared, declared)
        release_controller.validate_idempotent_version(record, source, tmp_path, "a" * 40)

    source = _write_declared_source(tmp_path / "bad", "5.1.5")
    with pytest.raises(ValueError, match="does not match idempotency"):
        release_controller.validate_idempotent_version(record, source, tmp_path, "a" * 40)


def test_idempotent_record_must_match_exact_tag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write_declared_source(tmp_path, "5.1.7")
    record = {
        "version_tag": "v5.1.7",
        "stable": "v5.1.6",
        "sequence": 8,
        "release_id": "stable-0008",
    }
    monkeypatch.setattr(
        release_controller, "_release_tag_at_commit", lambda repo_root, commit: "v5.1.6"
    )
    with pytest.raises(ValueError, match="does not match idempotency target"):
        release_controller.validate_idempotent_version(record, source, tmp_path, "a" * 40)

    monkeypatch.setattr(
        release_controller, "_release_tag_at_commit", lambda repo_root, commit: "v5.1.7"
    )
    release_controller.validate_idempotent_version(record, source, tmp_path, "a" * 40)


def test_injection_records_only_files_that_changed(tmp_path: Path) -> None:
    source = _write_declared_source(tmp_path, "5.1.1")

    injected = release_controller.inject_launcher_version(
        source,
        target_version="5.1.2",
        source_base_version="5.1.1",
    )

    assert injected == [
        "launcher/src/neko_launcher/__init__.py",
        "launcher/pyproject.toml",
    ]
    assert "__version__ = \"5.1.2\"" in (
        source / "launcher" / "src" / "neko_launcher" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert 'version = "5.1.2"' in (
        source / "launcher" / "pyproject.toml"
    ).read_text(encoding="utf-8")

    assert release_controller.inject_launcher_version(
        source,
        target_version="5.1.2",
        source_base_version="5.1.1",
    ) == []


def test_injection_rejects_unrelated_declared_version(tmp_path: Path) -> None:
    source = _write_declared_source(tmp_path, "5.1.3")

    with pytest.raises(ValueError, match="Base version mismatch"):
        release_controller.inject_launcher_version(
            source,
            target_version="5.1.2",
            source_base_version="5.1.1",
        )
