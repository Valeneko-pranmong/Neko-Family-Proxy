"""Strict canonical UTF-8 JSON serializer and deserializer."""
from __future__ import annotations


def canonical_json_dumps(obj: object) -> bytes:
    """Serialize an object into strict canonical UTF-8 JSON bytes."""
    raise NotImplementedError("canonical_json_dumps not implemented")


def canonical_json_loads(data: bytes | str) -> object:
    """Deserialize strict canonical UTF-8 JSON bytes or string."""
    raise NotImplementedError("canonical_json_loads not implemented")
