from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

from .proxy_api_gateway import ProxyApiError

T = TypeVar("T")

_AUTH_RETRY_CODES = frozenset({"invalid_token", "token_expired"})


class ProxyApiAccessTokenProvider(Protocol):
    def access_token(self) -> str: ...

    def refresh_access_token(self) -> str: ...


def call_with_access_token(
    provider: ProxyApiAccessTokenProvider,
    operation: Callable[[str], T],
) -> T:
    """Run one authorized operation with at most one refresh-and-retry."""
    try:
        token = provider.access_token()
    except ProxyApiError as error:
        if error.code not in _AUTH_RETRY_CODES:
            raise
        token = provider.refresh_access_token()
        return operation(token)
    try:
        return operation(token)
    except ProxyApiError as error:
        if error.code not in _AUTH_RETRY_CODES:
            raise
        token = provider.refresh_access_token()
        return operation(token)
