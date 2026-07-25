import hashlib

from neko_launcher.infrastructure.installation import LocalInstallationIdentity
from neko_launcher.infrastructure.secure_store import SupabaseAuthStorage


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_installation_identity_is_random_persistent_and_hashed() -> None:
    store = MemoryStore()
    identity = LocalInstallationIdentity(store)

    first = identity.key_hash
    second = LocalInstallationIdentity(store).key_hash

    assert first == second
    assert len(first) == 64
    assert first == hashlib.sha256(
        store.values["installation-secret"].encode("ascii")
    ).hexdigest()


def test_supabase_storage_delegates_to_secure_store() -> None:
    store = MemoryStore()
    storage = SupabaseAuthStorage(store)

    storage.set_item("auth-session", "secret-json")
    assert storage.get_item("auth-session") == "secret-json"

    storage.remove_item("auth-session")
    assert storage.get_item("auth-session") is None
