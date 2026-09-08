from neko_launcher.updater.trust import PRODUCTION_RELEASE_PUBLIC_KEYS


APPROVED_PRODUCTION_KEY_ID = "neko-update-prod-1"


def test_production_release_public_keys_contains_only_approved_key() -> None:
    assert set(PRODUCTION_RELEASE_PUBLIC_KEYS) == {APPROVED_PRODUCTION_KEY_ID}

    public_key = PRODUCTION_RELEASE_PUBLIC_KEYS[APPROVED_PRODUCTION_KEY_ID]
    assert isinstance(public_key, bytes)
    assert len(public_key) == 32

    assert all(
        "test" not in key_id.lower() and "placeholder" not in key_id.lower()
        for key_id in PRODUCTION_RELEASE_PUBLIC_KEYS
    )
