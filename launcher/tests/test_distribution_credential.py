from neko_launcher.infrastructure.distribution_credential import (
    clear_distribution_capability,
    get_distribution_capability,
    set_distribution_capability,
)


def test_credential_storage_roundtrip() -> None:
    test_cap = "test-opaque-capability-token-12345"
    try:
        set_distribution_capability(test_cap)
        retrieved = get_distribution_capability()
        assert retrieved == test_cap
    finally:
        clear_distribution_capability()
        assert get_distribution_capability() is None


def test_clear_nonexistent_does_not_raise() -> None:
    clear_distribution_capability()
    clear_distribution_capability()
    assert get_distribution_capability() is None
