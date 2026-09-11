import pytest
import json
import scripts.derive_version
from pathlib import Path

def test_failed_attempts_keep_target(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({
        "target": "v5.1.0",
        "seq": 4
    }), encoding="utf-8")

    class MockPath:
        def __init__(self, *args, **kwargs):
            self._path = Path(*args, **kwargs)
        def __truediv__(self, other):
            if other == "release_target.json":
                class DummyFile:
                    def exists(self): return True
                    def read_text(self, *a, **kw): return target_file.read_text(encoding="utf-8")
                return DummyFile()
            return MockPath(self._path / other)
        def resolve(self):
            return MockPath(self._path.resolve())
        @property
        def parent(self):
            return MockPath(self._path.parent)

    monkeypatch.setattr(scripts.derive_version, "Path", MockPath)

    releases = [
        {"tag_name": "v5.1.0", "prerelease": True}, # failed attempt 1
        {"tag_name": "v5.1.0", "prerelease": True}, # failed attempt 2
        {"tag_name": "v5.1.0", "prerelease": True}, # failed attempt 3
    ]
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.0"
    assert scripts.derive_version.get_release_sequence("v5.1.0") == 4

def test_occupied_accidental_tags_do_not_change_target(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.0", "seq": 4}), encoding="utf-8")

    class MockPath:
        def __init__(self, *args, **kwargs):
            self._path = Path(*args, **kwargs)
        def __truediv__(self, other):
            if other == "release_target.json":
                class DummyFile:
                    def exists(self): return True
                    def read_text(self, *a, **kw): return target_file.read_text(encoding="utf-8")
                return DummyFile()
            return MockPath(self._path / other)
        def resolve(self): return MockPath(self._path.resolve())
        @property
        def parent(self): return MockPath(self._path.parent)
    monkeypatch.setattr(scripts.derive_version, "Path", MockPath)

    # regression proving occupied historical tags v5.1.0-v5.1.6 do not bump target while reset/cutover mode is active
    releases = [
        {"tag_name": "v5.1.0", "prerelease": True},
        {"tag_name": "v5.1.1", "prerelease": True},
        {"tag_name": "v5.1.2", "prerelease": True},
        {"tag_name": "v5.1.3", "prerelease": True},
        {"tag_name": "v5.1.4", "prerelease": True},
        {"tag_name": "v5.1.5", "prerelease": False}, # Ghost tag, not accepted stable since we don't have explicit stable intent
        {"tag_name": "v5.1.6", "prerelease": True},
    ]
    # target is strictly v5.1.0, doesn't bump
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.0"

def test_controller_never_emits_517(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.0", "seq": 4}), encoding="utf-8")

    class MockPath:
        def __init__(self, *args, **kwargs):
            self._path = Path(*args, **kwargs)
        def __truediv__(self, other):
            if other == "release_target.json":
                class DummyFile:
                    def exists(self): return True
                    def read_text(self, *a, **kw): return target_file.read_text(encoding="utf-8")
                return DummyFile()
            return MockPath(self._path / other)
        def resolve(self): return MockPath(self._path.resolve())
        @property
        def parent(self): return MockPath(self._path.parent)
    monkeypatch.setattr(scripts.derive_version, "Path", MockPath)

    releases = [
        {"tag_name": "v5.1.6", "prerelease": True},
        {"tag_name": "v5.1.0", "prerelease": True},
        {"tag_name": "v5.1.1", "prerelease": True},
    ]
    # target is strictly v5.1.0, controller never emits v5.1.7
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.0"

def test_after_mocked_accepted_stable_no_automatic_bump(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.0", "seq": 4}), encoding="utf-8")

    class MockPath:
        def __init__(self, *args, **kwargs):
            self._path = Path(*args, **kwargs)
        def __truediv__(self, other):
            if other == "release_target.json":
                class DummyFile:
                    def exists(self): return True
                    def read_text(self, *a, **kw): return target_file.read_text(encoding="utf-8")
                return DummyFile()
            return MockPath(self._path / other)
        def resolve(self): return MockPath(self._path.resolve())
        @property
        def parent(self): return MockPath(self._path.parent)
    monkeypatch.setattr(scripts.derive_version, "Path", MockPath)

    releases = [
        {"tag_name": "v5.1.0", "prerelease": False}, # accepted stable
    ]
    with pytest.raises(ValueError, match="already accepted as Stable"):
        scripts.derive_version.get_next_patch(releases)

def test_explicit_user_bug_intent_permits_exact_bump(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.1", "seq": 5}), encoding="utf-8")

    class MockPath:
        def __init__(self, *args, **kwargs):
            self._path = Path(*args, **kwargs)
        def __truediv__(self, other):
            if other == "release_target.json":
                class DummyFile:
                    def exists(self): return True
                    def read_text(self, *a, **kw): return target_file.read_text(encoding="utf-8")
                return DummyFile()
            return MockPath(self._path / other)
        def resolve(self): return MockPath(self._path.resolve())
        @property
        def parent(self): return MockPath(self._path.parent)
    monkeypatch.setattr(scripts.derive_version, "Path", MockPath)

    releases = [
        {"tag_name": "v5.1.0", "prerelease": False}, # previously accepted stable
    ]
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.1"
    assert scripts.derive_version.get_release_sequence("v5.1.1") == 5