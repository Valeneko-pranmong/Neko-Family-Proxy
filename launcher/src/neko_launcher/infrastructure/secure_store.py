from __future__ import annotations

import keyring
from keyring.errors import KeyringError

from neko_launcher.application.ports import SecureStore


class KeyringSecureStore(SecureStore):
    """Stores launcher secrets in the operating system credential vault."""

    def __init__(self, service_name: str = "Neko Family Launcher") -> None:
        self._service_name = service_name

    def read(self, key: str) -> str | None:
        try:
            return keyring.get_password(self._service_name, key)
        except KeyringError as exc:
            raise RuntimeError("Credential storage is unavailable") from exc

    def write(self, key: str, value: str) -> None:
        try:
            keyring.set_password(self._service_name, key, value)
        except KeyringError as exc:
            raise RuntimeError("Credential storage is unavailable") from exc

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(self._service_name, key)
        except keyring.errors.PasswordDeleteError:
            return
        except KeyringError as exc:
            raise RuntimeError("Credential storage is unavailable") from exc


class SupabaseAuthStorage:
    """Adapts SecureStore to the storage interface expected by supabase-py."""

    def __init__(self, secure_store: SecureStore) -> None:
        self._secure_store = secure_store

    def get_item(self, key: str) -> str | None:
        return self._secure_store.read(key)

    def set_item(self, key: str, value: str) -> None:
        self._secure_store.write(key, value)

    def remove_item(self, key: str) -> None:
        self._secure_store.delete(key)
