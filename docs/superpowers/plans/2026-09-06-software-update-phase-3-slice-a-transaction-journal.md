# Software Update Phase 3 — Slice A Implementation Plan: Transaction Model & Journal

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the pure, crash-resilient transaction model, canonical JSON serialization, dual-slot 1 MiB binary frames, enrollment marker 16 KiB frames, domain models, snapshot selection predicates, and the exhaustive 25-state transition automaton specified in Sections 8, 8.1, and 13.1 of the approved Phase-3 specification.

**Architecture:** The state journal is stored in two fixed 1,048,576-byte slot files (`state/slot-a.bin` and `state/slot-b.bin`). Each slot contains a 24-byte header, body length, format version, revision, SHA-256 integrity checksum, canonical UTF-8 JSON body, and zero-byte padding. An immutable 16,384-byte enrollment marker (`state/enrollment.bin`) binds the installation trust root. State models are frozen dataclasses with closed keys, embedded signed envelope evidence, directory identities, and an exhaustive transition validator that guarantees atomic progression without relying on directory fsync or unauthenticated metadata.

**Tech Stack:** Python 3.11, standard library `dataclasses`, `hashlib`, `json`, `re`, `struct`, pytest 8.3.5, Ruff 0.11.2.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§4, 5, 8, 8.1, 13, 13.1, 15).

---

## Global Constraints

- Directory: `E:\Github\worktrees\Neko-Family-Proxy-5.1\launcher`
- Target package: `neko_launcher.updater`
- Tests package: `tests.updater`
- No third-party dependencies outside existing `pyproject.toml` (only Python stdlib + `cryptography` for Ed25519 verification).
- Slot body must strictly use the canonical JSON encoding: lexicographic ASCII keys, compact separators `","` and `":"`, minimal integer formatting, escaped quotes/backslashes and ASCII control characters, reject floats, reject NaN/Infinity, reject duplicate keys.
- Slots are exactly 1,048,576 bytes; enrollment marker is exactly 16,384 bytes.
- Every state mutation must follow the exhaustive automaton. Illegal transitions fail closed.

---

### Task 1: Canonical UTF-8 JSON Serializer & Deserializer

**Files:**
- Create: `launcher/src/neko_launcher/updater/canonical_json.py`
- Create: `launcher/tests/updater/test_canonical_json.py`

**Interfaces:**
- Produces: `canonical_json_dumps(obj: object) -> bytes`
- Produces: `canonical_json_loads(data: bytes | str) -> object`
- Raises `ValueError` for non-canonical types (floats, non-str keys, circular refs), duplicate keys, non-ASCII characters, or lone surrogates.

- [ ] **Step 1: Write RED tests for canonical JSON encoding & strict validation**

```python
# launcher/tests/updater/test_canonical_json.py
import pytest
from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads

def test_dumps_sorts_keys_lexicographically():
    obj = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
    encoded = canonical_json_dumps(obj)
    assert encoded == b'{"a":2,"m":{"a":4,"b":3},"z":1}'

def test_dumps_rejects_floats():
    with pytest.raises(ValueError, match="Float not permitted in canonical JSON"):
        canonical_json_dumps({"value": 1.5})

def test_dumps_escapes_controls_and_quotes():
    obj = {"msg": "hello \"world\"\n\x00"}
    encoded = canonical_json_dumps(obj)
    assert encoded == b'{"msg":"hello \\"world\\"\\u000a\\u0000"}'

def test_loads_rejects_duplicate_keys():
    raw = b'{"a":1,"a":2}'
    with pytest.raises(ValueError, match="Duplicate key"):
        canonical_json_loads(raw)

def test_roundtrip_preserves_canonical_bytes():
    obj = {"alpha": "test", "beta": [1, 2, 3], "gamma": True, "delta": None}
    dumped = canonical_json_dumps(obj)
    loaded = canonical_json_loads(dumped)
    assert loaded == obj
    assert canonical_json_dumps(loaded) == dumped
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_canonical_json.py`
Expected: FAIL (ModuleNotFoundError or ImportError: `neko_launcher.updater.canonical_json`).

- [ ] **Step 3: Implement canonical JSON serializer & deserializer**

Implement in `launcher/src/neko_launcher/updater/canonical_json.py`:
- `_encode_value` recursively handling `dict`, `list`, `str`, `int`, `bool`, `None`.
- Explicit float check (`if isinstance(v, float) or type(v) is float: raise ValueError(...)`).
- Key sorting: `sorted(dict.keys())` ensuring string ASCII.
- String escaping: replace `\\`, `"`, and ASCII `< 0x20` with `\\u00xx`.
- Custom `object_pairs_hook` in `json.loads` to reject duplicate keys.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_canonical_json.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/canonical_json.py tests/updater/test_canonical_json.py`
Expected: All tests pass, Ruff check zero warnings.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/canonical_json.py launcher/tests/updater/test_canonical_json.py
git commit -m "feat(updater): implement strict canonical json codec"
```

