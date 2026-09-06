"""Strict canonical UTF-8 JSON serializer and deserializer."""
from __future__ import annotations

import json
from typing import Any


def _encode_canonical_value(val: Any) -> str:
    # Boolean must be checked before int because bool is a subclass of int in Python
    if isinstance(val, bool):
        return "true" if val else "false"
    if val is None:
        return "null"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        raise ValueError("Float not permitted in canonical JSON")
    if isinstance(val, str):
        out = []
        for char in val:
            code = ord(char)
            if char == '"':
                out.append('\\"')
            elif char == "\\":
                out.append("\\\\")
            elif code < 0x20:
                out.append(f"\\u{code:04x}")
            else:
                out.append(char)
        return '"' + "".join(out) + '"'
    if isinstance(val, (list, tuple)):
        return "[" + ",".join(_encode_canonical_value(item) for item in val) + "]"
    if isinstance(val, dict):
        # Keys must be strings and sorted lexicographically
        items = []
        for k in sorted(val.keys()):
            if not isinstance(k, str):
                raise ValueError("Dict keys must be strings in canonical JSON")
            items.append(_encode_canonical_value(k) + ":" + _encode_canonical_value(val[k]))
        return "{" + ",".join(items) + "}"
    raise ValueError(f"Unsupported type in canonical JSON: {type(val).__name__}")


def canonical_json_dumps(obj: object) -> bytes:
    """Serialize an object into strict canonical UTF-8 JSON bytes."""
    encoded_str = _encode_canonical_value(obj)
    return encoded_str.encode("utf-8")


def _reject_duplicate_keys_hook(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key in canonical JSON: {key!r}")
        result[key] = value
    return result


def canonical_json_loads(data: bytes | str) -> object:
    """Deserialize strict canonical UTF-8 JSON bytes or string, enforcing exact formatting."""
    if isinstance(data, str):
        raw_bytes = data.encode("utf-8")
        raw_str = data
    else:
        raw_bytes = data
        try:
            raw_str = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as err:
            raise ValueError("Invalid UTF-8 in canonical JSON") from err

    try:
        parsed = json.loads(raw_str, object_pairs_hook=_reject_duplicate_keys_hook)
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON: {err}") from err

    # Strict canon validation: reserialized bytes must match original bytes exactly
    re_encoded = canonical_json_dumps(parsed)
    if re_encoded != raw_bytes:
        raise ValueError("non-canonical format: encoding does not match canonical form")

    return parsed
