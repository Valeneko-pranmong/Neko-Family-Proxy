# v5.1.2 Release Authority, Build & Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. All behavior changes follow `superpowers:test-driven-development`; each task requires an independent `ag/gemini-pro-agent` review with Critical 0 / Important 0.

**Goal:** Make release sequence custody non-reusable, separate production signing from ordinary workers, build one exact signed v5.1.2 component/envelope/Installer set, publish machine assets only to the dedicated Updates channel, and mechanically prove the packaged 5.1.2→5.1.3-proof mandatory-update lifecycle.

**Architecture:** Use an external hash-chained Production Sequence Authority Ledger as the only durable sequence allocator, with cryptographic-history cross-checks. Refactor release control into deterministic pure/build phases plus controller-only production-signing/publication phases. Compare proof and production packaged contents mechanically and require the baseline `NekoUpdater.exe` to be byte-identical; exercise update/rollback/recovery through packaged E2E rather than mocks alone.

**Tech Stack:** Python, pytest, Ruff, Git/GitHub CLI through injected executors, Ed25519 `release-v2` envelope tooling, PyInstaller/Inno Setup, existing updater transaction/recovery stack.

**Spec:** `docs/superpowers/specs/2026-09-13-neko-family-5-1-2-baseline-forced-update-revision-3-4.md`

**Master plan:** `docs/superpowers/plans/2026-09-13-neko-family-5-1-2-baseline-release-implementation.md`

**Runtime prerequisite:** `docs/superpowers/plans/2026-09-13-v512-runtime-trust-enrollment.md`; RT0/K1's signed trust-profile architecture is frozen at plan approval, then RT1 is the first executable trust task. RA1+ remains blocked until exact `RT1_CODE_HEAD` packaged conformance evidence is independently accepted as `UPDATER_TRUST_FEASIBLE / C0_I0`, canonical `docs/superpowers/evidence/v512-k1-acceptance.json` is sealed in `K1_ACCEPTANCE_COMMIT`, the runtime plan's Git-only **RT1 security-tool immutability guard** passes, and only then `scripts/verify_v512_k1_acceptance.py --require-git-immutability` passes for exact `K1B_CUSTODY_SHA256`; `ARCHITECTURE_FEASIBILITY_REGRESSION` stops RA1+.

## Global Constraints

- Provisional seq8/stable-0008 is not permanent. Actual baseline sequence is allocated from fresh authenticated history + ledger immediately before reservation.
- A production sequence is consumed forever from its first valid `RESERVED` event; later `SIGNED`/`PUBLISHED`/`FAILED`/`RETIRED` records are legal same-sequence lifecycle events, not new allocations.
- Production signing private key is never available to Hermes implementer/reviewer.
- Do not execute `gh auth token`; do not pass `Authorization: Bearer ...` in child-process argv/logs.
- Human repo is not the machine update channel.
- Production machine release contains exactly `release-v2.json`, `NekoLauncher.exe`, `NekoUpdater.exe`, `NekoProxyCore.zip`.
- Proof uses a separately Profile-Authority-signed proof trust profile containing only the K1A Proof Release Authority public key; production uses a separately signed production profile containing only authenticated production release public key(s). Neither consumes/reuses the other's release signing authority.
- Profile Authority and Proof Release Authority private keys are separate controller-only non-production authorities and are distinct from production release signing authority. RA workers receive only K1A public authority records, exact K1B-A profile bytes, K1B-B **feasibility** fixture/envelope custody as a validation anchor, and the immutable `docs/superpowers/evidence/v512-k1-acceptance.json`; K1B-B Launcher/Updater/Core fixture bytes are never final RA8/RA9 component inputs, and no non-production or production private key enters Hermes.
- K1A canonical public custody is `E:\Github\authority\v512-update-profile-authority\public-v1.json` for Profile Authority and `E:\Github\authority\v512-proof-release-authority\public-v1.json` for Proof Release Authority. K1B-A canonical signed profile custody paths are `E:\Github\artifacts\v512-update-trust-profiles\production\update-profile-v1.json` and `E:\Github\artifacts\v512-update-trust-profiles\proof\update-profile-v1.json`; K1B-B canonical manifest is `E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json`, pinned by accepted `K1B_CUSTODY_SHA256`. Plan approval creates/signs none of them.
- For accepted Spec §9/§10 evidence, the freshly rebuilt proof-baseline Updater must be byte-identical to the same-source/same-toolchain production-equivalent baseline Updater measured in that RA8/RA9 run; K1 synthetic feasibility hashes do not substitute for this final equivalence proof.
- No task in this implementation plan performs real production signing/public GitHub mutation. Release-phase controller gates are described at the end.

---

## Task RA1: Implement Append-Only Production Sequence Authority Ledger

**Files:**
- Create: `scripts/production_sequence_ledger.py`
- Create: `launcher/tests/test_production_sequence_ledger.py`

**Interface contract:** the first record of a production ledger is exactly one immutable `SequenceLedgerGenesis`; all later records are `SequenceLedgerEvent`. `SequenceLedgerGenesis` has `record_type="GENESIS"`, exact historical `floor_binding: AuthenticatedProductionBinding`, optional corroborated `floor_provenance_source_commit`, `timestamp`, and `previous_entry_sha256=None`. `SequenceLedgerEvent` has fields `record_type="EVENT"`, `sequence`, `release_id`, lifecycle `status`, `version`, `channel`, `source_commit`, `component_set_sha256`, optional `payload_sha256` / `envelope_sha256` / `key_id`, `timestamp`, and `previous_entry_sha256`. Genesis anchors pre-ledger cryptographic history without fabricating historical `RESERVED/SIGNED/PUBLISHED` lifecycle events.

Authenticated production history is modeled explicitly rather than collapsed to an integer:

```python
@dataclass(frozen=True)
class AuthenticatedProductionBinding:
    sequence: int
    release_id: str
    payload_sha256: str
    envelope_sha256: str
    key_id: str

@dataclass(frozen=True)
class AuthenticatedHistorySnapshot:
    bindings_by_sequence: Mapping[int, AuthenticatedProductionBinding]
    provenance_source_commit_by_sequence: Mapping[int, str]
    live_updates_sequences: frozenset[int]
    highest_authenticated_sequence: int
    authenticated_bindings_sha256: str
    snapshot_sha256: str

@dataclass(frozen=True)
class SequenceLedgerGenesis:
    record_type: Literal["GENESIS"]
    floor_binding: AuthenticatedProductionBinding
    floor_provenance_source_commit: str | None
    timestamp: str
    previous_entry_sha256: None

@dataclass(frozen=True)
class VerifiedSequenceLedger:
    genesis: SequenceLedgerGenesis
    events: tuple[SequenceLedgerEvent, ...]
    latest_entry_sha256: str

@dataclass(frozen=True)
class ReconciledSequenceAuthority:
    authenticated_bindings_sha256: str
    history_snapshot_sha256: str
    genesis_floor_sequence: int
    latest_ledger_entry_sha256: str
    highest_authenticated_sequence: int
    highest_consumed_sequence: int
    next_unused_sequence: int
```

Public functions are `verify_ledger(path: Path) -> VerifiedSequenceLedger`, `initialize_genesis(session: SequenceAuthoritySession, genesis: SequenceLedgerGenesis) -> str`, `reconcile_ledger_with_authenticated_history(*, ledger: VerifiedSequenceLedger, authenticated_history: AuthenticatedHistorySnapshot) -> ReconciledSequenceAuthority`, `next_unused_sequence(authority: ReconciledSequenceAuthority) -> int`, `append_event(path: Path, event: SequenceLedgerEvent, expected_previous_sha256: str) -> str`, `latest_sequence_state(events: tuple[SequenceLedgerEvent, ...], sequence: int) -> SequenceLedgerEvent | None`, and `open_authority_session(path: Path) -> ContextManager[SequenceAuthoritySession]`. `initialize_genesis` is legal only while the session lock is held and only when the ledger file has no record; genesis is never rewritten, regenerated, or advanced.

`SequenceAuthoritySession` is the serialization authority for ledger genesis and every legitimate production authority-advancing action. While its Windows file lock is held, `read_verified() -> VerifiedSequenceLedger` re-reads the ledger from disk and `append(event, expected_previous_sha256) -> str` appends/fsyncs one validated event without reacquiring the lock. Authorized controller paths for one-time genesis creation, `RESERVED`, production signing + `SIGNED`, and public promotion + `PUBLISHED` must all hold this same session across their fresh authenticated-history load/reconciliation and the authority-advancing action. **Every legitimate production signer/publisher/controller instance must share this exact external ledger/lock path; no second writer authority is permitted.** Pre-ledger signed authorities are legal only at or below the immutable genesis floor; the exact genesis floor binding must remain present and cryptographically identical in fresh history forever. Any authenticated authority above the genesis floor with no corresponding ledger allocation is `RELEASE_AUTHORITY_RECONCILIATION_REQUIRED`. An exact signed binding discovered while that same sequence is ledger-`RESERVED` is recoverable only as `SIGNED_APPEND_REQUIRED`; an exact live-public binding while ledger state is `SIGNED` is recoverable only as `PUBLISHED_APPEND_REQUIRED`. Neither recovery state allocates/re-signs/re-publishes; it only completes the missing durable lifecycle append after re-verification under the same lock. The convenience `append_event(...)` may wrap one short session for non-controller/unit use but controller release flow must use `open_authority_session(...)`.

Reconciliation fails closed with `RELEASE_AUTHORITY_RECONCILIATION_REQUIRED` when the genesis floor binding disappears/changes, when the same sequence disagrees on cryptographically authenticated fields (`release_id`, signed payload SHA, envelope SHA, key ID, signed payload/component binding), when an authenticated sequence above the genesis floor has no ledger allocation, or when ledger lifecycle cannot be explained by an exact recovery state. `source_commit` is **not present in signed release-v2** and therefore is not part of `AuthenticatedProductionBinding`; it remains immutable controller/build provenance recorded from the first post-genesis `RESERVED` ledger event. When controller/custody evidence supplies a provenance source commit for an authenticated envelope, a disagreement with that reserved `source_commit` is a separate hard stop `RELEASE_PROVENANCE_RECONCILIATION_REQUIRED`. Absence of source-commit provenance on a live public envelope never causes the provider to invent or infer one. Historical authenticated records lower than the genesis floor may be discovered later if they are internally conflict-free; they never lower or reuse the floor. `next_unused_sequence` is derived only from the reconciled authority as `max(genesis.floor_binding.sequence, highest_authenticated_sequence, highest_consumed_sequence) + 1`; no reservation/allocation API accepts a bare highest-authenticated integer.

Authoritative ledger path is always supplied by controller/config; never hard-code it inside the repo.

**RA1 TDD execution order is exact and non-interleaved:** all tests first, then one complete RED, then implementation, then complete GREEN. No partial implementation is allowed before the full RED command.

- [ ] **Step 1 — Author the complete RA1 RED matrix before writing production code:** one-time genesis creation from an exact historical floor binding; second/mutated genesis rejection; ledger-without-genesis rejection; genesis floor disappearance/rebinding rejection; later discovery of non-conflicting lower historical authority; permanent `RESERVED` consumption above the floor; `RESERVED→SIGNED→PUBLISHED`; exact `RESERVED` + authenticated signed binding classified `SIGNED_APPEND_REQUIRED`; exact `SIGNED` + verified live-public binding classified `PUBLISHED_APPEND_REQUIRED`; authenticated above-floor sequence with no `RESERVED` hard-stop; second allocation rejection; immutable ledger allocation fields including controller `source_commit`; immutable payload/envelope/key after `SIGNED`; stale previous digest; `FAILED` terminal consumption; authenticated-history higher/lower cases; every same-sequence cryptographic release_id/payload/envelope/key conflict; separate controller/custody provenance-source mismatch; live authenticated history with no source-commit provenance; concurrent/stale append; authority-session lock serialization; and session append/readback without nested lock acquisition.

Representative assertions include a genesis floor at exact authenticated seq7 yielding `next_unused_sequence(...) == 8`, a reserved seq8 making next-unused 9, a fresh provider that loses/rebinds seq7 failing closed, and exact crash-recovery classification for signed-before-ledger-append / published-before-ledger-append without re-signing or re-publishing.