---

### Task 2: Dual Slot & Enrollment Marker Binary Frames

**Files:**
- Create: `launcher/src/neko_launcher/updater/binary_frame.py`
- Create: `launcher/tests/updater/test_binary_frame.py`

**Interfaces:**
- Produces: `SlotFrame(revision: int, format_version: int, body_bytes: bytes)`
- Produces: `pack_slot_frame(frame: SlotFrame) -> bytes` (fixed 1,048,576 bytes, magic `NEKOUPD1`)
- Produces: `unpack_slot_frame(raw: bytes) -> SlotFrame`
- Produces: `MarkerFrame(format_version: int, body_bytes: bytes)`
- Produces: `pack_marker_frame(frame: MarkerFrame) -> bytes` (fixed 16,384 bytes, magic `NEKOENR1`)
- Produces: `unpack_marker_frame(raw: bytes) -> MarkerFrame`

- [ ] **Step 1: Write RED tests for frame packing, unpacking, padding, and checksum verification**

```python
# launcher/tests/updater/test_binary_frame.py
import pytest
from neko_launcher.updater.binary_frame import (
    SlotFrame, pack_slot_frame, unpack_slot_frame,
    MarkerFrame, pack_marker_frame, unpack_marker_frame,
    FrameCorruptError,
    SLOT_FRAME_SIZE, MARKER_FRAME_SIZE,
)

def test_slot_frame_pack_unpack_roundtrip():
    body = b'{"schema_version":1,"revision":42}'
    frame = SlotFrame(revision=42, format_version=1, body_bytes=body)
    packed = pack_slot_frame(frame)
    assert len(packed) == SLOT_FRAME_SIZE == 1_048_576
    assert packed[:8] == b"NEKOUPD1"
    unpacked = unpack_slot_frame(packed)
    assert unpacked.revision == 42
    assert unpacked.format_version == 1
    assert unpacked.body_bytes == body

def test_slot_frame_rejects_corrupted_checksum():
    body = b'{"schema_version":1}'
    packed = bytearray(pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=body)))
    packed[64] ^= 0xFF  # Corrupt body byte
    with pytest.raises(FrameCorruptError, match="Checksum mismatch"):
        unpack_slot_frame(bytes(packed))

def test_slot_frame_rejects_non_zero_padding():
    body = b'{"schema_version":1}'
    packed = bytearray(pack_slot_frame(SlotFrame(revision=1, format_version=1, body_bytes=body)))
    packed[-1] = 0x01  # Dirty padding
    with pytest.raises(FrameCorruptError, match="Dirty trailing padding"):
        unpack_slot_frame(bytes(packed))

def test_marker_frame_pack_unpack():
    body = b'{"installation_id":"abc"}'
    packed = pack_marker_frame(MarkerFrame(format_version=1, body_bytes=body))
    assert len(packed) == MARKER_FRAME_SIZE == 16_384
    assert packed[:8] == b"NEKOENR1"
    unpacked = unpack_marker_frame(packed)
    assert unpacked.body_bytes == body
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_binary_frame.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'neko_launcher.updater.binary_frame'`.

- [ ] **Step 3: Implement binary frame packing & unpacking**

Implement `launcher/src/neko_launcher/updater/binary_frame.py`:
- Header layout: `<8sIIIQ32s` (Magic, body_length, format_version, reserved, revision, sha256).
- Slot frame size: 1024 * 1024 (1,048,576 bytes).
- Marker frame size: 16 * 1024 (16,384 bytes).
- SHA256 covers header prefix (first 24 bytes) + `body_bytes`.
- Validate that remaining bytes in slice `[header_len + body_len:]` are strictly all zeroes `b'\x00'`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_binary_frame.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/binary_frame.py tests/updater/test_binary_frame.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/binary_frame.py launcher/tests/updater/test_binary_frame.py
git commit -m "feat(updater): implement dual slot and enrollment binary frame codecs"
```

---

### Task 3: State Domain Models, Enrollment Marker & Schema Validation

**Files:**
- Create: `launcher/src/neko_launcher/updater/state_models.py`
- Create: `launcher/tests/updater/test_state_models.py`

**Interfaces:**
- Produces: `Binding`, `Generation`, `DirectoryIdentity`, `Transaction`, `Cleanup`, `Rollback`, `State`, `EnrollmentMarker`
- Produces: `serialize_state(state: State) -> bytes`, `deserialize_state(raw: bytes) -> State`
- Produces: `serialize_marker(marker: EnrollmentMarker) -> bytes`, `deserialize_marker(raw: bytes) -> EnrollmentMarker`
- Enforces strict field typing, non-empty lowerhex hashes, closed field sets, bounded sizes.

- [ ] **Step 1: Write RED tests for state models & serialization**

```python
# launcher/tests/updater/test_state_models.py
import pytest
from neko_launcher.updater.state_models import (
    Binding, Generation, DirectoryIdentity, Transaction, Cleanup, Rollback, State,
    EnrollmentMarker, serialize_state, deserialize_state, serialize_marker, deserialize_marker
)

