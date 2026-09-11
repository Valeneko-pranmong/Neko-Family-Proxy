import pytest

from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads


def test_dumps_sorts_keys_lexicographically() -> None:
    obj = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
    encoded = canonical_json_dumps(obj)
    assert encoded == b'{"a":2,"m":{"a":4,"b":3},"z":1}'


def test_dumps_rejects_floats() -> None:
    with pytest.raises(ValueError, match="Float not permitted in canonical JSON"):
        canonical_json_dumps({"value": 1.5})


def test_dumps_escapes_controls_and_quotes() -> None:
    obj = {"msg": "hello \"world\"\n\x00"}
    encoded = canonical_json_dumps(obj)
    assert encoded == b'{"msg":"hello \\"world\\"\\u000a\\u0000"}'


def test_loads_rejects_duplicate_keys() -> None:
    raw = b'{"a":1,"a":2}'
    with pytest.raises(ValueError, match="Duplicate key"):
        canonical_json_loads(raw)


def test_loads_rejects_non_canonical_formatting() -> None:
    # Non-compact formatting (whitespace) or non-lexicographic order
    raw_with_spaces = b'{"a": 1}'
    with pytest.raises(ValueError, match="non-canonical format"):
        canonical_json_loads(raw_with_spaces)

    raw_unordered = b'{"z":1,"a":2}'
    with pytest.raises(ValueError, match="non-canonical format"):
        canonical_json_loads(raw_unordered)


def test_roundtrip_preserves_canonical_bytes() -> None:
    obj = {"alpha": "test", "beta": [1, 2, 3], "gamma": True, "delta": None}
    dumped = canonical_json_dumps(obj)
    loaded = canonical_json_loads(dumped)
    assert loaded == obj
    assert canonical_json_dumps(loaded) == dumped
