def test_derive_patch_stable_only():
    from scripts.derive_version import get_next_patch
    releases = [
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.4", "prerelease": False}
    ]
    assert get_next_patch(releases, []) == "v5.1.5"

def test_derive_patch_filters_prerelease_and_suffix_but_skips_occupied():
    from scripts.derive_version import get_next_patch
    releases = [
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.3-beta.1", "prerelease": True},
        {"tag_name": "v5.1.3", "prerelease": True}
    ]
    # Stable base is 5.1.2. Candidate 5.1.3 is occupied. So 5.1.4.
    assert get_next_patch(releases, []) == "v5.1.4"

def test_derive_patch_no_stable():
    from scripts.derive_version import get_next_patch
    releases = [
        {"tag_name": "v5.1.0-alpha", "prerelease": True},
    ]
    assert get_next_patch(releases, []) == "v5.1.0"

def test_derive_patch_jump_over_multiple_occupied():
    from scripts.derive_version import get_next_patch
    releases = [
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.3", "prerelease": True},
        {"tag_name": "v5.1.4", "prerelease": True},
        {"tag_name": "v5.1.5-beta", "prerelease": True},
    ]
    # Stable base is 5.1.2. Next stable is 5.1.3. But 5.1.3, 5.1.4 are occupied.
    # Is 5.1.5 occupied? Wait, 5.1.5-beta is occupied, but is v5.1.5 occupied? No.
    # The requirement: "skip any already-occupied version/tag/release identity".
    # If the tag is exactly "v5.1.5", it's occupied. If the tag is "v5.1.5-beta", does it occupy "v5.1.5"?
    # PM: "occupied superseded tag v5.1.3 => next available stable candidate v5.1.4".
    # We should skip if the exact candidate tag "v5.1.X" is in the occupied tags list.
    assert get_next_patch(releases, []) == "v5.1.5"

def test_derive_patch_empty():
    from scripts.derive_version import get_next_patch
    assert get_next_patch([], []) == "v5.1.0"

def test_derive_patch_current_state_fixture():
    from scripts.derive_version import get_next_patch, get_release_sequence
    # Prove current state yields next v5.1.7 and sequence 11
    releases = [
        {"tag_name": "v5.1.6", "prerelease": True},
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.1", "prerelease": False},
        {"tag_name": "v5.1.0", "prerelease": False},
    ]
    extra_tags = [
        "v5.1.0", "v5.1.1", "v5.1.2",
        "v5.1.3", "v5.1.4", "v5.1.5", "v5.1.6"
    ]

    next_patch = get_next_patch(releases, extra_tags)
    assert next_patch == "v5.1.7"
    assert get_release_sequence(next_patch) == 11

def test_derive_patch_calls_get_remote_tags(monkeypatch):
    from scripts import derive_version

    # Mock get_remote_tags to return our occupied tags
    def mock_get_remote_tags():
        return ["v5.1.0", "v5.1.1", "v5.1.2", "v5.1.3", "v5.1.4", "v5.1.5", "v5.1.6"]

    monkeypatch.setattr(derive_version, "get_remote_tags", mock_get_remote_tags)

    releases = [
        {"tag_name": "v5.1.6", "prerelease": True},
        {"tag_name": "v5.1.2", "prerelease": False},
        {"tag_name": "v5.1.1", "prerelease": False},
        {"tag_name": "v5.1.0", "prerelease": False},
    ]

    # Call without extra_tags
    next_patch = derive_version.get_next_patch(releases)
    assert next_patch == "v5.1.7"