def test_state_serialization_roundtrip():
    binding = Binding(release_sequence=1, release_id="rel-1", payload_sha256="a"*64)
    gen = Generation(binding=binding, launcher_identity_sha256="b"*64, core_identity_sha256="c"*64)
    state = State(
        schema_version=1,
        revision=1,
        installation_id="1"*32,
        helper_protocol=1,
        enrollment_complete=True,
        phase="IDLE",
        committed=gen,
        previous=None,
        highwater=binding,
        observed=binding,
        failed=None,
        transaction=None,
        cleanup=None,
        rollback=None,
        last_error=None,
        evidence={"a"*64: "dGVzdC1lbnZlbG9wZQ=="}
    )
    data = serialize_state(state)
    restored = deserialize_state(data)
    assert restored == state

def test_state_rejects_extra_fields():
    raw = b'{"schema_version":1,"revision":1,"installation_id":"11111111111111111111111111111111","helper_protocol":1,"enrollment_complete":true,"phase":"IDLE","committed":null,"previous":null,"highwater":null,"observed":null,"failed":null,"transaction":null,"cleanup":null,"rollback":null,"last_error":null,"evidence":{},"unauthorized_field":true}'
    with pytest.raises(ValueError, match="Unknown field: unauthorized_field"):
        deserialize_state(raw)
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_state_models.py`
Expected: FAIL (ModuleNotFoundError: `neko_launcher.updater.state_models`).

- [ ] **Step 3: Implement domain models, validation, and JSON serialization**

Implement `launcher/src/neko_launcher/updater/state_models.py`:
- Use `dataclasses` with `@dataclass(frozen=True)`.
- Implement dataclass <-> dict conversion with closed key validation against dataclass fields.
- Type & format validation (regex check on hashes, IDs, enums).
- Hook to `canonical_json_dumps` and `canonical_json_loads`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_state_models.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/state_models.py tests/updater/test_state_models.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/state_models.py launcher/tests/updater/test_state_models.py
git commit -m "feat(updater): implement state and enrollment marker domain models"
```

---

### Task 4: Pairwise Snapshot Selection & Validation Predicates

**Files:**
- Create: `launcher/src/neko_launcher/updater/slot_selector.py`
- Create: `launcher/tests/updater/test_slot_selector.py`

**Interfaces:**
- Produces: `select_active_slot(slot_a_bytes: bytes | None, slot_b_bytes: bytes | None, public_keys: Mapping[str, bytes]) -> SelectionResult`
- `SelectionResult` status: `SELECTED`, `REPAIR_REQUIRED`, `ENROLLMENT_INCOMPLETE`
- Implements the 6-predicate hierarchy:
  1. Frame-valid
  2. Schema-valid
  3. Evidence-authenticated (Ed25519 verified against embedded public key registry)
  4. Transition-valid (consecutive revisions, monotonic floors, valid transition)
  5. Generation-complete (assessed on selected snapshot)
  6. Launchable
- Handles all pairwise cases from Section 8.1.

- [ ] **Step 1: Write RED tests covering pairwise selection matrix**

```python
# launcher/tests/updater/test_slot_selector.py
import pytest
from neko_launcher.updater.slot_selector import select_active_slot, SelectionStatus

def test_select_highest_consecutive_valid_revision(valid_slot_pair):
    slot_a, slot_b, keys = valid_slot_pair(rev_a=10, rev_b=11)
    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.SELECTED
    assert res.state.revision == 11
    assert res.active_slot == "b"

def test_select_valid_when_other_slot_torn(valid_slot_single):
    slot_a, keys = valid_slot_single(rev=5)
    slot_b = b"corrupted bytes..."
    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.SELECTED
    assert res.state.revision == 5
    assert res.active_slot == "a"

def test_repair_required_when_higher_slot_malformed(valid_slot_single, malformed_frame):
    slot_a, keys = valid_slot_single(rev=5)
    slot_b = malformed_frame(rev=6)  # Frame valid, but schema invalid
    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.REPAIR_REQUIRED
    assert "malformed higher slot" in res.reason.lower()

def test_repair_required_when_stale_lower_slot_malformed(valid_slot_single, malformed_frame):
    slot_a = malformed_frame(rev=4)
    slot_b, keys = valid_slot_single(rev=5)
    res = select_active_slot(slot_a, slot_b, keys)
    assert res.status == SelectionStatus.REPAIR_REQUIRED
    assert "malformed stale history" in res.reason.lower()
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_slot_selector.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'neko_launcher.updater.slot_selector'`.