- [ ] **Step 2 — Run one complete RA1 RED command.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_production_sequence_ledger.py -q
```

Expected RED: the module/session/reconciliation/lifecycle contracts do not exist or fail the complete matrix. Environment/import failures unrelated to the missing contract do not count.

- [ ] **Step 3 — Implement only after Step 2 RED:** canonical genesis/event serialization/hash, one-time genesis initialization, full-chain verification, `SequenceAuthoritySession` Windows lock/session, append-only lifecycle validation, atomic append/fsync, reconciliation/recovery classification, and next-unused derivation. Do not synthesize historical lifecycle events and do not repair/rewrite ledger contents automatically.

Each JSONL record carries a canonical body plus `entry_sha256`; record 1 is the immutable genesis with no predecessor, and every later event body’s `previous_entry_sha256` equals the preceding record digest. `open_authority_session()` holds the serialization lock until its context exits.

- [ ] **Step 4 — Run the complete RA1 matrix GREEN and verify cross-check cases remain GREEN.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_production_sequence_ledger.py -q
.venv\Scripts\ruff.exe check ../scripts/production_sequence_ledger.py tests/test_production_sequence_ledger.py
cd ..
git diff --check
```

- [ ] **Step 5 — Commit exactly RA1 files.**

```cmd
git add scripts/production_sequence_ledger.py launcher/tests/test_production_sequence_ledger.py
git commit -m "feat: add production sequence authority ledger"
```

Legal lifecycle remains exact:

```text
START     -> RESERVED
RESERVED  -> SIGNED | FAILED
SIGNED    -> PUBLISHED | FAILED
PUBLISHED -> RETIRED
FAILED    -> terminal
RETIRED   -> terminal
```

No other transition is valid. `PUBLISHED` is not rewritten to `FAILED`; a later bad release is handled by a newer sequence plus rollback/recovery evidence. A same-sequence event is not a second allocation when it follows this graph and preserves the allocation binding.

**Review:** C0/I0. Reviewer must verify no production code existed before the complete RED evidence, that the historical seq7 authority can be anchored exactly once without fabricated lifecycle history, that missing post-genesis lifecycle writes have bounded recovery rather than sequence reuse/re-sign/re-publish, and that controller authority advancement remains inside one ledger serialization session. Sol-high is allowed only if the normal reviewer finds a genuine atomicity/concurrency authority conflict.

---

## Task RA2: Make Release Controller Consume Ledger Allocation Instead Of `release_target.json` Sequence

**Files:**
- Create: `scripts/authenticated_production_history.py`
- Modify: `scripts/release_controller.py`
- Modify: `scripts/derive_version.py`
- Modify: `scripts/kanban_release_adapter.py` to retire legacy automatic release-worker dispatch and consume the changed semantic-intent API only for read-only readiness observation
- Modify: `scripts/publish_atomic_release.py` to stop deriving sequence from tag/version
- Modify: `scripts/verify_github_release_assets.py` to verify against an explicit authenticated expected release binding rather than `get_release_sequence(tag)`
- Modify: `release_target.json`
- Modify existing: `tests/test_derive_version.py`, `tests/test_release_intent.py`, `tests/test_kanban_adapter.py`, `tests/test_e2e_release_pipeline.py`, and `tests/test_release_controller_split.py` for the semantic-intent API/controller flow.
- Create: `launcher/tests/test_authenticated_production_history.py`
- Modify: `launcher/tests/test_publish_atomic_release.py`, `launcher/tests/test_verify_github_release_assets.py`

**Interface contract:** `ReleaseTargetIntent(source_base: str, target: str, intent: Literal["user_bug"])`; `ReleaseAllocation(sequence: int, release_id: str, ledger_entry_sha256: str, component_set_sha256: str, authenticated_bindings_sha256: str, history_snapshot_sha256: str)`. `load_release_target_intent(path: Path) -> ReleaseTargetIntent` parses the exact semantic-only JSON file. `source_base` is the accepted Launcher/Updater source-build base (currently `v5.1.1`), **not** the Human/public stable version (`v5.1.0`) and **not** a Core-authority selector; Core authority is an independent frozen RA3 input.

Fresh history is never supplied as a prebuilt snapshot to an authority-changing function. `scripts/authenticated_production_history.py` defines:

```python
class AuthenticatedHistoryProvider(Protocol):
    def load(self) -> AuthenticatedHistorySnapshot: ...

@dataclass(frozen=True)
class AuthenticatedEnvelopeRecord:
    source_id: str
    source_kind: Literal["custody", "live_updates"]
    envelope_bytes: bytes
    provenance_source_commit: str | None

class CompositeAuthenticatedHistoryProvider:
    def __init__(
        self,
        *,
        enumerate_records: Callable[[], tuple[AuthenticatedEnvelopeRecord, ...]],
        trusted_public_keys: Mapping[str, bytes],
    ) -> None: ...
    def load(self) -> AuthenticatedHistorySnapshot: ...


def load_custody_records(custody_root: Path) -> tuple[AuthenticatedEnvelopeRecord, ...]: ...
def append_custody_record(custody_root: Path, record: AuthenticatedEnvelopeRecord, *, expected_index_sha256: str | None) -> str: ...
def bootstrap_sequence_ledger(*, ledger_path: Path, history_provider: AuthenticatedHistoryProvider, expected_floor: AuthenticatedProductionBinding, expected_floor_provenance_source_commit: str | None) -> SequenceLedgerGenesis: ...
```

Production custody root is fixed by controller configuration to `E:\\Github\\artifacts\\v512-production-authority-custody`. It contains `history-index-v1.json` plus exact envelope bytes under `envelopes/<envelope_sha256>.json`. The index is canonical JSON with exact closed schema `{schema_version: 1, entries: [...]}`; each custody entry contains `source_id`, `source_kind="custody"`, `envelope_relpath`, `envelope_sha256`, and nullable `provenance_source_commit`. `load_custody_records()` rejects absolute/escaping/duplicate paths, hash mismatch, malformed index, duplicate source IDs, wrong source kind, and non-canonical envelope bytes before returning records. `append_custody_record()` is exact-idempotent, uses temp-file + file fsync + atomic replace + parent/index readback, rejects stale expected index digest or any conflicting duplicate binding, and never overwrites existing envelope bytes. `expected_index_sha256=None` is legal only when `history-index-v1.json` is absent for first creation; if an index already exists, `None` is stale and fails closed. It never scans arbitrary artifact directories at production reservation time.

The already-audited seq7 bootstrap source must be captured into that custody before any production reservation. Current read-only source evidence is `E:\\Github\\artifacts\\main-auto-release\\34601286641-fb0d2e734ee611d75933ccd90cb82347c0b578bd\\5.1.3\\publish\\release-v2.json`; fresh verification on 2026-09-13 established `sequence=7`, `release_id=stable-0007`, `key_id=neko-update-prod-1`, payload SHA-256 `d62602d3b90ee0d6b251b6eee7d1aa3e1b5db591f1cd280f723bc011c12fed98`, envelope SHA-256 `a806be8e9f1308df1d4ab63e08b319112723a49b768bbb1a2af6189d5ee625c9`, size 1632, with provenance commit `fb0d2e734ee611d75933ccd90cb82347c0b578bd` present in the canonical repository. These values are evidence expectations, not sequence-allocation constants: the controller must re-read/reverify the exact bytes before custody and must hard-stop `PRODUCTION_HISTORY_EVIDENCE_MISSING` or `PRODUCTION_HISTORY_EVIDENCE_CHANGED` on absence/mismatch rather than falling back to a remembered highest integer.

Every `load()` invokes `enumerate_records()` afresh, verifies every envelope cryptographically, and derives `AuthenticatedProductionBinding` **only** from verified release-v2 envelope/payload fields. It rejects conflicting duplicate signed bindings for one sequence. `provenance_source_commit` is optional non-cryptographic controller/custody metadata: live Updates-channel records must set it to `None`; controller-custodied records may provide it. Multiple non-null provenance commits for the same exact signed binding are rejected with `RELEASE_PROVENANCE_RECONCILIATION_REQUIRED`. The snapshot stores at most one corroborated non-null provenance commit per sequence separately from the authenticated binding and records `live_updates_sequences` only for exact verified records enumerated from the production Updates endpoint; custody presence alone can never satisfy publication recovery. `authenticated_bindings_sha256` is the canonical digest of only the cryptographically verified per-sequence bindings; `snapshot_sha256` is a separate freshness digest covering those bindings plus source kinds/source IDs/provenance claims. The controller’s production enumerator combines `load_custody_records(...)` with fresh live production Updates-channel `release-v2.json` records when that channel exists; no cached snapshot object is accepted as authority.

`bootstrap_sequence_ledger(...)` is the only production genesis path. It acquires `open_authority_session(ledger_path)`, requires no existing ledger record, calls `history_provider.load()` **inside that lock**, requires `highest_authenticated_sequence == expected_floor.sequence` and exact equality of the expected floor binding/provenance, writes/fsyncs/read-backs one genesis record, and releases. If a ledger already exists it only verifies and returns an exact matching genesis; it never reinitializes it. Missing/changed/newer pre-ledger authority is `PRODUCTION_HISTORY_EVIDENCE_CHANGED` and blocks bootstrap.

`reserve_release_sequence(*, ledger_path: Path, history_provider: AuthenticatedHistoryProvider, target: ReleaseTargetIntent, source_commit: str, component_set_sha256: str) -> ReleaseAllocation` requires an already initialized genesis, acquires `open_authority_session(ledger_path)`, calls `history_provider.load()` **inside that session**, re-reads/verifies the ledger inside the same session, reconciles, derives next-unused, appends/fsyncs `RESERVED`, and read-backs the append before releasing the lock. A newer/conflicting external authenticated authority yields `RELEASE_AUTHORITY_RECONCILIATION_REQUIRED`; lock/session staleness yields `RELEASE_AUTHORITY_STALE`; neither path silently retries.

`release_target.json` schema after this task is semantic intent only:

```json
{
  "source_base": "v5.1.1",
  "target": "v5.1.2",
  "intent": "user_bug"
}
```

Remove `seq`, `stable_id`, `installer_repo`, and the ambiguous legacy field name `stable` from this authority/intention file. Repository routing lives in explicit channel/publisher configuration, sequence/release_id come only from the Production Sequence Authority Ledger, and `source_base` is used only for Launcher/Updater source-version/build compatibility checks; it never selects or fetches Core authority.

- [ ] **Step 1: Write RED tests against the current legacy `release_target.json` shape. The new semantic-intent parser must reject authority/routing fields instead of silently trusting or ignoring them, then accept the exact new schema after the file is migrated.**

```python
def test_legacy_target_cannot_supply_sequence_or_repo_authority():
    legacy = {
        "stable": "v5.1.1",
        "target": "v5.1.2",
        "seq": 6,
        "stable_id": "stable-0006",
        "intent": "user_bug",
        "installer_repo": "Valeneko-pranmong/Neko-Family-Proxy-Installer",
    }
    with pytest.raises(ValueError, match="forbidden release-target field"):
        parse_release_target_data(legacy)


def test_semantic_target_plus_ledger_history_allocates_sequence(tmp_path):
    target = ReleaseTargetIntent(source_base="v5.1.1", target="v5.1.2", intent="user_bug")
    history_provider = fake_history_provider(sequence=7, release_id="stable-0007")
    allocation = reserve_release_sequence(
        ledger_path=tmp_path / "ledger.jsonl",
        history_provider=history_provider,
        target=target,
        source_commit="a" * 40,
        component_set_sha256="b" * 64,
    )
    assert allocation.sequence == 8
    assert allocation.release_id == "stable-0008"
```

- [ ] **Step 2: RED test ledger highest=8 produces seq9 even when semantic version remains 5.1.2.**

- [ ] **Step 3: Add RED history-provider/controller tests:** prove `bootstrap_sequence_ledger()` and reservation call `history_provider.load()` only after the ledger authority session is acquired; seq7 exact custody initializes one genesis, while missing/changed seq7 or a newly discovered seq8 before genesis hard-stops without creating a ledger; mutate the provider’s enumerated history between a preflight observation and the locked call and prove reservation sees the newer history and stops/advances correctly; same-sequence cryptographic `release_id/payload/envelope/key` disagreement stops before append; a conflicting non-null controller/custody `provenance_source_commit` yields `RELEASE_PROVENANCE_RECONCILIATION_REQUIRED`; live authenticated records with `provenance_source_commit=None` remain valid and never synthesize source provenance; `live_updates_sequences` cannot be forged by a custody record; provider conflict/newer external authority hard-stops; concurrent ledger append serializes; no failure path silently retries. Add custody-index tests for canonical closed schema, fixed-root relative path confinement, atomic/idempotent append, stale-index guard, envelope hash/readback, malformed/escaping/duplicate entries, and seq7 bootstrap evidence verification. Add publisher/verifier tests proving tag `v5.1.2` cannot manufacture seq6 and expected sequence/release_id come from explicit allocation evidence. Add legacy-automation RED tests proving `poll_github_and_create_tasks()` never dispatches a Hermes release worker or embeds `release_controller.py` execution for the v5.1.2 semantic intent, and that the `release_controller.py` CLI cannot reserve sequence/sign/publish from argv-driven worker execution.

