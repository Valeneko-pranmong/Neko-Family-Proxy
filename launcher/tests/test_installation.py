import hashlib
import random

from neko_launcher.infrastructure.storage.installation import LocalInstallationIdentity
from neko_launcher.infrastructure.auth.secure_store import SupabaseAuthStorage


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


def test_supabase_storage_compresses_large_auth_sessions() -> None:
    store = MemoryStore()
    storage = SupabaseAuthStorage(store)
    value = '{"access_token":"' + ("token-" * 600) + '"}'

    storage.set_item("auth-session", value)

    assert store.values["auth-session"].startswith("zlib1:")
    assert storage.get_item("auth-session") == value


def test_supabase_storage_chunks_values_beyond_credential_limit() -> None:
    store = MemoryStore()
    storage = SupabaseAuthStorage(store)
    generator = random.Random(42)
    value = "".join(generator.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(3000))

    storage.set_item("auth-session", value)

    assert store.values["auth-session"].startswith("chunked1:")
    assert storage.get_item("auth-session") == value
