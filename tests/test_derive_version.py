import pytest
import json
import scripts.derive_version
from pathlib import Path

@pytest.fixture
def mock_target(monkeypatch, tmp_path):
    # Instead of mocking Path, let's just patch the content of release_target.json where it lives,
    # or monkeypatch a function. Wait, we can monkeypatch Path or just read_text?
    # Let's mock a method in scripts.derive_version directly
    pass

    # We can use monkeypatch.setattr on scripts.derive_version to override the hardcoded file reading?
    # No, it's easier to mock the pathlib.Path
    pass

def test_failed_attempts_keep_target(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({
        "target": "v5.1.3",
        "seq": 7
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
        {"tag_name": "v5.1.3", "prerelease": True}, # failed attempt 1
        {"tag_name": "v5.1.3", "prerelease": True}, # failed attempt 2
    ]
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.3"
    assert scripts.derive_version.get_release_sequence("v5.1.3") == 7

def test_occupied_accidental_tags_do_not_change_target(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.3", "seq": 7}), encoding="utf-8")

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
        {"tag_name": "v5.1.4", "prerelease": True},
        {"tag_name": "v5.1.5", "prerelease": False},
        {"tag_name": "v5.1.6", "prerelease": True},
    ]
    # target is strictly v5.1.3, doesn't bump
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.3"

def test_controller_never_emits_517(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.3", "seq": 7}), encoding="utf-8")

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
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.1", "prerelease": False},
    ]
    # target is strictly v5.1.3
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.3"

def test_after_mocked_accepted_stable_no_automatic_bump(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.3", "seq": 7}), encoding="utf-8")

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
        {"tag_name": "v5.1.3", "prerelease": False}, # accepted stable
    ]
    with pytest.raises(ValueError, match="already accepted as Stable"):
        scripts.derive_version.get_next_patch(releases)

def test_explicit_user_bug_intent_permits_exact_bump(monkeypatch, tmp_path):
    target_file = tmp_path / "release_target.json"
    target_file.write_text(json.dumps({"target": "v5.1.4", "seq": 8}), encoding="utf-8")

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
        {"tag_name": "v5.1.3", "prerelease": False}, # previously accepted stable
    ]
    assert scripts.derive_version.get_next_patch(releases) == "v5.1.4"
    assert scripts.derive_version.get_release_sequence("v5.1.4") == 8