- [ ] **Step 4: Run the complete RA2 RED set before changing production/release tooling.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -m pytest tests\test_derive_version.py tests\test_release_intent.py tests\test_kanban_adapter.py tests\test_e2e_release_pipeline.py tests\test_release_controller_split.py launcher\tests\test_authenticated_production_history.py launcher\tests\test_publish_atomic_release.py launcher\tests\test_verify_github_release_assets.py -q
```

Expected RED: legacy semantic-intent parsing/tuple callers still expose sequence authority, the ambiguous `stable` field still carries source-base semantics, the legacy adapter can still dispatch a Hermes worker that directly invokes `release_controller.py`, production reservation does not yet load `AuthenticatedHistoryProvider` from inside the ledger authority session, custody-index APIs do not exist, and fresh/newer/conflicting history cases are not yet fail-closed.

- [ ] **Step 5: Refactor `release_target.json` and `derive_version.py` to the exact semantic-intent schema/API above. Rename legacy `stable` semantics to `source_base`; keep the accepted source/build base `v5.1.1` distinct from the public/manual-migration baseline `v5.1.0`. Retire `get_release_sequence(version)` from all production/release authority paths; semantic version must never allocate or validate a production sequence.**

- [ ] **Step 6: Update existing root tests `tests/test_derive_version.py` and `tests/test_release_intent.py` for `ReleaseTargetIntent`; update adapter/controller/e2e fixtures that currently unpack `(stable, target, seq, stable_id)`. Retire legacy auto-release dispatch: for the new semantic intent `kanban_release_adapter.py` may observe successful Main Source Acceptance and report `CONTROLLER_RELEASE_REQUIRED`, but it must not create a Hermes release worker/task, must not place `release_controller.py` in a task body, and must not perform sequence reservation/signing/publication. The repository `release_controller.py` CLI is preflight/build-only after this task and must hard-stop `CONTROLLER_ACTION_REQUIRED` before any authority-changing API; later CR0+ controller execution calls the typed authority APIs directly from the controller session rather than through a worker CLI.**

- [ ] **Step 7: Update `publish_atomic_release.py` and `verify_github_release_assets.py`: their manifest/release verification APIs receive the expected authenticated `ReleaseAllocation`/binding explicitly from controller evidence and never call `get_release_sequence(tag)`.**

- [ ] **Step 8: Make controller require the explicit external ledger path, canonical production custody root, `AuthenticatedHistoryProvider`, and frozen component-set digest. Production provider construction must enumerate only verified custody-index records plus fresh live Updates-channel records; never rglob arbitrary historical artifact trees during reservation. Wire the one-time seq7 genesis bootstrap through `bootstrap_sequence_ledger()` and require genesis before reservation. Remove every production reservation API that accepts a prebuilt `AuthenticatedHistorySnapshot`/`ReconciledSequenceAuthority`. Reservation must load history and ledger from inside `open_authority_session()` as specified above. Expose one shared `fresh_reconcile_locked(session, history_provider) -> ReconciledSequenceAuthority` helper for RA4 signing and RA5 publication guards.**

- [ ] **Step 9: Run GREEN/Ruff/diff-check from repository root so both root and launcher test suites are addressed.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -m pytest tests\test_derive_version.py tests\test_release_intent.py tests\test_kanban_adapter.py tests\test_e2e_release_pipeline.py tests\test_release_controller_split.py launcher\tests\test_authenticated_production_history.py launcher\tests\test_publish_atomic_release.py launcher\tests\test_verify_github_release_assets.py -q
launcher\.venv\Scripts\ruff.exe check scripts\authenticated_production_history.py scripts\derive_version.py scripts\release_controller.py scripts\kanban_release_adapter.py scripts\publish_atomic_release.py scripts\verify_github_release_assets.py tests launcher\tests\test_authenticated_production_history.py launcher\tests\test_publish_atomic_release.py launcher\tests\test_verify_github_release_assets.py
git diff --check
```

- [ ] **Step 10: Commit.**

```cmd
git add scripts/authenticated_production_history.py scripts/derive_version.py scripts/release_controller.py scripts/kanban_release_adapter.py scripts/publish_atomic_release.py scripts/verify_github_release_assets.py release_target.json tests/test_derive_version.py tests/test_release_intent.py tests/test_kanban_adapter.py tests/test_e2e_release_pipeline.py tests/test_release_controller_split.py launcher/tests/test_authenticated_production_history.py launcher/tests/test_publish_atomic_release.py launcher/tests/test_verify_github_release_assets.py
git commit -m "fix: separate semantic release intent from sequence authority"
```

**Review:** C0/I0. Reviewer must explicitly confirm that no successful-main/semantic-intent path can auto-dispatch a worker into sequence reservation, production signing, or publication; source acceptance is only a readiness signal for later controller gates.

---

## Task RA3: Define Exact Final Component Set And Canonical Baseline Metadata

**Prerequisite:** RA1 and RA2 accepted C0/I0. RA3 produces every component-set/metadata type consumed by RA4+; no signing task starts before RA3 is accepted.

**Files:**
- Create: `scripts/core_authority_custody.py`
- Modify: `scripts/build_software_release_v2.py`
- Modify: `scripts/release_controller.py`
- Create: `launcher/tests/test_core_authority_custody.py`
- Modify: `launcher/tests/test_build_software_release_v2.py`
- Modify: `tests/test_release_controller_split.py`

**Produces:**

```python
@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_id: str
    version: str
    sha256: str
    size: int
    installed_identity_sha256: str
    artifact_format: str

@dataclass(frozen=True)
class CoreAuthorityBinding:
    authority_version_tag: str
    authority_release_sequence: int
    authority_release_id: str
    authority_payload_sha256: str
    authority_envelope_sha256: str
    authority_key_id: str
    core_source_commit: str
    provenance_sha256: str

@dataclass(frozen=True)
class TrustProfileBinding:
    profile_id: str
    channel: str
    owner: str
    repository: str
    profile_authority_key_id: str
    profile_authority_public_key_sha256: str
    profile_envelope_sha256: str
    keyset_sha256: str

@dataclass(frozen=True)
class FinalComponentSet:
    source_commit: str
    launcher: ArtifactIdentity
    updater: ArtifactIdentity
    core: ArtifactIdentity
    core_authority: CoreAuthorityBinding
    trust_profile: TrustProfileBinding
    component_set_sha256: str

@dataclass(frozen=True)
class UnsignedBaselineEvidence:
    sequence: int
    release_id: str
    component_set_sha256: str
    payload_sha256: str
    payload_path: Path
```

`collect_final_component_set(...) -> FinalComponentSet` hashes the exact staged Launcher/Updater/Core bytes, requires the exact controller-custodied **production** `update-profile-v1.json` to verify under the RT1 Profile Authority root, materializes one `TrustProfileBinding`, and computes one canonical component-set digest. Launcher/Updater bytes are built from the approved final `source_commit`; Core is **not claimed to be built from that commit** and is never fetched from the Human release surface during the final freeze. Core is loaded once from controller-owned canonical Core-authority custody and `CoreAuthorityBinding` freezes the exact verified authority version/sequence/release_id/envelope/payload/key, the transitively authenticated `core_source_commit` from the verified Core manifest, and a canonical provenance digest over the exact custody/source identifiers. The canonical `component_set_sha256` covers all three `ArtifactIdentity` values plus `source_commit`, the complete `CoreAuthorityBinding`, and the complete `TrustProfileBinding`. Therefore changing Core bytes/authority **or** the production trust-profile envelope/keyset/profile authority/routing after reservation consumes the sequence and requires a new freeze/reservation, even though the trust profile is separately Profile-Authority-signed and is not one of the four machine-release assets. `build_unsigned_baseline(*, allocation: ReleaseAllocation, component_set: FinalComponentSet) -> UnsignedBaselineEvidence` writes canonical unsigned payload bytes from only that accepted allocation/component set. Baseline metadata is stable, non-mandatory, and sets `minimum_supported_sequence == allocation.sequence`.

`scripts/core_authority_custody.py` defines `VerifiedCoreAuthority(binding: CoreAuthorityBinding, core_zip_path: Path, core: ArtifactIdentity)` plus `load_verified_core_authority(custody_root: Path, trusted_public_keys: Mapping[str, bytes]) -> VerifiedCoreAuthority` and `bootstrap_core_authority_custody(*, source_envelope: Path, source_core_zip: Path, custody_root: Path, trusted_public_keys: Mapping[str, bytes], expected: CoreAuthorityBinding) -> VerifiedCoreAuthority`. Custody uses a closed canonical `core-authority-v1.json` + immutable `release-v2.json` + `NekoProxyCore.zip`; bootstrap is exact-idempotent, rejects any pre-existing byte/metadata mismatch, writes through temp/fsync/atomic replace/readback, and loader re-verifies signature, payload/envelope/core hashes/sizes/installed identity/Core-manifest source commit every call. No function performs GitHub discovery.

Canonical initial Core authority custody for this v5.1.2 release is controller-configured at `E:\\Github\\artifacts\\v512-core-authority-custody`. It is bootstrapped from the exact historical local bytes `E:\\Github\\artifacts\\main-auto-release\\34735305323-f4afa51878ccea590c33f758c9da70eb3ddbd43b\\5.1.2\\publish\\release-v2.json` + `NekoProxyCore.zip`, not from a live Human release. Fresh read-only verification on 2026-09-13 established production key `neko-update-prod-1`, authority `sequence=6 / release_id=stable-0006 / version=v5.1.2`, payload SHA-256 `1ae606758302f485c8f31f324eafedeb9c182f8f0f9ab0b7bdd82bc4eab94c9f`, envelope SHA-256 `989b0469baaa819ff619b5a83a59df5a0cd5669a80d43285f2d36bd9bb392b38`, Core SHA-256 `4593d6b1bb201179df14412b4033815fa53b1e63b3b4593cf1d1e41d8721de71`, size `156001298`, installed identity `0e0cd94c0a56eb2e20897035f6445d60be9cbcfcdd21f2d0fa48c94e883a3972`, and Core-manifest source commit `6ab94bb`. These are custody expectations, not permission to reuse production sequence 6; final baseline allocation remains strictly above the seq7 genesis floor.

- [ ] **Step 1: Write complete Core-custody + trust-profile + component-freeze RED tests first:** bootstrap exact historical-equivalent envelope/Core bytes into temporary custody; load/readback verifies authority version/sequence/release_id, envelope SHA, payload SHA, verified key ID, Core SHA/size/installed identity and Core-manifest `source_commit`; wrong signature/hash/size/source commit, malformed/escaping custody paths, stale/pre-existing mismatch, or non-canonical metadata fail closed; repeat exact bootstrap is idempotent. Load an exact RT1-verified production trust profile fixture and prove `FinalComponentSet` carries Launcher/Updater source commit + exact `CoreAuthorityBinding` + exact `TrustProfileBinding` and deterministic `component_set_sha256`. Mutated profile envelope, profile authority key/root hash, keyset, profile id/channel/repository, proof-profile substitution, or non-production profile must fail closed or change the frozen digest. Add the real source-mapping case: `source_base=v5.1.1` affects Launcher/Updater source compatibility only, while Core loads from explicit custody with a fake network executor that must receive zero calls.**

- [ ] **Step 2: Write RED metadata test that an explicit ledger allocation plus exact `FinalComponentSet` yields baseline sequence/release-id/minimum support from that allocation.**

```python
def test_baseline_metadata_uses_reserved_sequence_as_minimum():
    unsigned = build_unsigned_baseline(
        allocation=allocation(8, "stable-0008"),
        component_set=components("5.1.2"),
    )
    document = read_payload(unsigned.payload_path)
    assert document["release_sequence"] == 8
    assert document["release_id"] == "stable-0008"
    assert document["minimum_supported_sequence"] == 8
```

- [ ] **Step 3: Write RED tests proving stale `release_target.json` sequence/release-id fields cannot influence payload generation, component identities come only from `FinalComponentSet`, stable channel/updater protocol remain strict, and baseline `mandatory` is false. Add freeze-integrity tests proving a changed Core authority envelope/key/payload/Core-manifest source commit/provenance digest **or changed signed production trust-profile binding** after component collection invalidates the frozen set rather than being silently re-resolved for signing or Installer build.**

