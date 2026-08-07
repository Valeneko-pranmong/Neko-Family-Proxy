from __future__ import annotations

import base64
import zlib

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

    _COMPRESSED_PREFIX = "zlib1:"
    _CHUNKED_PREFIX = "chunked1:"
    _CHUNK_SIZE = 900

    def __init__(self, secure_store: SecureStore) -> None:
        self._secure_store = secure_store

    def get_item(self, key: str) -> str | None:
        value = self._secure_store.read(key)
        if value is None:
            return value
        if value.startswith(self._CHUNKED_PREFIX):
            try:
                count = int(value[len(self._CHUNKED_PREFIX) :])
            except ValueError:
                return None
            chunks = [
                self._secure_store.read(f"{key}.{index}") for index in range(count)
            ]
            if any(chunk is None for chunk in chunks):
                return None
            value = "".join(chunk for chunk in chunks if chunk is not None)
        if not value.startswith(self._COMPRESSED_PREFIX):
            return value
        try:
            encoded = value[len(self._COMPRESSED_PREFIX) :].encode("ascii")
            return zlib.decompress(base64.urlsafe_b64decode(encoded)).decode("utf-8")
        except (ValueError, UnicodeDecodeError, zlib.error):
            # Preserve compatibility with a legacy value that happens to use
            # the prefix but is not a valid compressed payload.
            return value

    def set_item(self, key: str, value: str) -> None:
        compressed = self._COMPRESSED_PREFIX + base64.urlsafe_b64encode(
            zlib.compress(value.encode("utf-8"), level=9)
        ).decode("ascii")
        encoded = compressed if len(compressed) < len(value) else value
        old = self._secure_store.read(key)
        old_count = self._chunk_count(old)
        if len(encoded) <= self._CHUNK_SIZE:
            self._secure_store.write(key, encoded)
            self._delete_chunks(key, old_count)
            return

        chunks = [
            encoded[index : index + self._CHUNK_SIZE]
            for index in range(0, len(encoded), self._CHUNK_SIZE)
        ]
        for index, chunk in enumerate(chunks):
            self._secure_store.write(f"{key}.{index}", chunk)
        self._secure_store.write(key, f"{self._CHUNKED_PREFIX}{len(chunks)}")
        self._delete_chunks(key, old_count, start=len(chunks))

    def remove_item(self, key: str) -> None:
        self._delete_chunks(key, self._chunk_count(self._secure_store.read(key)))
        self._secure_store.delete(key)

    @classmethod
    def _chunk_count(cls, value: str | None) -> int:
        if not value or not value.startswith(cls._CHUNKED_PREFIX):
            return 0
        try:
            return max(0, int(value[len(cls._CHUNKED_PREFIX) :]))
        except ValueError:
            return 0

    def _delete_chunks(self, key: str, count: int, *, start: int = 0) -> None:
        for index in range(start, count):
            self._secure_store.delete(f"{key}.{index}")
