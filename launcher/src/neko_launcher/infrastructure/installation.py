from __future__ import annotations

import hashlib
import secrets
import socket

from neko_launcher.application.ports import SecureStore


class LocalInstallationIdentity:
    """Creates a random installation identity without hardware fingerprinting."""

    _STORE_KEY = "installation-secret"

    def __init__(self, secure_store: SecureStore) -> None:
        self._secure_store = secure_store

    @property
    def key_hash(self) -> str:
        secret = self._secure_store.read(self._STORE_KEY)
        if secret is None:
            secret = secrets.token_hex(32)
            self._secure_store.write(self._STORE_KEY, secret)
        return hashlib.sha256(secret.encode("ascii")).hexdigest()

    @property
    def display_name(self) -> str:
        return socket.gethostname()[:120] or "Windows PC"