- [ ] **Step 4: Run RA3 RED before implementing the typed component-set/metadata producer.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -m pytest launcher\tests\test_core_authority_custody.py launcher\tests\test_build_software_release_v2.py tests\test_release_controller_split.py -q
```

Expected RED: `FinalComponentSet`/`CoreAuthorityBinding`/`UnsignedBaselineEvidence` and the explicit allocation-driven builder do not yet exist, current Core resolution exposes only loose provenance and can be re-resolved independently of a frozen component set, or stale target metadata still influences the payload.

- [ ] **Step 5: Implement `core_authority_custody.py`, retire production final-freeze dependence on `resolve_core_authority()` GitHub discovery, and implement only the typed component collector, exact Core-authority evidence capture, canonical component-set digest, and unsigned metadata builder required by RED. `release_controller.py` consumes one `VerifiedCoreAuthority` loaded from explicit custody; downstream RA4/RA6 consume that frozen object and must not fetch/re-resolve Core authority. No signing/private-key access is added in RA3.**

- [ ] **Step 6: Run GREEN, affected release-controller regression, Ruff, and diff check.**

```cmd
launcher\.venv\Scripts\python.exe -B -m pytest launcher\tests\test_core_authority_custody.py launcher\tests\test_build_software_release_v2.py tests\test_release_controller_split.py -q
launcher\.venv\Scripts\ruff.exe check scripts\core_authority_custody.py scripts\build_software_release_v2.py scripts\release_controller.py launcher\tests\test_core_authority_custody.py launcher\tests\test_build_software_release_v2.py tests\test_release_controller_split.py
git diff --check
```

- [ ] **Step 7: Commit exactly the RA3 producer files.**

```cmd
git add scripts/core_authority_custody.py scripts/build_software_release_v2.py scripts/release_controller.py launcher/tests/test_core_authority_custody.py launcher/tests/test_build_software_release_v2.py tests/test_release_controller_split.py
git commit -m "feat: bind baseline metadata to exact component set"
```

**Review:** C0/I0; reviewer verifies RA3 produces the complete typed contract needed by RA4, that Core provenance is frozen before sequence reservation instead of being conflated with the Launcher/Updater source SHA, that downstream code cannot re-resolve a different Core authority after reservation, and that RA3 contains no signing path.

---

## Task RA4: Create Controller-Only Production Signing Boundary

**Prerequisite:** RA3 accepted C0/I0. RA4 consumes `UnsignedBaselineEvidence` and `FinalComponentSet`; it does not define or mutate those contracts. Immediately before any use of the shared RT1 assembler, run the runtime plan's Git-only **RT1 security-tool immutability guard**; `RT1_SECURITY_TOOL_DRIFT` blocks RA4 and reopens RT1/K1 rather than permitting a current-path substitute.

**Files:**
- Modify: `scripts/sign_software_release.py`
- Modify: `scripts/release_controller.py`
- Reuse without changing: `scripts/assemble_release_v2_envelope.py` from accepted RT1/K1 (`RT1_CODE_HEAD`); if RA4 needs to change its canonicalization/assembly contract, STOP and reopen RT1/K1 rather than forking envelope logic.
- Modify: `launcher/tests/test_sign_software_release.py`
- Regression: `launcher/tests/test_assemble_release_v2_envelope.py`
- Modify: `tests/test_release_controller_split.py`

**Produces:**

```python
@dataclass(frozen=True)
class SigningRequired:
    status: Literal["SIGNING_REQUIRED"]
    payload_path: Path
    payload_sha256: str

@dataclass(frozen=True)
class DetachedReleaseSignature:
    key_id: str
    signature: bytes

class ReleaseSigner(Protocol):
    def sign(self, canonical_payload: bytes) -> DetachedReleaseSignature: ...

@dataclass(frozen=True)
class SignedBaselineEvidence:
    sequence: int
    release_id: str
    component_set_sha256: str
    payload_sha256: str
    envelope_sha256: str
    key_id: str
    envelope_path: Path
```

Signer seam is exact as defined by the `ReleaseSigner` protocol above. `DetachedReleaseSignature.key_id` must match the exact production authority registry supplied by the controller and `signature` must be exactly 64 bytes. The signer returns only those detached values; it does not construct/write an envelope. Worker/test `signer=None` returns `SIGNING_REQUIRED` only when no already-custodied exact signed envelope exists. The controller authority-changing API is `sign_reserved_baseline(*, ledger_path: Path, custody_root: Path, history_provider: AuthenticatedHistoryProvider, production_public_keys: Mapping[str, bytes], allocation: ReleaseAllocation, unsigned: UnsignedBaselineEvidence, signer: ReleaseSigner | None) -> SignedBaselineEvidence | SigningRequired`. `production_public_keys` is not an arbitrary test/runtime trust seam in production execution: controller composition must source it from the accepted production authority/K1 evidence and require the exact approved production registry (currently `neko-update-prod-1`) with no proof key or fallback. Tests may inject an ephemeral one-key registry only in isolated unit cases. It acquires the RA1 ledger authority session and fresh-loads history inside the lock. If reconciliation reports an exact `SIGNED_APPEND_REQUIRED` recovery for this `RESERVED`, it loads the exact envelope from canonical custody, verifies sequence/release/component/payload/key binding, appends/read-backs `SIGNED`, and **does not invoke the signer**. Otherwise it hard-stops on newer/conflicting authority; if `signer=None` it returns `SIGNING_REQUIRED` with no custody/lifecycle mutation. With a real/injected signer it signs while the same serialization session is held, validates the returned `DetachedReleaseSignature`, then calls RT1's `assemble_verified_release_v2_envelope(payload_bytes=exact canonical unsigned payload, key_id=signature.key_id, detached_signature=signature.signature, release_public_keys=production_public_keys)`. It parses/re-verifies the returned envelope with the accepted verifier, derives `key_id` from the **verified envelope** rather than trusting signer metadata, verifies exact binding, atomically persists/read-backs that exact envelope through `append_custody_record(...)`, refreshes authenticated history while still locked, requires the exact binding to appear as `SIGNED_APPEND_REQUIRED`, then appends/read-backs exact `SIGNED` and releases. A crash after custody persistence but before ledger append is therefore recoverable without re-signing. Test signers use ephemeral Ed25519 keys only. Production signer custody is controller-only.

- [ ] **Step 1: Write RED test that `sign_reserved_baseline(..., signer=None)` returns `SigningRequired`, preserves exact payload SHA/path, and performs no private-key file read/signing subprocess/custody/lifecycle append when there is no recovery envelope. Add the complementary RED recovery case where exact canonical custody already contains the signed binding for ledger-`RESERVED`: `signer=None` must verify it and complete `SIGNED` without signer invocation.**

- [ ] **Step 2: Write RED test that signing helper rejects inline private-key material and never dumps environment/private-key/traceback secret values.**

- [ ] **Step 3: Write RED ephemeral-signer + shared-assembler + freshness/custody tests:** signer returns only `DetachedReleaseSignature`; `sign_reserved_baseline` invokes the accepted RT1 assembler with exact canonical payload + returned key id/signature + injected public registry; assembled envelope verifies under its test public key; `SignedBaselineEvidence` records exact sequence/release_id/component-set/payload/envelope hashes **and verified `key_id`**; a signer returning a key id absent from the exact supplied production registry, a bad-length signature, or a signature invalid for the exact payload fails before custody/lifecycle mutation; add a production-composition RED case proving the K1A Proof Release Authority key or any mixed prod+proof registry is rejected before signer invocation; history provider is loaded while ledger session is held immediately before signing; a newer/conflicting external authority prevents signer invocation; custody append is atomic/idempotent and occurs only after envelope verification; history is refreshed after custody write; successful signing requires `SIGNED_APPEND_REQUIRED` then appends/read-backs exact `SIGNED` before releasing the lock; simulate a failure after custody persistence and prove rerun performs no second signature and only completes the missing ledger append.

- [ ] **Step 4: Run the complete RA4 RED suite before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B -m pytest launcher\tests\test_sign_software_release.py launcher\tests\test_assemble_release_v2_envelope.py tests\test_release_controller_split.py -q
```

Expected RED: the explicit detached `ReleaseSigner`/`sign_reserved_baseline`/`SigningRequired`/`SignedBaselineEvidence.key_id`/shared-assembler/fresh-history-under-lock contract does not yet exist, exact production-registry enforcement is absent, and current signing helper still exposes legacy key-handling behavior.

- [ ] **Step 5: Implement the minimal callable detached-signature boundary and stable sanitized error codes; remove secret-bearing debug/exception output.** `sign_software_release.py` may own the controller-only private-key adapter but must return only `DetachedReleaseSignature`; envelope construction belongs exclusively to accepted `assemble_release_v2_envelope.py`. Do not add a second envelope serializer.

- [ ] **Step 6: Run GREEN, shared-assembler regression, Ruff, diff check, then commit exactly RA4-owned files.**

```cmd
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B -m pytest launcher\tests\test_sign_software_release.py launcher\tests\test_assemble_release_v2_envelope.py tests\test_release_controller_split.py -q
launcher\.venv\Scripts\ruff.exe check scripts\sign_software_release.py scripts\release_controller.py launcher\tests\test_sign_software_release.py launcher\tests\test_assemble_release_v2_envelope.py tests\test_release_controller_split.py
git diff --check
git add scripts/sign_software_release.py scripts/release_controller.py launcher/tests/test_sign_software_release.py tests/test_release_controller_split.py
git commit -m "refactor: isolate production release signing boundary"
```

**Review:** C0/I0, security-focused; reviewer verifies RA4 consumes only accepted RA3 + RT1 assembler interfaces, worker execution cannot read production private key material, signer output is detached-only, and no second release-envelope construction path is introduced.

---

## Task RA5: Rework Machine Publisher For `Neko-Family-Proxy-Updates` And Remove Token-In-Argv Verification

**Files:**
- Modify: `scripts/publish_atomic_release.py`
- Modify: `scripts/release_controller.py`
- Modify: `scripts/verify_github_release_assets.py`
- Modify: `launcher/tests/test_publish_atomic_release.py`
- Modify: `launcher/tests/test_verify_github_release_assets.py`

**Required machine asset set:**

```python
REQUIRED_MACHINE_ASSETS = (
    "release-v2.json",
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
)
```

Controller-facing publisher contract is exact: `publish_machine_release(*, ledger_path: Path, history_provider: AuthenticatedHistoryProvider, signed: SignedBaselineEvidence, target_commit: str, staging_dir: Path, executor: CommandExecutor) -> MachinePublishResult`. Tests inject a fake executor/history provider; workers never call this against live GitHub. The publisher is crash-idempotent: an exact live Updates binding discovered while ledger state is still `SIGNED` is `PUBLISHED_APPEND_REQUIRED`, not permission to upload/promote again.

- [ ] **Step 1: Write RED test that machine publisher targets only `Valeneko-pranmong/Neko-Family-Proxy-Updates`.**

- [ ] **Step 2: Write RED exact-asset-set + authority-freshness/recovery tests:** missing/extra asset fails before promotion; publisher acquires the RA1 authority session and calls `history_provider.load()` inside it immediately before any public promotion. Newer/conflicting authority hard-stops with zero mutation commands. If the exact signed binding is already in `live_updates_sequences` while ledger remains `SIGNED`, classify `PUBLISHED_APPEND_REQUIRED`, perform hosted/public read-only verification of the exact four assets/tag/target, append/read-back `PUBLISHED`, and issue **zero create/upload/promote commands**. Otherwise fake promotion occurs once; refresh authenticated history while the same session remains held, require the exact binding in `live_updates_sequences` (custody-only presence is insufficient), append/read-back `PUBLISHED`, then release the lock.

- [ ] **Step 3: Write RED command-capture test proving no child argv contains `gh auth token` or `Authorization: Bearer`.**

```python
def test_hosted_verification_never_exposes_token_in_argv(
    fake_exec, machine_draft_evidence, machine_staging_dir
):
    _hosted_verify_machine_channel(
        machine_draft_evidence,
        staging_dir=machine_staging_dir,
        expected_tag="v5.1.2",
        expected_target="a" * 40,
        runner=fake_exec,
    )
    flat = "\n".join(" ".join(cmd) for cmd in fake_exec.commands)
    assert "gh auth token" not in flat
    assert "Authorization: Bearer" not in flat
```

