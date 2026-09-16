# RA-SR1 Evidence: Terminal Supersession of Signed-but-Unpublished Sequence 8

- **Task**: `RA-SR1`
- **Status**: `DRY_RUN_VERIFIED`
- **PRODUCTION_LEDGER_MUTATED**: `false`
- **NO_PUBLIC_MUTATION**: `true`
- **NO_PRODUCTION_SIGNING**: `true`

---

## 1. Context and Architectural Basis

Under the approved single-repo release design (`docs/superpowers/specs/2026-09-16-single-repo-unified-release-design.md`), the separate Updates repository is permanently superseded in favor of canonical publication to `Valeneko-pranmong/Neko-Family-Proxy`.

Prior to this architecture migration, release sequence 8 (`stable-0008`) was allocated (`RESERVED`) and signed (`SIGNED`) against the superseded topology, but **never published**. The signed bytes and historical envelope are immutable ledger history. Under authority ledger rules, `SIGNED -> FAILED` is an approved terminal transition that safely retires the superseded release without rewriting history.

Reconciliation after this terminal event advances the authority sequence to **9**, allowing the unified single-repo release to proceed on a fresh sequence.

---

## 2. Production Authority State (Read-Only Verification)

- **Authority Ledger**: `E:\Github\authority\v512-production-sequence-authority\production-sequence-ledger-v1.jsonl`
- **Authority Custody Root**: `E:\Github\artifacts\v512-production-authority-custody`
- **Authority Floor**: Sequence 7 (`stable-0007`) Genesis
- **Evaluated Sequence**: 8 (`stable-0008`)

### 2.1 Immutable Sequence 8 Signed Identity
- **Sequence**: `8`
- **Release ID**: `stable-0008`
- **Version**: `5.1.2`
- **Channel**: `stable`
- **Source Commit**: `efb79a0b62d27437fd7ac0c7b2c4bfad8c4264ce`
- **Component Set SHA-256**: `4520cba9be1785155630992d75ebd11f7616a1256fdcd394abb9950ad6681f57`
- **Payload SHA-256**: `ed9d510fc3aca08b70ef1a78864fd1c632a4f87b0a285fc3360e2627359161f0`
- **Envelope SHA-256**: `0ee3134aaddffab345eddec669918fe3defc794f446b922d22d61f3b91be50b7`
- **Key ID**: `neko-update-prod-1`
- **Current Ledger Head (Entry SHA-256)**: `ac89aea38c06ab62ab8c6fab1e99db6491a05d0a41a15eb8a041a4b83e4dca58`

---

## 3. Supersession Request Contract

```python
SupersedeSignedReleaseRequest(
    sequence=8,
    release_id="stable-0008",
    source_commit="efb79a0b62d27437fd7ac0c7b2c4bfad8c4264ce",
    component_set_sha256="4520cba9be1785155630992d75ebd11f7616a1256fdcd394abb9950ad6681f57",
    payload_sha256="ed9d510fc3aca08b70ef1a78864fd1c632a4f87b0a285fc3360e2627359161f0",
    envelope_sha256="0ee3134aaddffab345eddec669918fe3defc794f446b922d22d61f3b91be50b7",
    latest_ledger_entry_sha256="ac89aea38c06ab62ab8c6fab1e99db6491a05d0a41a15eb8a041a4b83e4dca58",
    approved_spec_commit="224eb9cb43df0ca0fa583fa41a0c219622392a56",
    reason_code="ARCHITECTURE_SUPERSEDED_BEFORE_PUBLICATION",
)
```

---

## 4. Dry-Run Execution & Invariant Proof

- **Command**: `prepare_signed_release_supersession(ledger_path=prod_ledger, custody_root=prod_custody, request=req, mutate=False)`
- **Execution Result**:
  - `event.sequence`: `8`
  - `event.status`: `FAILED`
  - `event.release_id`: `stable-0008`
  - `event.source_commit`: `efb79a0b62d27437fd7ac0c7b2c4bfad8c4264ce`
  - `event.previous_entry_sha256`: `ac89aea38c06ab62ab8c6fab1e99db6491a05d0a41a15eb8a041a4b83e4dca58`
  - `next_unused_sequence`: `9`
  - `mutated`: `false`
  - `PRODUCTION_LEDGER_MUTATED=false` (confirmed by file size, SHA-256 hash, and mtime comparisons)

---

## 5. Automated Verification Summary

- `launcher/tests/test_production_sequence_ledger.py` (30 tests passed)
- `tests/test_release_controller_split.py` (27 tests passed)
- `scripts/check_repository_safety.py`: Passed
- `git diff --check`: Clean (0 errors)
- `ruff check`: Clean (0 errors)