- [ ] **Step 3: Implement pairwise slot selection algorithm**

Implement `launcher/src/neko_launcher/updater/slot_selector.py`:
- Unpack frames; classify frame validity.
- If both frames valid, parse states and verify Ed25519 evidence against `public_keys`. If either fails schema/evidence, report `REPAIR_REQUIRED`.
- Check revision adjacency (`abs(rev_a - rev_b) == 1` or identical revision 1 enrollment).
- Highest revision wins if transition valid; else `REPAIR_REQUIRED`.

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_slot_selector.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/slot_selector.py tests/updater/test_slot_selector.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/slot_selector.py launcher/tests/updater/test_slot_selector.py
git commit -m "feat(updater): implement pairwise slot selection and validation predicates"
```

---

### Task 5: Exhaustive State Transition Automaton

**Files:**
- Create: `launcher/src/neko_launcher/updater/state_machine.py`
- Create: `launcher/tests/updater/test_state_machine.py`

**Interfaces:**
- Produces: `validate_transition(current: State, next_state: State) -> None`
- Produces helper step functions:
  - `transition_to_preparing(current: State, candidate: Generation, incoming_id: DirectoryIdentity, envelope_b64: str) -> State`
  - `transition_stage_mutation(current: State, next_mutation_kind: str, next_status: str, ...) -> State`
  - `transition_to_probation(...) -> State`
  - `transition_commit(...) -> State`
  - `transition_pre_quiesce_abort(...) -> State`
  - `transition_to_rollback(...) -> State`
  - `transition_rollback_step(...) -> State`
  - `transition_cleaning_step(...) -> State`

- [ ] **Step 1: Write RED tests for all legal state transitions and illegal transition rejection**

```python
# launcher/tests/updater/test_state_machine.py
import pytest
from neko_launcher.updater.state_machine import validate_transition, StateTransitionError
from neko_launcher.updater.state_models import State

def test_transition_enforces_revision_increment():
    s1 = create_idle_state(revision=1)
    s2 = create_idle_state(revision=1)
    with pytest.raises(StateTransitionError, match="Revision must increment by exactly 1"):
        validate_transition(s1, s2)

def test_pre_quiesce_abort_preserves_committed_and_previous():
    current = create_preparing_state(revision=2)
    aborted = transition_pre_quiesce_abort(current, error_code="CANCELLED")
    validate_transition(current, aborted)
    assert aborted.phase == "CLEANING" or aborted.phase == "IDLE"
    assert aborted.committed == current.committed
    assert aborted.previous == current.previous
    assert aborted.failed == current.observed
    assert aborted.transaction is None

def test_illegal_rollback_sequence_reduction_rejected():
    # Attempting to roll back highwater floor
    current = create_rollback_state(revision=5, highwater_seq=10)
    illegal_next = create_idle_state(revision=6, highwater_seq=9)  # Lower floor!
    with pytest.raises(StateTransitionError, match="Highwater floor cannot decrease"):
        validate_transition(current, illegal_next)
```

- [ ] **Step 2: Run pytest to verify genuine RED**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_state_machine.py`
Expected: FAIL.

- [ ] **Step 3: Implement transition validation & step generators**

Implement `launcher/src/neko_launcher/updater/state_machine.py` strictly matching the table in Section 8.1:
- `ENROLLING -> ENROLLING / IDLE(false)`
- `IDLE(false) -> IDLE(true)`
- `IDLE -> PREPARING`
- `PREPARING -> PREPARING` (mutation progression)
- `PREPARING -> QUIESCING`
- `QUIESCING -> PROBATION`
- `PROBATION -> CLEANING` (commit)
- `PREPARING -> CLEANING/IDLE` (pre-quiesce abort)
- `QUIESCING/PROBATION -> ROLLING_BACK`
- `ROLLING_BACK -> ROLLING_BACK` (drain & restore steps)
- `ROLLING_BACK -> CLEANING/IDLE` (rollback selection)
- `CLEANING -> CLEANING -> IDLE`
- `Any -> REPAIR_REQUIRED`

- [ ] **Step 4: Run pytest and Ruff to verify GREEN**

Run: `build/venv-5.1/Scripts/python.exe -m pytest -q tests/updater/test_state_machine.py`
Run: `build/venv-5.1/Scripts/python.exe -m ruff check src/neko_launcher/updater/state_machine.py tests/updater/test_state_machine.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher/src/neko_launcher/updater/state_machine.py launcher/tests/updater/test_state_machine.py
git commit -m "feat(updater): implement exhaustive state transition automaton"
```