- [ ] **Step 4: Run RED publisher/verifier tests before changing the publisher.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_publish_atomic_release.py tests/test_verify_github_release_assets.py -q
```

Expected RED: machine routing still targets the legacy Human repo and/or hosted verification still emits forbidden token/curl argv.

- [ ] **Step 5: Replace hosted asset verification with one locked mechanism only:** parent Python invokes `gh api repos/{owner}/{repo}/releases/assets/{asset_id} -H "Accept: application/octet-stream"` as an argv array with `stdout` connected directly to a temporary file handle opened by the parent. Do not call `gh auth token`, do not invoke `curl`, do not place `Authorization: Bearer` in argv, do not use shell redirection, and do not print/dump environment credentials. After process success, parent flushes + `os.fsync()` + closes the file, computes exact size/SHA-256, compares against expected local identity, records verification evidence, then removes the temporary file unless a later custody contract explicitly owns it.

- [ ] **Step 6: Add tests that command capture equals the exact `gh api ... releases/assets/{asset_id} -H "Accept: application/octet-stream"` shape, hosted bytes are re-hashed after download, expected size/SHA match, and argv contains neither `gh auth token` nor `Authorization: Bearer`.**

- [ ] **Step 7: Run GREEN/Ruff/diff check and commit. Publication tests must prove the authority session spans pre-publish fresh reconciliation through fake promotion/live readback/post-publish fresh reconciliation and `PUBLISHED` append, plus crash recovery after public promotion performs read-only verification + missing append only and never duplicates public mutation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_publish_atomic_release.py tests/test_verify_github_release_assets.py -q
.venv\Scripts\ruff.exe check ../scripts/publish_atomic_release.py ../scripts/release_controller.py ../scripts/verify_github_release_assets.py tests/test_publish_atomic_release.py tests/test_verify_github_release_assets.py
cd ..
git diff --check
git add scripts/publish_atomic_release.py scripts/release_controller.py scripts/verify_github_release_assets.py launcher/tests/test_publish_atomic_release.py launcher/tests/test_verify_github_release_assets.py
git commit -m "fix: publish machine updates without token exposure"
```

The hosted machine-release verification regression file is `launcher/tests/test_verify_github_release_assets.py`; it is part of this task's required test command and commit scope.

**Review:** C0/I0.

---

## Task RA6: Bind Final Installer Provenance To The Exact Signed Envelope

**Prerequisites:** `RUNTIME_TRUST_C0_I0` (RT10) and RA1–RA5 accepted C0/I0. This is the convergence gate in the Master DAG; RA6 must not package a final signed-envelope candidate from a merely task-local RT7/RT8/RT9 state or before the RA5 publisher/verifier contract is accepted.

**Files:**
- Modify: `installer/scripts/build_beta_installer.py`
- Modify: `scripts/release_controller.py`
- Modify: `launcher/tests/test_build_beta_installer.py`
- Modify: `tests/test_release_controller_split.py`

**Build-record required fields:** source commit; injected 5.1.2 version inputs; component artifact hashes/sizes/installed identities; frozen `CoreAuthorityBinding` including authority version/sequence/release_id, authority payload/envelope/key, authenticated Core-manifest source commit, and provenance digest; frozen `TrustProfileBinding` including profile id/channel/repository, Profile Authority key id/public-root SHA, exact profile-envelope SHA, and release-keyset SHA; reserved sequence/release_id/key_id; payload SHA; signed envelope SHA; embedded envelope SHA; embedded trust-profile SHA; installer SHA/size. `source_base` remains separate Launcher/Updater source-build compatibility metadata and is not a field of `CoreAuthorityBinding` or `TrustProfileBinding`.

- [ ] **Step 1: Write RED test that Installer build refuses a signed envelope whose payload component identities differ from staged final bytes.**

- [ ] **Step 2: Write RED test that one-byte difference between supplied envelope and staged embedded envelope fails before ISCC.**

- [ ] **Step 3: Write RED test that build record includes all required provenance, `embedded_envelope_sha256 == envelope_sha256`, and `build_record.key_id == signed_baseline.key_id`; independently re-verify the embedded envelope and require its verified `key_id` to equal the same field.**

- [ ] **Step 4: Write RED test that packaged version/title inputs are 5.1.2 and stale 5.1.1 source metadata cannot leak into build record/package inputs after controlled injection.**

- [ ] **Step 5: Run the RA6 RED set before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -m pytest launcher\tests\test_build_beta_installer.py tests\test_release_controller_split.py -q
```

Expected RED: the installer builder does not yet require/verify `SignedBaselineEvidence`, exact-envelope provenance fields are absent, or stale version inputs are still accepted.

- [ ] **Step 6: Implement exact-envelope verification/copy and provenance fields using `SignedBaselineEvidence.key_id` as the sole build-record key identifier, cross-checked against the re-verified embedded envelope; do not accept unsigned sequence/release_id/key_id flags.**

- [ ] **Step 7: Run GREEN + RT8/RT9 regressions.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -m pytest launcher\tests\test_build_beta_installer.py tests\test_release_controller_split.py launcher\tests\test_baseline_enrollment.py launcher\tests\test_verify_core_install_script.py -q
launcher\.venv\Scripts\ruff.exe check installer\scripts\build_beta_installer.py scripts\release_controller.py launcher\tests\test_build_beta_installer.py tests\test_release_controller_split.py
git diff --check
```

- [ ] **Step 8: Commit and review.**

```cmd
git add installer/scripts/build_beta_installer.py scripts/release_controller.py launcher/tests/test_build_beta_installer.py tests/test_release_controller_split.py
git commit -m "feat: bind installer to signed baseline provenance"
```

**Review:** C0/I0.

---

## Task RA7: Implement Mechanical Proof/Production Build Equivalence

**Prerequisite:** RA6 accepted C0/I0 on a branch that already carries `RUNTIME_TRUST_C0_I0`. RA7 implementation/test helpers may be developed only within this task's normal dependency order; accepted equivalence evidence must consume the same post-RA6 source/toolchain/package contract that RA8 will rebuild and measure, never an earlier K1 feasibility package tree.

**Files:**
- Create: `scripts/verify_build_equivalence.py`
- Create: `launcher/tests/test_verify_build_equivalence.py`

**Interface:**

```python
@dataclass(frozen=True)
class ContentInventoryEntry:
    logical_path: str
    sha256: str
    size: int
    classification: str

@dataclass(frozen=True)
class EquivalenceResult:
    equivalent: bool
    unexpected_differences: tuple[str, ...]
    updater_byte_identical: bool
```

The **only** packaged-content allowlist entry for proof-vs-production trust/routing is the exact relative resource `trust/update-profile-v1.json`. Its verified signed payload may differ only in RT1-defined declarative fields (`profile_id`, channel, owner/repository endpoint, release-key registry); the Profile Authority root, executable/module bytes, PyInstaller contents, and all other resources must match. Broad globs/directories are forbidden, and `NekoUpdater.exe` must remain byte-identical.

- [ ] **Step 1: Write RED test that identical extracted trees pass.**

- [ ] **Step 2: Write RED test that one allowlisted generated profile-resource difference passes and is recorded in evidence.**

- [ ] **Step 3: Write RED tests that a non-allowlisted Python/module/resource content difference, extra file, missing file, changed baseline `NekoUpdater.exe`, or broad/globbed allowlist fails.**

```python
def test_changed_updater_always_fails(tmp_path):
    prod, proof = make_equivalent_trees(tmp_path)
    (proof / "NekoUpdater.exe").write_bytes(b"changed")
    result = compare_builds(prod, proof, allowlist=PROFILE_ALLOWLIST)
    assert not result.equivalent
    assert not result.updater_byte_identical
```

- [ ] **Step 4: Run the complete RA7 RED suite before implementing the verifier.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_verify_build_equivalence.py -q
```

Expected RED: verifier/inventory APIs do not exist yet or unexpected-difference/updater-byte rules are not enforced.

- [ ] **Step 5: Implement deterministic inventory sorted by logical path with SHA-256/size/classification and canonical JSON evidence output, including strict allowlist validation that rejects broad globs and code-module patterns.**

- [ ] **Step 6: Run GREEN/Ruff/diff-check and commit.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_verify_build_equivalence.py -q
.venv\Scripts\ruff.exe check ../scripts/verify_build_equivalence.py tests/test_verify_build_equivalence.py
cd ..
git diff --check
git add scripts/verify_build_equivalence.py launcher/tests/test_verify_build_equivalence.py
git commit -m "feat: verify proof production build equivalence"
```

**Review:** C0/I0.

---

## Task RA8: Build Packaged Proof Harness — Happy Path, Mandatory, Session Defer, Offline Pending

**Precondition:** `RUNTIME_TRUST_C0_I0` (RT10) and RA7 are accepted, and RT1/K1 packaged conformance remains independently accepted as `UPDATER_TRUST_FEASIBLE / C0_I0`. The runtime plan's Git-only **RT1 security-tool immutability guard** has just passed, and only then `scripts/verify_v512_k1_acceptance.py --require-git-immutability` has verified the tracked `docs/superpowers/evidence/v512-k1-acceptance.json`, exact K1A public-custody files, exact K1B-A production/proof profiles, exact K1B-B feasibility fixture/envelopes, and accepted `K1B_CUSTODY_SHA256`. K1 supplies the immutable **trust/profile/authority architecture and feasibility anchor only**. Its Step 10/11 Launcher/Updater/Core identities are early `RT1_CODE_HEAD` feasibility fixtures and **must not** be reused as RA8 final proof/production component identities. RA8 rebuilds and measures fresh production-equivalent and proof-equivalent 5.1.2 baseline package trees from one exact accepted integration source commit, dependency lock, PyInstaller specs, packaging code, and toolchain recipe **for Launcher/Updater**, while both trees stage the exact same verified `NekoProxyCore.zip` bytes from RA3 canonical Core-authority custody/CoreAuthorityBinding rather than rebuilding or resolving Core from that source commit; RA7 must prove the only packaged-content difference is exact `trust/update-profile-v1.json`. RA8 then builds/measures the proof N+1 candidate under the same approved proof harness/toolchain, with the baseline proof `NekoUpdater.exe` byte-identical to the freshly measured production-equivalent baseline Updater. RA8 does not create/sign a trust profile, invent a proof authority, or substitute K1 synthetic component bytes during packaged E2E.

**Files:**
- Create: `launcher/tests/e2e/test_v512_to_v513_proof_e2e.py`
- Modify: `launcher/tests/e2e/test_deferred_pending_update_e2e.py` only for shared packaged proof fixtures used by the new scenario.
- Modify: `launcher/tests/e2e/test_github_release_update_e2e.py` only for shared proof-channel transport fixtures used by the new scenario.
- **Do not modify production modules in RA8.** If a packaged RED test exposes a production defect, STOP RA8, reopen the exact owning RT task, remediate under that task's TDD/review gate, re-run RT acceptance, then resume RA8.

**Feasibility regression rule:** RA8 must re-check RT1/K1 invariants A–G: separate proof/production release keys, common Profile Authority root only in helper code, production profile contains no proof release key/fallback, proof profile contains exactly the K1A Proof Release Authority public keyset and no production fallback, no runtime profile/key switch, exact enrollment profile/keyset pins, and byte-identical baseline Updater. Any contradiction with accepted RT1 evidence yields `ARCHITECTURE_FEASIBILITY_REGRESSION` and returns to Owner architecture review; RA8 may not invent a workaround.

**Proof-signing boundary:** unit/harness RED→GREEN fixtures may use ephemeral test keys strictly inside tests. Accepted packaged proof evidence must not use those fixture keys or a second serializer: after RA8 freshly measures the exact proof-production baseline and proof-candidate artifacts described above, the controller canonicalizes ReleaseSetV2 payloads from **those fresh measured identities**, obtains only `(key_id, detached_signature)` from the K1A Proof Release Authority out-of-process, and constructs/re-verifies each envelope through the immutable RT1 `scripts/assemble_release_v2_envelope.py` from `RT1_CODE_HEAD`. K1 Step 10/11 synthetic artifact identities are never substituted into an RA8 accepted payload. The controller then supplies only signed envelope bytes + public custody/evidence to the harness. `scripts/sign_software_release.py` and worker-held signers are forbidden for accepted proof. Hermes implementers/reviewers never receive the proof private key. Any accepted proof envelope whose verified `key_id` is not the K1A Proof Release Authority key id, whose signed component object differs from the freshly measured RA8 artifact identities, whose payload/envelope cannot be reproduced through the shared assembler, or whose assembler source differs from accepted `RT1_CODE_HEAD` is `PROOF_AUTHORITY_MISMATCH` and cannot become RA8/RA9 evidence.

- [ ] **Step 1: Write the packaged baseline RED scenario:** record `RA8_PACKAGE_SOURCE_SHA` from the accepted integration branch after RT10/RA7, then build fresh production-equivalent and proof-equivalent 5.1.2 Launcher/Updater bytes from that same exact source commit/toolchain with the exact K1B-A production/proof profiles and stage the same exact RA3-verified Core custody bytes/Core installed identity into both package trees; no Core rebuild or network re-resolution is allowed. Run RA7 mechanical inventory equivalence and require all non-allowlisted bytes to match with baseline `NekoUpdater.exe` byte-identical. Install the proof-equivalent 5.1.2 whose Installer contains the exact controller-custodied signed proof trust profile at fixed `trust\update-profile-v1.json` plus a proof-signed equivalent baseline `release-v2.json` whose signed Launcher/Updater/Core objects equal the freshly measured proof-baseline artifacts. Test fixtures may use an ephemeral signer, but the accepted controller run replaces those bytes with an envelope produced by the detached Proof Release Authority + shared RT1 assembler path and requires verified `key_id`/public-key identity + assembler-source match. Offline enrollment must first verify the profile under the common Profile Authority root, pin exact profile-envelope/keyset hashes, then authenticate the baseline only with that profile's proof release key. Assert the exact proof-baseline `NekoUpdater.exe` SHA equals the freshly measured production-equivalent baseline helper SHA; no K1 synthetic component artifact may satisfy this assertion.

