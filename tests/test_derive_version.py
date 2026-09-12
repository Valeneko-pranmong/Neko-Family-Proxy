import json
from pathlib import Path

import pytest

import scripts.derive_version


@pytest.fixture
def mock_target_file(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    class MockPath:
        def __init__(self, *args, **kwargs):
            self._path = Path(*args, **kwargs)
        def __truediv__(self, other):
            if other == "release_target.json":
                class DummyFile:
                    def exists(self): return target_file.exists()
                    def read_text(self, *a, **kw): return target_file.read_text(encoding="utf-8")
                return DummyFile()
            return MockPath(self._path / other)
        def resolve(self): return MockPath(self._path.resolve())
        @property
        def parent(self): return MockPath(self._path.parent)
    monkeypatch.setattr(scripts.derive_version, "Path", MockPath)
    return target_file

def test_closed_post_cutover_target_fails(mock_target_file):
    mock_target_file.write_text(json.dumps({
        "stable": "v5.1.0",
        "target": "v5.1.0",
        "seq": 4,
        "stable_id": "stable-0004",
        "intent": "closed"
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="intent is closed or missing"):
        scripts.derive_version.get_armed_target()

def test_missing_intent_fails(mock_target_file):
    mock_target_file.write_text(json.dumps({
        "stable": "v5.1.0",
        "target": "v5.1.0",
        "seq": 4,
        "stable_id": "stable-0004"
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="intent is closed or missing"):
        scripts.derive_version.get_armed_target()

def test_explicit_user_bug_intent_success(mock_target_file):
    mock_target_file.write_text(json.dumps({
        "stable": "v5.1.0",
        "target": "v5.1.1",
        "seq": 5,
        "stable_id": "stable-0005",
        "intent": "user_bug"
    }), encoding="utf-8")
    stable, target, seq, stable_id = scripts.derive_version.get_armed_target()
    assert stable == "v5.1.0"
    assert target == "v5.1.1"
    assert seq == 5
    assert stable_id == "stable-0005"

def test_reject_skip_patch(mock_target_file):
    mock_target_file.write_text(json.dumps({
        "stable": "v5.1.0",
        "target": "v5.1.2",
        "seq": 6,
        "stable_id": "stable-0006",
        "intent": "user_bug"
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one patch increment from accepted stable is allowed"):
        scripts.derive_version.get_armed_target()

def test_reject_seq_id_mismatch(mock_target_file):
    mock_target_file.write_text(json.dumps({
        "stable": "v5.1.0",
        "target": "v5.1.1",
        "seq": 4,
        "stable_id": "stable-0005",
        "intent": "user_bug"
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="sequence or stable_id mismatch"):
        scripts.derive_version.get_armed_target()