- [ ] **Step 2: RED self-resolution test: proof baseline querying proof channel authenticates exact same binding and returns `LATEST / NO UPDATE`.**

- [ ] **Step 3: RED newer candidate test: proof seq N+1 with `mandatory=true` is detected as mandatory; separate case `mandatory=false` but `minimum_supported_sequence=N+1` is also mandatory because committed=N.**

- [ ] **Step 4: RED authenticated-but-incomplete mandatory scenario (Spec Case 2):** committed=N, Launcher discovery authenticates mandatory N+1, then the RT6 one-shot helper `ADMIT_AUTHORITY` path re-verifies the exact envelope and durably records `highwater=observed=N+1` while updater state remains IDLE **before** `SoftwareUpdateStageService.stage()` downloads any artifact. Require the admission-only helper process to exit 0 without activation/probation. Force network loss during Launcher/Core stage download before `PendingUpdateStore.promote`; restart Launcher and prove no helper PREPARING transaction ever existed, `failed != N+1`, committed N remains runnable, and exact admitted authority survives. Make discovery unavailable and prove non-bricking runtime; restore network and prove exact N+1 is policy-retryable, helper admission is idempotent, staging retries, and only successful signature/size/SHA/installed-identity checks create durable pending. Assert the legacy direct-online `SoftwareUpdateApplyService.prepare()` path is fail-closed and unused; packaged apply proceeds only through the verified pending + `prepare_pending(...)` path.

- [ ] **Step 5: RED active-game test: after the successful retry creates pending, apply is deferred; fixture asserts game process/session is not terminated.**

- [ ] **Step 6: RED safe-state apply test consumes the verified durable pending through `prepare_pending(...)` using the exact freshly measured RA8 proof-baseline `NekoUpdater.exe`; assert its byte SHA equals the same-run production-equivalent baseline helper evidence before apply and assert no direct-online `prepare()` resolver/download path executes.**

- [ ] **Step 7: RED restart/relaunch/probation/commit test proves committed binding advances to N+1.**

- [ ] **Step 8: RED offline-pending test: after verified pending is durable, disable proof discovery/network fixture and prove apply still succeeds when safe.**

- [ ] **Step 9: Run the focused RA8 scenario set RED before treating the harness as evidence.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_v512_to_v513_proof_e2e.py -q
```

Expected RED: at least one newly added packaged scenario fails for the intended missing runtime/fixture behavior; an infrastructure/import failure is not acceptable evidence. If a production defect is exposed, STOP RA8, reopen the owning RT task, repair under that task's TDD/review gate, rerun RT10, then resume RA8.

- [ ] **Step 10: After all owning production tasks are remediated and re-reviewed, run the packaged RA8 scenarios GREEN plus affected deferred/GitHub E2E regressions.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_v512_to_v513_proof_e2e.py tests/e2e/test_deferred_pending_update_e2e.py tests/e2e/test_github_release_update_e2e.py -q
cd ..
git diff --check
```

- [ ] **Step 11: Commit only harness/fixture changes after production defects are separately accepted.**

```cmd
git add launcher/tests/e2e/test_v512_to_v513_proof_e2e.py launcher/tests/e2e/test_deferred_pending_update_e2e.py launcher/tests/e2e/test_github_release_update_e2e.py
git commit -m "test: prove packaged v5.1.2 mandatory update path"
```

**Review:** C0/I0; reviewer must verify this is packaged evidence, not merely coordinator mocks.

---

## Task RA9: Extend Packaged Proof Harness — Same-Sequence, Rollback, Crash Recovery, Replay

**Prerequisite:** RA8 accepted C0/I0 with recorded `RA8_PACKAGE_SOURCE_SHA`, fresh proof/production baseline equivalence, and proof releases signed from the fresh RA8 component identities. RA9 extends that accepted packaged harness; it never falls back to K1 Step 10/11 synthetic component bytes.

**Files:**
- Modify: `launcher/tests/e2e/test_v512_to_v513_proof_e2e.py`
- Create: `scripts/verify_v512_proof_evidence.py`
- Create: `launcher/tests/test_verify_v512_proof_evidence.py`
- Generated/untracked proof bytes: `artifacts/evidence/v512-v513-proof-evidence.json`
- Durable proof custody: `E:\Github\artifacts\v512-release-proof-evidence\v512-v513-proof-evidence.json`
- Controller-created tracked acceptance record after C0/I0 review: `docs/superpowers/evidence/v512-ra9-proof-acceptance.json`
- Reuse updater recovery/state tests as helpers only; packaged scenario remains the acceptance evidence.

- [ ] **Step 1: Add RED same-sequence exact-binding no-op scenario.**
- [ ] **Step 2: Add RED same-sequence changed payload/release_id scenario and require fail-closed identity conflict.**
- [ ] **Step 3: Add RED lower-than-high-water replay scenario and require rejection.**
- [ ] **Step 4: Add RED broken candidate/probation failure scenario; require runtime rollback to N while high-water/failed remain exact N+1 binding.**
- [ ] **Step 5: Add RED rediscovery matrix: exact failed N+1 is known/no-new-update and not reapplied; changed N+1 conflicts; N+2 may become fresh candidate.**
- [ ] **Step 6: Add RED restart/crash boundaries around PREPARING, QUIESCING, PROBATION, CLEANING, and ROLLING_BACK; after restart require only `OLD_FULLY_RESTORED`, `NEW_FULLY_COMMITTED`, or explicit `REPAIR_REQUIRED` per scenario.**
- [ ] **Step 7: Add RED discovery-outage scenario while no mandatory pending: committed app remains runnable and update check is unavailable, not application-blocking.**
- [ ] **Step 8: Run the new RA9 packaged scenarios RED before accepting any evidence.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_v512_to_v513_proof_e2e.py -q
```

Expected RED: at least one newly added rollback/replay/crash scenario fails for the intended missing behavior; unrelated infrastructure failure does not count.

- [ ] **Step 9: After owning-task remediation where required, run packaged E2E + full updater regression GREEN.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_v512_to_v513_proof_e2e.py tests/e2e/test_deferred_pending_update_e2e.py tests/e2e/test_github_release_update_e2e.py -q
.venv\Scripts\python.exe -B -m pytest tests/updater -q
```

- [ ] **Step 10: Define and test the complete proof-evidence schema v1 before emitting durable evidence.** `scripts/verify_v512_proof_evidence.py` validates canonical UTF-8 JSON and exact keys/types. Its controller/acceptance CLI is closed to exactly `--repo-root`, `--acceptance-record`, `--evidence`, `--k1-acceptance-record`, and `--k1b-custody`; there is no caller-supplied trust registry/profile/public-key override. The RA9 verifier is invoked only after the RT1 security-tool guard + fresh K1 verifier PASS, then independently reads the immutable K1 acceptance record and exact K1B custody manifest to bind the RA9 evidence back to accepted K1 authority/profile identities:

```text
BindingEvidenceV1 = {
  release_sequence: int >= 1,
  release_id: non-empty str,
  payload_sha256: lowercase hex64
}
AuthorityStateEvidenceV1 = {
  committed: BindingEvidenceV1,
  high_water: BindingEvidenceV1,
  observed: BindingEvidenceV1,
  failed: BindingEvidenceV1 | null,
  pending_release_sequence: int >= 1 | null
}
ComponentEvidenceV1 = {
  version: non-empty str,
  artifact_id: non-empty str,
  artifact_sha256: lowercase hex64,
  artifact_size: int > 0,
  installed_identity_sha256: lowercase hex64,
  artifact_format: non-empty str
}
ComponentSetEvidenceV1 = {launcher: ComponentEvidenceV1, updater: ComponentEvidenceV1, core: ComponentEvidenceV1}
TrustProfileEvidenceV1 = {
  profile_id: non-empty str,
  profile_authority_key_id: non-empty str,
  profile_authority_public_key_sha256: lowercase hex64,
  profile_envelope_sha256: lowercase hex64,
  keyset_sha256: lowercase hex64
}
ReleaseAuthorityEvidenceV1 = {
  key_id: non-empty str,
  public_key_hex: exactly 64 lowercase hex characters for one 32-byte Ed25519 public key,
  public_key_sha256: lowercase hex64
}
trust_profiles = {
  production_baseline: TrustProfileEvidenceV1,
  proof_baseline: TrustProfileEvidenceV1
}
release_authorities = {
  production: ReleaseAuthorityEvidenceV1,
  proof: ReleaseAuthorityEvidenceV1
}
component_identities = {
  production_baseline: ComponentSetEvidenceV1,
  proof_baseline: ComponentSetEvidenceV1,
  proof_candidate: ComponentSetEvidenceV1
}
ProofReleaseEvidenceV1 = {
  role: "baseline" | "candidate" | "scenario_auxiliary",
  release_sequence: int >= 1,
  release_id: non-empty str,
  payload_sha256: lowercase hex64,
  envelope_sha256: lowercase hex64,
  key_id: non-empty str,
  envelope_b64: canonical RFC4648 base64 of the exact canonical release-v2.json file bytes
}
proof_releases = non-empty list[ProofReleaseEvidenceV1] sorted by (release_sequence, envelope_sha256) with unique envelope_sha256 and exactly one role="baseline" plus exactly one role="candidate"
ScenarioEvidenceV1 = {
  scenario_id: non-empty unique str,
  result: "PASS",
  diagnostic_code: str | null,
  before: AuthorityStateEvidenceV1,
  after: AuthorityStateEvidenceV1,
  release_envelope_sha256s: list[lowercase hex64] sorted unique (may be empty only when the scenario authenticates/consumes no new remote envelope),
  evidence_sha256: lowercase hex64
}
scenarios = non-empty list[ScenarioEvidenceV1] sorted by scenario_id
final_bindings = AuthorityStateEvidenceV1
```

Top-level keys are exactly `schema_version=1`, `source_sha`, `k1b_custody_sha256`, `trust_profiles`, `release_authorities`, `baseline_updater_sha256`, `updater_byte_identical`, `component_identities`, `proof_releases`, `scenarios`, `final_bindings`. `k1b_custody_sha256` must equal the exact value pinned by immutable `v512-k1-acceptance.json`; the verifier must reject evidence produced from a different or freshly reconstructed K1 custody manifest. Require the supplied `--k1-acceptance-record` to carry the same `k1b_custody_path` and `k1b_custody_sha256` as the supplied exact `--k1b-custody` bytes and top-level RA9 `k1b_custody_sha256`; any path/digest mismatch fails. Require distinct production/proof `profile_id` and `keyset_sha256`; the same approved Profile Authority key id/public-key SHA; exact K1B custody `profile_envelope_sha256` values; production release authority equal authenticated `neko-update-prod-1` public evidence; and proof release authority equal exact K1A Proof Release Authority identity in K1B custody. For each `ReleaseAuthorityEvidenceV1`, decode `public_key_hex`, require exactly 32 bytes, recompute `public_key_sha256`, require exact K1B authority key-id/public-key-SHA binding, and recompute the corresponding one-key canonical registry digest as `sha256(canonical_json_dumps({"release_keys":[{"key_id":key_id,"public_key_hex":public_key_hex}]})).hexdigest()`; that digest must equal both the RA9 trust-profile `keyset_sha256` and the corresponding accepted K1B profile `keyset_sha256`. Require `updater_byte_identical=true`; require `component_identities.production_baseline == component_identities.proof_baseline` exactly because the only allowed 5.1.2 proof/production package difference is the external signed trust-profile resource, and require `baseline_updater_sha256 == component_identities.production_baseline.updater.artifact_sha256 == component_identities.proof_baseline.updater.artifact_sha256`. For every component set, require exact ReleaseSetV2 component semantics: launcher id/format `NekoLauncher.exe`/`raw-pe-v1`, updater `NekoUpdater.exe`/`raw-pe-v1`, core `NekoProxyCore.zip`/`zip-core-v1`; launcher/updater artifact SHA must equal installed identity SHA; sizes are positive. Every `proof_releases[*].envelope_b64` must strict-base64 decode and re-encode byte-identically, hash to its recorded `envelope_sha256`, equal the existing canonical release-envelope file contract (sorted compact UTF-8 JSON plus exactly one LF), parse successfully, and cryptographically verify with `verify_release_envelope_v2(...)` using only `{release_authorities.proof.key_id: bytes.fromhex(release_authorities.proof.public_key_hex)}` after the K1 binding checks above. The verifier recomputes `payload_sha256`, `release_sequence`, `release_id`, and requires `key_id` to equal the exact K1A Proof Release Authority key id; no ephemeral/production key is accepted. The unique `role="baseline"` release must have signed `components` exactly equal to `component_identities.proof_baseline`; the unique `role="candidate"` release must have signed `components` exactly equal to `component_identities.proof_candidate`; auxiliary releases are still fully signature/component-parse verified but need not equal the canonical candidate. Every non-null `committed/high_water/observed/failed` `BindingEvidenceV1` appearing in any scenario or `final_bindings` must exactly match `(release_sequence, release_id, payload_sha256)` of at least one verified `proof_releases` entry; every non-null `pending_release_sequence` must exist among verified proof-release sequences. Each scenario's `release_envelope_sha256s` must reference only entries in `proof_releases`; the union of all scenario references must equal the exact `proof_releases` envelope-SHA set so no accepted envelope is unaudited or orphaned. Define each `ScenarioEvidenceV1.evidence_sha256` exactly as `sha256(canonical_json_dumps({"scenario_id":scenario_id,"result":result,"diagnostic_code":diagnostic_code,"before":before,"after":after,"release_envelope_sha256s":release_envelope_sha256s})).hexdigest()`; `canonical_json_dumps(...)` already returns the exact UTF-8 bytes and no LF is added; the verifier recomputes this digest and never accepts an arbitrary hex value. `source_sha` must equal the exact RA9 code HEAD recorded later as `ra9_code_head_sha` in the acceptance record. Unknown/missing nested keys, malformed/non-canonical envelope bytes/base64, envelope hash/signature/payload/key mismatch, unknown scenario envelope refs, orphaned proof releases, evidence-hash mismatch, authority/keyset mismatch, unsorted/duplicate release/scenario IDs, invalid binding ordering, or a non-PASS scenario fail validation.

- [ ] **Step 11: Run verifier-schema RED→GREEN and packaged proof GREEN, but do not create the durable custody artifact yet.** This step proves the producer/verifier code before the source commit. RED cases must include missing/extra `proof_releases`, zero/multiple baseline or candidate roles, baseline/candidate signed-component mismatch, production/proof baseline component divergence, bad component id/format/version/size/installed identity, `baseline_updater_sha256` mismatch, a state binding with no matching signed proof release, a pending sequence absent from proof releases, missing/invalid `public_key_hex`, wrong key length/case/hex, public-key-SHA mismatch, K1 authority/key-id mismatch, recomputed keyset-SHA mismatch, missing/wrong `--k1-acceptance-record` or `--k1b-custody`, K1 acceptance/custody path-or-digest mismatch, invalid/non-canonical base64, decoded envelope bytes with missing/extra LF or non-canonical JSON, envelope-SHA mismatch, payload-SHA mismatch, bad proof signature/key, production-key or ephemeral-key substitution, wrong release sequence/id, unknown/duplicate/orphaned scenario envelope references, scenario refs not sorted unique, arbitrary/stale `evidence_sha256`, scenario-body mutation without digest update, and a proof release present in custody but referenced by no accepted scenario.

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_verify_v512_proof_evidence.py tests/e2e/test_v512_to_v513_proof_e2e.py -q
.venv\Scripts\ruff.exe check ../scripts/verify_v512_proof_evidence.py tests/test_verify_v512_proof_evidence.py tests/e2e/test_v512_to_v513_proof_e2e.py
cd ..
git diff --check
```

- [ ] **Step 12: Commit exactly the RA9 harness/verifier source code first.**

```cmd
git add launcher/tests/e2e/test_v512_to_v513_proof_e2e.py scripts/verify_v512_proof_evidence.py launcher/tests/test_verify_v512_proof_evidence.py
git commit -m "test: prove rollback replay and crash recovery"
```

Require a clean tracked worktree after the commit and record `RA9_CODE_HEAD = git rev-parse HEAD`.

- [ ] **Step 13: Generate the accepted proof bytes from that exact committed RA9 code HEAD using only accepted K1 authority inputs.** First run the Git-only **RT1 security-tool immutability guard**, then re-run `verify_v512_k1_acceptance.py --require-git-immutability` and obtain the exact accepted `K1B_CUSTODY_SHA256`; STOP on any mismatch. From clean `RA9_CODE_HEAD`, rebuild both production-equivalent and proof-equivalent 5.1.2 Launcher/Updater bytes with the accepted K1B-A profiles, stage the same exact RA3-verified Core custody bytes in both trees, rerun RA7 mechanical equivalence, and freshly measure full Launcher/Updater/Core component objects; these become `component_identities.production_baseline` and `.proof_baseline` and must be exactly equal. Neither tree may rebuild, fetch, or re-resolve Core. Build/measure the canonical proof N+1 candidate from the same accepted proof harness/toolchain as `.proof_candidate`. Re-run the packaged proof using those fresh bytes; every accepted proof release envelope must be regenerated/verified through the detached K1A Proof Release Authority + immutable `RT1_CODE_HEAD` shared assembler path, never an ephemeral fixture signer, and all profile/authority identities must match the K1 acceptance record. The producer records exact production/proof `public_key_hex` only from the already accepted authority inputs whose key id/public-key SHA are pinned by K1, recomputes both authority public-key SHA and one-key keyset SHA, marks exactly one signed release `role="baseline"` whose components equal `.proof_baseline` and exactly one `role="candidate"` whose components equal `.proof_candidate`, marks all other signed scenario variants `scenario_auxiliary`, embeds every distinct exact accepted `release-v2.json` file byte sequence into `proof_releases[*].envelope_b64`, records/recomputes its envelope/payload/key/sequence/id binding, attaches exact envelope SHA references to every scenario that authenticates/consumes that envelope, requires every recorded authority-state binding to resolve to a verified proof release, requires the union of scenario refs to cover exactly the stored proof-release set, and recomputes each scenario `evidence_sha256` from the canonical scenario body defined above before schema validation. Set top-level `source_sha=RA9_CODE_HEAD` and `k1b_custody_sha256=<accepted K1B_CUSTODY_SHA256>`, validate the full schema, serialize canonical UTF-8 with sorted keys and separators `(',', ':')`, write the worktree artifact, atomically copy exact bytes to `E:\Github\artifacts\v512-release-proof-evidence\v512-v513-proof-evidence.json`, fsync/close/re-read custody, and require byte-for-byte equality + same SHA-256. Record that digest as candidate `proof_evidence_sha256`.

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_k1_acceptance.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --evidence docs\superpowers\evidence\v512-updater-trust-feasibility.md --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json --require-git-immutability
cd launcher
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_v512_to_v513_proof_e2e.py tests/test_verify_v512_proof_evidence.py -q
cd ..
git rev-parse HEAD
git status --short
```

The only allowed untracked/generated delta from this step is the declared worktree proof artifact/evidence output; tracked source must remain clean and `HEAD == RA9_CODE_HEAD`.

- [ ] **Step 14: Independent `ag/gemini-pro-agent` review the exact `RA9_CODE_HEAD` plus the exact custody `proof_evidence_sha256`. Required C0/I0.** Any C/I remediation changes code, so discard the candidate custody acceptance, reopen RA9, create a new code commit, regenerate evidence with the new HEAD, and review again.

- [ ] **Step 15 — Controller seals the expected proof digest only after reviewer C0/I0:** before sealing, re-run the Git-only RT1 security-tool guard and fresh `verify_v512_k1_acceptance.py --require-git-immutability` against the exact K1B custody used by the reviewed RA9 evidence; any K1 drift invalidates the candidate and returns to Step 13/review. Then create canonical tracked `docs/superpowers/evidence/v512-ra9-proof-acceptance.json` with exact fields `schema_version=1`, `task_id="RA9"`, `ra9_code_head_sha=RA9_CODE_HEAD`, `proof_custody_path`, `proof_evidence_sha256`, `reviewer_model="ag/gemini-pro-agent"`, `critical_count=0`, `important_count=0`, `reviewed_at`. Re-hash custody independently before writing. Commit this one evidence file in a controller-only evidence commit and record that commit as `RA9_ACCEPTANCE_COMMIT`. The record is immutable after this commit; downstream tasks must never edit it.

```cmd
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_k1_acceptance.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --evidence docs\superpowers\evidence\v512-updater-trust-feasibility.md --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json --require-git-immutability
git add docs/superpowers/evidence/v512-ra9-proof-acceptance.json
git commit -m "docs(evidence): seal RA9 proof digest"
git rev-parse HEAD
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-ra9-proof-acceptance.json'; paths=[r'scripts/verify_v512_proof_evidence.py',r'launcher/tests/e2e/test_v512_to_v513_proof_e2e.py',r'launcher/tests/test_verify_v512_proof_evidence.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('RA9 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['ra9_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RA9 evidence paths changed after accepted RA9_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RA9_EVIDENCE_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_proof_evidence.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-ra9-proof-acceptance.json --evidence E:\Github\artifacts\v512-release-proof-evidence\v512-v513-proof-evidence.json --k1-acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json
```

`verify_v512_proof_evidence.py` must load the tracked RA9 acceptance record from Git, validate it has exactly one introduction commit and no later modification, require proof top-level `source_sha == acceptance.ra9_code_head_sha`, take `proof_evidence_sha256` from that immutable record as the **expected** digest, compare the custody bytes to it, and independently bind the evidence's K1 digest/authority/keyset/profile identities to the explicit `--k1-acceptance-record` + rehashed `--k1b-custody` inputs before any proof-envelope signature is accepted. It must never compute a current evidence/K1 digest and treat that freshly computed value as authority.

**RA9 proof-evidence immutability guard:** after `RA9_ACCEPTANCE_COMMIT`, the closed RA9 evidence path set `scripts/verify_v512_proof_evidence.py`, `launcher/tests/e2e/test_v512_to_v513_proof_e2e.py`, and `launcher/tests/test_verify_v512_proof_evidence.py` is immutable relative to accepted `RA9_CODE_HEAD`. The guard does not assume `RA9_CODE_HEAD` / `RA9_ACCEPTANCE_COMMIT` are Git refs: it resolves the single acceptance-record introduction commit from Git history, reads `ra9_code_head_sha` from that commit's JSON blob, requires the current acceptance record to equal its committed bytes, requires the accepted RA9 commit to be an ancestor of `HEAD`, requires zero later commits to have touched the closed RA9 paths, and requires current index/worktree bytes for those paths to equal `RA9_CODE_HEAD`. Before any downstream current-path proof-verifier/harness use, run this exact repo-root command:

```cmd
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-ra9-proof-acceptance.json'; paths=[r'scripts/verify_v512_proof_evidence.py',r'launcher/tests/e2e/test_v512_to_v513_proof_e2e.py',r'launcher/tests/test_verify_v512_proof_evidence.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('RA9 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['ra9_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RA9 evidence paths changed after accepted RA9_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RA9_EVIDENCE_TOOL_GUARD_OK',c,h)"
```

Any failure is `RA9_EVIDENCE_TOOL_DRIFT` and reopens RA9/regenerates proof evidence + review; passing current tests cannot waive it.

**Review:** C0/I0 in Step 14 before the Step 15 acceptance-record seal; Sol-high escalation only for a concrete unresolved recovery/concurrency contract conflict.

---

## Task RA10: Release Authority & Proof Workstream Acceptance

- [ ] **Step 1: Run the exact RA unit/tooling test matrix.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -m pytest launcher\tests\test_update_trust_profile.py launcher\tests\test_build_update_trust_profile.py launcher\tests\test_assemble_release_v2_envelope.py launcher\tests\test_verify_v512_k1_acceptance.py launcher\tests\test_updater_trust_feasibility.py launcher\tests\test_update_channel_profile.py tests\test_derive_version.py tests\test_release_intent.py tests\test_kanban_adapter.py tests\test_e2e_release_pipeline.py tests\test_release_controller_split.py launcher\tests\test_production_sequence_ledger.py launcher\tests\test_authenticated_production_history.py launcher\tests\test_core_authority_custody.py launcher\tests\test_sign_software_release.py launcher\tests\test_build_software_release_v2.py launcher\tests\test_publish_atomic_release.py launcher\tests\test_verify_github_release_assets.py launcher\tests\test_verify_build_equivalence.py launcher\tests\test_build_beta_installer.py launcher\tests\test_verify_v512_proof_evidence.py -q
```

- [ ] **Step 2: Run the exact packaged E2E + updater regression.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/e2e/test_v512_to_v513_proof_e2e.py tests/e2e/test_deferred_pending_update_e2e.py tests/e2e/test_github_release_update_e2e.py -q
.venv\Scripts\python.exe -B -m pytest tests/updater -q
```

- [ ] **Step 3: Run exact RA Ruff + diff checks.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\ruff.exe check scripts\build_update_trust_profile.py scripts\assemble_release_v2_envelope.py scripts\verify_v512_k1_acceptance.py scripts\production_sequence_ledger.py scripts\authenticated_production_history.py scripts\core_authority_custody.py scripts\derive_version.py scripts\release_controller.py scripts\kanban_release_adapter.py scripts\build_software_release_v2.py scripts\sign_software_release.py scripts\publish_atomic_release.py scripts\verify_github_release_assets.py scripts\verify_build_equivalence.py scripts\verify_v512_proof_evidence.py installer\scripts\build_beta_installer.py tests launcher\tests
git diff --check
```

- [ ] **Step 4: Verify K1 acceptance first, then RA9 evidence against immutable accepted digests—not against itself.** Run the Git-only **RT1 security-tool immutability guard** before `scripts/verify_v512_k1_acceptance.py --require-git-immutability`; then run the **RA9 proof-evidence immutability guard** before invoking `scripts/verify_v512_proof_evidence.py`. Only after both source guards pass may the current-path verifiers consume the accepted records. Run `scripts/verify_v512_k1_acceptance.py` with `--require-git-immutability` against tracked `v512-k1-acceptance.json`, exact K1 evidence, and exact K1B-B custody manifest pinned by `K1B_CUSTODY_SHA256`. Then `scripts/verify_v512_proof_evidence.py` must read immutable `v512-ra9-proof-acceptance.json`, explicit immutable `v512-k1-acceptance.json`, and exact supplied K1B custody; extract expected `proof_evidence_sha256`, validate full nested schema/canonical bytes at `E:\Github\artifacts\v512-release-proof-evidence\v512-v513-proof-evidence.json`, and compare actual SHA-256 to that expected value. Require proof top-level `k1b_custody_sha256` exactly equals the K1 acceptance + rehashed K1B custody value; RA9 `release_authorities` public-key bytes/key IDs/SHAs and recomputed one-key keyset SHAs, plus `trust_profiles` identities/profile/keyset SHAs, must match the K1 manifest/record, with production authority still matching authenticated `neko-update-prod-1`. If a worktree copy exists, require byte-for-byte equality with custody.

```cmd
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_k1_acceptance.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --evidence docs\superpowers\evidence\v512-updater-trust-feasibility.md --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json --require-git-immutability
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-ra9-proof-acceptance.json'; paths=[r'scripts/verify_v512_proof_evidence.py',r'launcher/tests/e2e/test_v512_to_v513_proof_e2e.py',r'launcher/tests/test_verify_v512_proof_evidence.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('RA9 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['ra9_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RA9 evidence paths changed after accepted RA9_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RA9_EVIDENCE_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_proof_evidence.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-ra9-proof-acceptance.json --evidence E:\Github\artifacts\v512-release-proof-evidence\v512-v513-proof-evidence.json --k1-acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json
```

Any missing/malformed/nested-schema/digest/history-modification/K1-authority-binding/proof-envelope-signature mismatch blocks RA10 acceptance.
- [ ] **Step 5: Independent `ag/gemini-pro-agent` review against Spec Revision 3.4 + runtime workstream contract + this plan. Required C0/I0.**
- [ ] **Step 6: Reopen owning tasks on any C/I issue and repeat acceptance.**
- [ ] **Step 7: Mark `RELEASE_AUTHORITY_PROOF_C0_I0` only after all pass.**

No actual production sequence reservation, production signing, repo creation, machine publication, or Human publication is performed by this acceptance task.

---

# Controller Release Stop Gates After Implementation Approval

These gates describe later controller execution and are **not authorized by plan approval alone**.

- **CR0 — Bootstrap/read-back canonical production authority custody + ledger genesis:** before any component freeze/reservation, controller re-reads the exact historical seq7 source path recorded in RA2, verifies canonical bytes + production signature + expected seq7/release_id/key/payload/envelope hashes, verifies provenance commit exists, and persists the exact envelope through canonical custody at `E:\\Github\\artifacts\\v512-production-authority-custody`. Create/update canonical `history-index-v1.json` only through the tested atomic/idempotent custody API, then read back through `load_custody_records()` and require exact seq7 binding. Construct the production history provider, acquire the external Production Sequence Authority Ledger lock, fresh-load history, require highest authenticated authority is still exactly seq7, then create/read-back exactly one immutable ledger genesis anchored to that seq7 binding/provenance. If the ledger already exists, require exact genesis match and never regenerate it. Any missing/mutated/newer pre-ledger evidence is `PRODUCTION_HISTORY_EVIDENCE_MISSING/CHANGED` and blocks release; never substitute remembered integer 7 or fabricate historical lifecycle events.
- **CR1 — Freeze exact production component + trust set first:** before build/freeze, run the Git-only **RT1 security-tool immutability guard**, then on PASS run `verify_v512_k1_acceptance.py --require-git-immutability` against canonical `v512-k1-acceptance.json` and exact K1B-A/K1B-B custody chain; any mismatch stops before sequence allocation. Build Launcher/Updater from Owner-approved final source SHA using `source_base` only for Launcher/Updater source-build compatibility; load Core once from explicit controller-owned canonical Core-authority custody; and re-load/re-verify the exact **K1B-A production profile referenced by accepted K1 custody** at `trust/update-profile-v1.json` under the RT1-accepted Profile Authority root. Require the frozen `CoreAuthorityBinding` to carry the verified authority version/sequence/release_id/payload/envelope/key, authenticated Core-manifest source commit, and provenance digest; for initial v5.1.2 custody this is historical signed seq6/stable-0006 authority defined in RA3. Require frozen `TrustProfileBinding` to carry exact production profile id/channel/owner/repository, Profile Authority key id/public-root SHA, profile-envelope SHA, and production keyset SHA matching authenticated `neko-update-prod-1` evidence **and accepted K1 record/manifest**. Record exact component bytes/hashes/sizes/installed identities, Launcher/Updater source/toolchain, both bindings, and one canonical `component_set_sha256` over the complete typed set. Never select/fetch Core through `source_base` or Human Release and never replace/re-sign/select another production trust profile after this point. Do not allocate a production sequence yet.
- **CR2 — Fresh sequence reconciliation/reservation second:** construct the production `AuthenticatedHistoryProvider`, then acquire the Production Sequence Authority Ledger serialization session. **Inside that lock**, invoke `history_provider.load()` afresh, read/verify exact CR0 genesis + ledger, reconcile, derive next-unused, append/fsync/read-back `RESERVED` bound to CR1 `component_set_sha256`, then release. No prebuilt history snapshot is accepted. Missing/rebound genesis floor or newer/conflicting authenticated authority hard-stops; no silent retry. Provisional seq8 is used only if still next-unused. A reservation stays permanently consumed if later abandoned.
- **CR3 — Fresh guard + detached controller production signing + shared assembly + custody + `SIGNED`:** generate canonical payload from exact CR1 `FinalComponentSet` + CR2 allocation without signing. Before signer invocation, re-hash/re-validate staged component identities and exact frozen `TrustProfileBinding`; any profile-envelope/keyset/Profile Authority/routing drift means the reserved component-set binding changed and the sequence is consumed/failed. Acquire the same ledger serialization session; inside it fresh-load authenticated history and reconcile again against exact `RESERVED`. If reconciliation finds exact `SIGNED_APPEND_REQUIRED` from an earlier crash, verify the custodied envelope and append only the missing `SIGNED` record with zero signer invocation. Otherwise newer/conflicting authority stops before signer invocation. For a new signature, while still locked re-run the Git-only **RT1 security-tool immutability guard** before any assembler invocation; on PASS invoke the controller production signer only for `DetachedReleaseSignature(key_id, signature)`; require `key_id` belongs to the exact accepted production registry (currently only `neko-update-prod-1`) and that no proof key/fallback is present, then call immutable `RT1_CODE_HEAD` `assemble_verified_release_v2_envelope(...)` with the exact canonical payload + detached signature + exact production public registry. Trust only the re-verified assembled envelope/binding/key_id, persist/read-back those exact bytes into canonical production authority custody atomically, fresh-load history again and require exact `SIGNED_APPEND_REQUIRED`, then append/fsync/read-back `SIGNED`. The signer never serializes an envelope and workers never see private key material. If payload/component/trust set changed, consume/fail the reservation and restart CR1/CR2 with a new sequence.
- **CR4 — Final Installer:** build exact Installer embedding both the exact production-signed baseline envelope and the exact CR1-frozen **K1B-A production profile bytes referenced by immutable K1 acceptance** at their fixed paths. Before ISCC, require embedded profile SHA/profile id/keyset/Profile Authority binding to equal `FinalComponentSet.trust_profile`; a different even-validly-signed profile is not equivalent. Prove metadata 5.1.2, exact enrollment profile pins, Core verifier exit 0, clean install/offline enrollment/uninstall-reinstall/manual v5.1.0→v5.1.2 migration. Retry transient infrastructure failures only with byte-identical signed envelope + byte-identical frozen profile/component inputs; if the candidate requires any payload/component/Core-authority/trust-profile change, append/readback same-sequence `FAILED` and restart CR1/CR2 with a new sequence.
- **CR5 — Mechanical equivalence + isolated proof:** run the Git-only **RT1 security-tool immutability guard** and **RA9 proof-evidence immutability guard** first; only on PASS fresh-reverify immutable K1 acceptance and RA9 proof acceptance/custody with the explicit K1 acceptance + K1B custody inputs required by `verify_v512_proof_evidence.py`. These immutable K1/RA9 records are qualification/authority anchors only, not final component-byte sources. Use the exact CR1/CR3/CR4 frozen-and-signed production Launcher/Updater/Core bytes as the production reference; do **not** rebuild a substitute production reference after signing. Build the proof-equivalent 5.1.2 Launcher/Updater from the exact Owner-approved final source SHA with the same dependency lock/PyInstaller specs/packaging code/toolchain recipe used by the frozen production candidate, stage the exact same CR1 `NekoProxyCore.zip` bytes/CoreAuthorityBinding (never rebuild/re-resolve Core), and use the exact accepted K1B-A proof profile. Require freshly measured proof Launcher/Updater/Core identities to equal the signed production component identities exactly; allow only `trust/update-profile-v1.json` as the declarative package-tree difference. Verify both profiles under the same Profile Authority root, require production keyset == authenticated production public registry and proof keyset == exact K1A Proof Release Authority public custody, and require byte-identical baseline Updater plus identical non-allowlisted contents. Build/measure the isolated 5.1.3-proof candidate against that proof baseline and produce every accepted proof baseline/candidate/auxiliary envelope only from those fresh proof identities using detached K1A Proof Release Authority + immutable `RT1_CODE_HEAD` shared assembler; K1 synthetic fixture identities and worker/ephemeral keys cannot satisfy this gate. Record fresh release-phase proof evidence including final source SHA, exact signed-production reference component objects, fresh proof component objects, signed proof-envelope bytes/bindings, exact production/proof Updater equality, CoreAuthorityBinding equality, and scenario authority-state bindings, then run the complete packaged proof matrix. Any source/toolchain difference, production-reference rebuild/substitution, Core authority/byte drift, unexpected content drift, trust crossover, RA9/K1 evidence drift, or proof failure blocks release. If proof rejects the signed production baseline/frozen production profile such that corrected production bytes/authority/trust-profile are required, append/readback same-sequence `FAILED`; never reuse that signed sequence for corrected content.
- **CR6 — Independent exact-candidate review:** `ag/gemini-pro-agent` C0/I0.
- **CR7 — Production Updates repository:** if missing, STOP for separately authorized controller creation. No worker creates it.
- **CR8 — Fresh guard + machine baseline publication + `PUBLISHED`:** acquire the same ledger serialization session before any public promotion; inside it fresh-load authenticated history and reconcile exact `SIGNED`. Newer/conflicting external authority => hard STOP with zero publication. If the exact candidate is already verified in the live Updates source and reconciliation returns `PUBLISHED_APPEND_REQUIRED`, perform read-only hosted asset/tag/target/self-resolution verification and append only the missing `PUBLISHED` record—do not upload/promote again. Otherwise keep the session held across one exact four-asset promotion and live re-download/readback; production candidate must authenticate live endpoint and return `LATEST / NO UPDATE`. Then fresh-load history again while still locked, require the exact binding specifically in `live_updates_sequences` and no newer/conflicting authority, append/fsync/read-back `PUBLISHED`, then release. Transient publication failure may retry only identical bytes under a newly fresh-guarded session; crash-after-promotion recovery is read-only + missing append only; an invalid signed candidate transitions to `FAILED` and remains consumed.

Failure at any CR gate blocks retirement/Human release.
