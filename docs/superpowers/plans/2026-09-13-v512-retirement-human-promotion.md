# v5.1.2 Installer Repository Retirement & Human Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. All behavior changes follow `superpowers:test-driven-development`; each task requires an independent `ag/gemini-pro-agent` review with Critical 0 / Important 0.

**Goal:** Provide deterministic tooling/evidence for retiring and deleting the historical Installer repository without losing forensic custody or operational dependencies, and implement a canonical Human v5.1.2 draft→validate→publish path that cannot become public until deletion outcome is durably verified.

**Architecture:** Keep retirement audit evidence in a Project Release-Audit Ledger that is separate from the Production Sequence Authority Ledger and physically outside the retiring repository. Bind dependency-audit results to an exact source/config/tooling/docs snapshot. Fresh-capture repository/release/asset/ref state immediately before DELETE; treat current-session freshness checks as ephemeral delete authorization. Human release tooling is draft-first, exact-one-asset, remote-hash validated, and cannot publish when draft validation fails.

**Tech Stack:** Python, pytest, Ruff, Git/GitHub CLI through injected executors, SHA-256 canonical JSON evidence, existing repository safety tooling.

**Spec:** `docs/superpowers/specs/2026-09-13-neko-family-5-1-2-baseline-forced-update-revision-3-4.md`

**Master plan:** `docs/superpowers/plans/2026-09-13-neko-family-5-1-2-baseline-release-implementation.md`

**Prerequisite plans:**
- `docs/superpowers/plans/2026-09-13-v512-runtime-trust-enrollment.md`
- `docs/superpowers/plans/2026-09-13-v512-release-authority-proof.md`

RH1–RH3 tooling may be implemented in parallel only after **RT1/K1 packaged conformance is independently accepted as `UPDATER_TRUST_FEASIBLE / C0_I0`, canonical `docs/superpowers/evidence/v512-k1-acceptance.json` is sealed in `K1_ACCEPTANCE_COMMIT`, the runtime plan's Git-only **RT1 security-tool immutability guard** passes, and only then `scripts/verify_v512_k1_acceptance.py --require-git-immutability` passes on the integration branch** where file ownership permits; RT0/K1 plan architecture, K1A public-authority bootstrap, K1B-A profiles, K1B-B custody/`K1B_CUSTODY_SHA256`, or an unsealed reviewer verdict alone do not unlock RH implementation. RH4 and later require both `RUNTIME_TRUST_C0_I0` (RT10) and `RELEASE_AUTHORITY_PROOF_C0_I0` (RA10), because pre-delete/replacement readiness must bind the accepted runtime and release architecture.

## Global Constraints

- Owner disposition is final: `Valeneko-pranmong/Neko-Family-Proxy-Installer` will be **deleted entirely** once all retirement gates pass. Do not ask preserve-vs-delete again.
- DELETE itself is controller-only and is never implemented as an automatic worker action.
- `RETIREMENT_EVIDENCE_READY` is evidence, not reusable delete authorization.
- G19 fresh checks in the current controller execution session are the only operational delete authorization.
- Exact broken v5.1.2 Installer bytes must be custodied outside the retiring repo.
- Forensic scope includes ALL releases, ALL custom assets, ALL tags, and branch-head refs in defined scope, not a hand-picked subset.
- Dependency audit is valid only for the exact bound source/config/tooling/docs snapshot. Any change before DELETE makes it stale.
- Before Human Release object exists, old repo deletion must be live-verified and `INSTALLER_REPOSITORY_DELETED / VERIFIED_DELETED` must be durably read back.
- Human release is created as draft, exact Installer uploaded, draft remotely validated, then and only then `draft=false`.
- Implementers/reviewers do not mutate canonical tag, delete repo, create/upload/publish real releases, or perform other public mutation.

---

## Task RH1: Implement Exact-Snapshot Operational Dependency Audit

**Files:**
- Create: `scripts/release_dependency_audit.py`
- Modify: `scripts/check_repository_safety.py`
- Create: `launcher/tests/test_release_dependency_audit.py`
- Modify: `launcher/tests/test_repository_safety.py`

**Interface contract:** `DependencyFinding(path, line, kind, text_digest)` and `DependencyAuditEvidence(input_snapshot_sha256, result_sha256, approved_source_commit, tracked_tree_sha256, operational_matches, historical_allowed_matches)`. Public functions are `build_dependency_snapshot(repo_root: Path, *, external_inputs: Mapping[str, Path]) -> dict[str, object]`, `audit_old_installer_dependency(repo_root: Path, snapshot: dict[str, object]) -> DependencyAuditEvidence`, and `verify_audit_freshness(repo_root: Path, evidence: DependencyAuditEvidence, *, external_inputs: Mapping[str, Path]) -> bool`.

- [ ] **Step 1: Write RED direct-reference test.**

```python
def test_runtime_reference_to_old_installer_repo_is_operational_blocker(tmp_path):
    repo = fake_repo(tmp_path, {"src/config.py": 'REPO = "Neko-Family-Proxy-Installer"\n'})
    evidence = audit_old_installer_dependency(repo, build_dependency_snapshot(repo, external_inputs={}))
    assert evidence.operational_matches
```

- [ ] **Step 2: RED split-constant test where owner and repository name are stored separately then composed by release tooling.**

- [ ] **Step 3: RED current-doc test (`docs/current`, README/operator guidance) and generated-config test; all operational references block.**

- [ ] **Step 4: RED historical-only test proving an explicitly superseded `docs/superpowers/specs|plans` reference may be classified as historical/non-operational but is still recorded.**

- [ ] **Step 5: RED snapshot freshness test: after a PASS evidence object, change one audited source/config/tooling/docs byte and assert `verify_audit_freshness(repo, evidence, external_inputs={}) is False`.**

- [ ] **Step 6: Run the complete RH1 RED set before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_release_dependency_audit.py tests/test_repository_safety.py -q
```

Expected RED: dependency-audit APIs do not exist and/or current repository-safety behavior does not satisfy direct/split/current-doc/historical/stale-snapshot assertions.

- [ ] **Step 7: Implement deterministic input snapshot.**

For Git-tracked inputs record repository identity, exact approved commit, tracked tree hash, and selected operational files/content hashes. For explicit external/generated inputs record canonical path identifier + content SHA-256. Sort all records before canonical JSON hashing.

- [ ] **Step 8: Implement dependency search categories without broad path ignores.**

Search at least:

```text
Neko-Family-Proxy-Installer
Valeneko-pranmong/Neko-Family-Proxy-Installer
github.com/.../Neko-Family-Proxy-Installer
api.github.com/repos/.../Neko-Family-Proxy-Installer
releases/download/... old-repo patterns
split owner/repository constants in production-capable config/tooling
```

- [ ] **Step 9: Integrate `check_repository_safety.py` so current operational old-repo dependencies fail safety checks; historical evidence stays visible/classified.**

- [ ] **Step 10: Run GREEN/Ruff/diff-check.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_release_dependency_audit.py tests/test_repository_safety.py -q
.venv\Scripts\ruff.exe check ../scripts/release_dependency_audit.py ../scripts/check_repository_safety.py tests/test_release_dependency_audit.py tests/test_repository_safety.py
cd ..
git diff --check
```

- [ ] **Step 11: Commit.**

```cmd
git add scripts/release_dependency_audit.py scripts/check_repository_safety.py launcher/tests/test_release_dependency_audit.py launcher/tests/test_repository_safety.py
git commit -m "feat: bind installer retirement dependency audit"
```

**Review:** C0/I0.

---

## Task RH2: Implement Separate Append-Only Project Release-Audit Ledger

**Files:**
- Create: `scripts/project_release_audit_ledger.py`
- Create: `launcher/tests/test_project_release_audit_ledger.py`

**Interface contract:** `ReleaseAuditEvent(event_type, target_repository_id, target_repository_node_id, target_owner, target_name, evidence, timestamp, previous_entry_sha256)`. Public functions are `verify_release_audit_ledger(path: Path) -> tuple[ReleaseAuditEvent, ...]` and `append_release_audit_event(path: Path, event: ReleaseAuditEvent, expected_previous_sha256: str | None) -> str`.

- [ ] **Step 1: RED append/readback/hash-chain test independent of Production Sequence Authority Ledger.**

- [ ] **Step 2: RED schema test for `RETIREMENT_EVIDENCE_READY`: require forensic inventory digest, exact Installer custody binding including `known_broken_evidence_ref`, `known_broken_evidence_sha256`, and `qualification_status="KNOWN_BROKEN_UNQUALIFIED"`, dependency input/result digests, replacement-readiness digests, Owner disposition DELETE; missing or changed known-broken binding is schema-invalid, and no field is interpreted as `delete_authorized=true`.**

- [ ] **Step 3: RED schema test for `INSTALLER_REPOSITORY_DELETED`: require `result == VERIFIED_DELETED`, execution timestamp/result, post-delete live verification digest, post-delete dependency verification digest.**

- [ ] **Step 4: RED tamper, broken previous hash, stale append, invalid event type/fields tests.**

- [ ] **Step 5: Run the complete RH2 RED set before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_project_release_audit_ledger.py -q
```

Expected RED: release-audit ledger/event validation APIs do not exist and the event-schema/hash-chain assertions cannot pass.

- [ ] **Step 6: Implement canonical append-only JSONL/hash-chain writer/reader. Authoritative path must be supplied externally; reject paths inside the retiring repository when target is that repository.**

- [ ] **Step 7: Add explicit test proving `RETIREMENT_EVIDENCE_READY` alone cannot satisfy any `can_delete` API; this module should not expose a DELETE execution API at all.**

- [ ] **Step 8: Run GREEN/Ruff/diff-check and commit.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_project_release_audit_ledger.py -q
.venv\Scripts\ruff.exe check ../scripts/project_release_audit_ledger.py tests/test_project_release_audit_ledger.py
cd ..
git diff --check
git add scripts/project_release_audit_ledger.py launcher/tests/test_project_release_audit_ledger.py
git commit -m "feat: add project release audit ledger"
```

**Review:** C0/I0.

---

## Task RH3: Capture Complete Installer-Repo Forensics And External Broken-Installer Custody

**Files:**
- Create: `scripts/capture_installer_repo_forensics.py`
- Create: `launcher/tests/test_installer_repo_forensics.py`
- Consume RH2 ledger APIs but do not append `RETIREMENT_EVIDENCE_READY` until dependency/replacement digests exist.

**Forensic output:**

```python
@dataclass(frozen=True)
class RepositoryIdentity:
    numeric_id: int
    node_id: str
    owner: str
    name: str
    default_branch: str
    default_head_sha: str

@dataclass(frozen=True)
class ForensicSnapshot:
    repository: RepositoryIdentity
    repository_identity_sha256: str
    release_inventory_sha256: str
    asset_inventory_sha256: str
    ref_inventory_sha256: str
    complete_forensic_inventory_sha256: str
    canonical_repository_json: bytes
    canonical_releases_json: bytes
    canonical_assets_json: bytes
    canonical_refs_json: bytes

@dataclass(frozen=True)
class ArtifactCustodyEvidence:
    repository_id: int
    repository_node_id: str
    release_id: int
    release_tag: str
    asset_id: int
    asset_name: str
    size: int
    sha256: str
    custody_path: str
    captured_at: str
    known_broken_evidence_ref: str
    known_broken_evidence_sha256: str
    qualification_status: Literal["KNOWN_BROKEN_UNQUALIFIED"]
```

- [ ] **Step 1: Create fake paginated GitHub executor fixtures with multiple releases, draft/prerelease flags, multiple assets, annotated/lightweight tags, and branch refs.**

- [ ] **Step 2: RED test that capture requests/pages through ALL releases and ALL assets, not only v5.1.2. Missing page/incomplete pagination must fail.**

- [ ] **Step 3: RED test canonical inventories are order-independent: same API objects in different response order yield the same digests.**

- [ ] **Step 4: RED test tag inventory records ref object type/SHA and peeled commit where applicable; release captures target_commitish + resolved commit.**

- [ ] **Step 5: RED custody test downloads exact historical broken v5.1.2 asset bytes to an explicitly supplied external directory and records repo ID/node_id, release ID/tag, asset ID/name, size, SHA-256, timestamp, custody path/id, plus immutable `known_broken_evidence_ref`, `known_broken_evidence_sha256`, and `qualification_status="KNOWN_BROKEN_UNQUALIFIED"`. The referenced evidence must identify the verified array-schema Core-verifier failure/provenance; free-form prose alone is insufficient.**

Historical expected cross-check only:

```text
name   = NekoFamilyProxy-Installer.exe
size   = 212293271
sha256 = e069aa2b268d134ca16d038bef58c176d237e01201e638c63e07f5832803e3f7
```

The test must re-hash bytes; expected metadata alone is insufficient. **Implementation RH3 must never write the real retirement-custody path.** Unit/integration tests create both Installer custody and known-broken evidence only under pytest `tmp_path`/an injected temporary custody root.

The known-broken evidence schema used by those tests and later by the controller is exact:

```text
KnownBrokenEvidenceV1 = {
  schema_version: 1,
  repository_id: int,
  repository_node_id: str,
  release_id: int,
  asset_id: int,
  installer_size: int,
  installer_sha256: lowercase hex64,
  historical_source_commit: hex40,
  historical_verifier_path: "installer/scripts/verify-core-install.ps1",
  historical_verifier_sha256: lowercase hex64,
  historical_failure_exit_code: 6,
  historical_failure_output_sha256: lowercase hex64,
  historical_core_payload_sha256: lowercase hex64,
  source_build_provenance_sha256: lowercase hex64,
  qualification_status: "KNOWN_BROKEN_UNQUALIFIED"
}
```

The verifier fields bind the **historical verifier bytes from the exact broken Installer source/build**, not the RT9-fixed current verifier. Test fixtures use fake historical verifier/payload bytes under `tmp_path`; controller G14 later materializes the exact historical verifier from Git/source custody and reproduces/validates the historical failure against exact historical payload evidence before writing any real custody record.

- [ ] **Step 6: RED mismatch tests: live/custodied bytes differ from expected asset metadata/build evidence => exact blocker `FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE`; missing/mismatched known-broken evidence ref/digest/status also blocks. Add a cross-module assertion that `RETIREMENT_EVIDENCE_READY` cannot be constructed unless the exact custody object carries the required known-broken evidence binding.**

- [ ] **Step 7: Run the complete RH3 RED set before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_installer_repo_forensics.py tests/test_project_release_audit_ledger.py -q
```

Expected RED: custody schema lacks the durable known-broken binding and/or retirement evidence can still be constructed without it.

- [ ] **Step 8: Implement deterministic snapshot/custody with injected GitHub/download executor and an injected `custody_root: Path`; tests pass only `tmp_path`. Build `KnownBrokenEvidenceV1` from injected historical verifier/payload/failure fixtures, write it under that test custody root, and produce `ArtifactCustodyEvidence` that satisfies the already-accepted RH2 schema. RH3 must not modify `scripts/project_release_audit_ledger.py`; if RH2 cannot consume the object, STOP and reopen RH2. No DELETE call exists. No implementation test may reference/write `E:\Github\artifacts\v512-retirement-custody`.**

- [ ] **Step 9: Run GREEN/Ruff/diff-check and commit.** GREEN read-backs only the injected `tmp_path` known-broken evidence file and proves its SHA-256 equals the custody object's `known_broken_evidence_sha256`; assert no fixed live-custody path was touched.

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_installer_repo_forensics.py tests/test_project_release_audit_ledger.py -q
.venv\Scripts\ruff.exe check ../scripts/capture_installer_repo_forensics.py tests/test_installer_repo_forensics.py
cd ..
git diff --check
git add scripts/capture_installer_repo_forensics.py launcher/tests/test_installer_repo_forensics.py
git commit -m "feat: capture complete installer repository forensics"
```

**Review:** C0/I0.

---

## Task RH4: Implement Current-Session Retirement Pre-Delete Validator (No DELETE Capability)

**Files:**
- Create: `scripts/retirement_predelete_check.py`
- Create: `launcher/tests/test_retirement_predelete_check.py`
- Consume: RH1 audit evidence/freshness, RH2 latest ledger evidence, RH3 forensic snapshot.

**Interface contract:** `RetirementBlocker` contains exactly `TARGET_IDENTITY_MISMATCH`, `FORENSIC_STATE_CHANGED`, `DEPENDENCY_AUDIT_STALE`, `FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE`, `TAG_AUTHORITY_BLOCKED`, and `RETIREMENT_BLOCKED`. `PreDeleteCheckResult` contains `allowed_now`, `blockers`, `live_inventory_sha256`, and `live_dependency_snapshot_sha256`.

Exact validator signature: `check_predelete_freshness(*, approved_forensic: ForensicSnapshot, live_forensic: ForensicSnapshot, dependency_evidence: DependencyAuditEvidence, live_dependency_snapshot_sha256: str, custody: ArtifactCustodyEvidence, latest_retirement_event: ReleaseAuditEvent, approved_final_source_sha: str, live_tag_commit_sha: str, live_replacement_readiness_sha256: str) -> PreDeleteCheckResult`. The function derives the approved replacement-readiness digest from `latest_retirement_event.evidence` and has no delete executor/callback parameter.

This module validates evidence only. It must have **no function that deletes a repository**.

- [ ] **Step 1: RED PASS test: live owner/name + numeric ID/node_id + complete release/asset/ref digest + dependency input snapshot + canonical tag + custody + ledger all exactly match latest approved evidence.**

- [ ] **Step 2: RED immutable identity mismatch test: same owner/name but changed numeric ID/node_id => `TARGET_IDENTITY_MISMATCH`. No name/URL fallback.**

- [ ] **Step 3: RED complete inventory delta tests: added/removed/changed release, asset, or ref => `FORENSIC_STATE_CHANGED`.**

- [ ] **Step 4: RED dependency snapshot change => `DEPENDENCY_AUDIT_STALE`.**

- [ ] **Step 5: RED canonical tag not resolving exact approved final SHA => `TAG_AUTHORITY_BLOCKED`.**

- [ ] **Step 6: RED missing/mismatched external broken-installer custody hash/IDs => `FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE`.**

- [ ] **Step 7: RED test an old `RETIREMENT_EVIDENCE_READY` event plus fresh state mismatch still blocks; ledger status is not reusable authorization.**

- [ ] **Step 8: Run the complete RH4 RED set before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_retirement_predelete_check.py -q
```

Expected RED: the pre-delete validator does not exist and the identity/inventory/freshness/custody/tag blocker matrix cannot pass.

- [ ] **Step 9: Implement pure comparison logic; require fresh live snapshot objects passed from controller. Do not cache PASS across sessions.**

- [ ] **Step 10: Run GREEN/Ruff/diff-check and commit.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_retirement_predelete_check.py -q
.venv\Scripts\ruff.exe check ../scripts/retirement_predelete_check.py tests/test_retirement_predelete_check.py
cd ..
git diff --check
git add scripts/retirement_predelete_check.py launcher/tests/test_retirement_predelete_check.py
git commit -m "feat: validate fresh installer repo retirement state"
```

**Review:** C0/I0. Reviewer must verify module cannot perform DELETE itself.

---

## Task RH5: Replace Old Installer Publisher With Canonical Human Draft Publisher

**Files:**
- Rename/rewrite: `scripts/publish_installer_release.py` → `scripts/publish_human_release.py`
- Rename/rewrite: `scripts/verify_installer_release_assets.py` → `scripts/verify_human_release_assets.py`
- Rename/rewrite: `launcher/tests/test_publish_installer_release.py` → `launcher/tests/test_publish_human_release.py`
- Rename/rewrite: `launcher/tests/test_verify_installer_release_assets.py` → `launcher/tests/test_verify_human_release_assets.py`

**Constants:**

```python
CANONICAL_HUMAN_REPO = "Valeneko-pranmong/Neko-Family-Proxy"
REQUIRED_HUMAN_ASSETS = ("NekoFamilyProxy-Installer.exe",)
FORBIDDEN_HUMAN_ASSETS = (
    "NekoLauncher.exe",
    "NekoUpdater.exe",
    "NekoProxyCore.zip",
    "release-v2.json",
)
```

**Interface direction:** `publish_human_release(*, tag: str, target_commit: str, installer_path: Path, body: str, deletion_evidence: ReleaseAuditEvent, executor: CommandExecutor) -> HumanPublishResult`. `deletion_evidence` must be the read-back `INSTALLER_REPOSITORY_DELETED / VERIFIED_DELETED` event. Injected executor returns structured GitHub state; tests perform no real mutation.

- [ ] **Step 1: RED test publisher refuses to start unless caller supplies proof that G22 deletion-result ledger event was read back as `INSTALLER_REPOSITORY_DELETED / VERIFIED_DELETED`.**

- [ ] **Step 2: RED command-order test: first GitHub Release mutation is draft creation in main repo with `draft=true`, `prerelease=false`; no pre-G22 draft or upload path exists.**

- [ ] **Step 3: RED test exact Installer is uploaded and draft live-readback requires exactly one custom asset named `NekoFamilyProxy-Installer.exe`.**

- [ ] **Step 4: RED tests extra machine asset, wrong/missing asset, wrong tag/source, wrong release body, wrong remote size, or wrong remote SHA-256 all return `DRAFT_VALIDATION_FAILED`.**

- [ ] **Step 5: RED safety test proves none of those failure paths issue a command setting `draft=false`.**

```python
def test_invalid_draft_is_never_published(
    fake_exec_with_tampered_remote_asset,
    qualified_installer,
    verified_deleted_event,
    approved_human_body,
):
    result = publish_human_release(
        tag="v5.1.2",
        target_commit="a" * 40,
        installer_path=qualified_installer,
        body=approved_human_body,
        deletion_evidence=verified_deleted_event,
        executor=fake_exec_with_tampered_remote_asset,
    )
    assert result.status == "DRAFT_VALIDATION_FAILED"
    assert not any(
        "draft=false" in " ".join(cmd)
        for cmd in fake_exec_with_tampered_remote_asset.commands
    )
```

- [ ] **Step 6: RED valid-draft test: only after draft validation PASS does publisher issue public promotion, then perform a fresh public readback.**

- [ ] **Step 7: RED body contract test requires v5.1.0-style bilingual structure and explicit 5.1.0 uninstall→5.1.2 install notice.**

- [ ] **Step 8: RED no-secret-argv test: no `gh auth token` and no bearer token argv. Hosted asset bytes are re-read/re-hashed through the exact RA5 mechanism: `gh api repos/{owner}/{repo}/releases/assets/{asset_id} -H "Accept: application/octet-stream"` with stdout connected directly to a parent-opened temporary file; no curl and no shell redirection.**

- [ ] **Step 9: Run the complete RH5 RED set before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_publish_human_release.py tests/test_verify_human_release_assets.py -q
```

Expected RED: canonical Human draft publisher/verifier APIs do not exist and/or the legacy publisher cannot satisfy deletion-evidence, draft-order, exact-one-asset, bilingual-body, remote-hash, and secret-safe argv contracts.

- [ ] **Step 10: Implement draft/upload/validate/promote/readback with injected executor. Do not put canonical tag mutation or old-repo DELETE into this module.**

- [ ] **Step 11: Run GREEN/Ruff/diff-check and commit.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_publish_human_release.py tests/test_verify_human_release_assets.py -q
.venv\Scripts\ruff.exe check ../scripts/publish_human_release.py ../scripts/verify_human_release_assets.py tests/test_publish_human_release.py tests/test_verify_human_release_assets.py
cd ..
git diff --check
git add scripts/publish_human_release.py scripts/verify_human_release_assets.py launcher/tests/test_publish_human_release.py launcher/tests/test_verify_human_release_assets.py
git add -u scripts/publish_installer_release.py scripts/verify_installer_release_assets.py launcher/tests/test_publish_installer_release.py launcher/tests/test_verify_installer_release_assets.py
git commit -m "refactor: publish canonical human release from validated draft"
```

**Review:** C0/I0, security/release-boundary focused.

---

## Task RH6: Remove Operational Old-Installer-Repo Dependencies And Mark Historical Docs Explicitly

**File ownership contract:** RH1 audit output is the authoritative input to RH6. The baseline **existing/tracked** operational surfaces that RH6 must audit/remediate are `release_target.json`, `scripts/release_controller.py`, `scripts/publish_atomic_release.py`, the RH5-created `scripts/publish_human_release.py`, `.github/workflows/release.yml`, `docs/current/runtime-distribution.md`, `docs/current/README.md`, `docs/README.md`, `docs/HANDOFF.md`, and `docs/PROJECT_CONTEXT.md`. Root `README.md` and `SECURITY.md` are not present in the current tracked tree and are not baseline task paths. In addition, **every operational finding emitted by the accepted RH1 audit must be explicitly remediated or classified by the tested historical-only rule**. Historical `docs/superpowers/specs/**` and `docs/superpowers/plans/**` are changed only when RH1 flags ambiguity requiring an explicit superseded marker; workers do not pick extra files ad hoc.

- [ ] **Step 1: Run RH1 dependency audit on the implementation branch and save the exact RED findings list.** This is RH6's RED evidence: before remediation, require at least one operational old-repo finding from the known current topology; an empty result without prior remediation is `RH6_UNEXPECTED_CLEAN_BASELINE` and STOP rather than silently proceeding.

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B scripts\release_dependency_audit.py --repo . --json-out artifacts\dependency-audit-before.json
```

Exact CLI shape is implemented/tested in RH1; use it here rather than an ad-hoc grep.

- [ ] **Step 2: Fix runtime/config/release-tooling references so production machine destination is Updates repo and Human destination is main repo.**

- [ ] **Step 3: Re-run audit; confirm runtime/tooling category is clean before touching docs.**

- [ ] **Step 4: Update current operator/user docs to the new topology and Human migration contract. Do not link normal users to the machine repo as a download surface.**

- [ ] **Step 5: Mark obsolete Superpowers v5.1.2 architecture/plan documents as superseded by Revision 3.4/master plan when their old operational topology could mislead; keep forensic/history content intact.**

- [ ] **Step 6: Add/adjust RH1/RH repository-safety tests so current operational old-repo references fail while explicitly historical references remain classified and visible.**

- [ ] **Step 7: Run dependency audit GREEN + repository safety + docs-relevant tests/Ruff/diff check.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_release_dependency_audit.py tests/test_repository_safety.py -q
cd ..
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
git diff --check
```

- [ ] **Step 8: Build and verify the exact RH6 commit path set before staging.** Write sorted newline-delimited paths to external evidence file `E:\Github\artifacts\v512-plan-execution\rh6-commit-paths.txt`. The set is exactly: tracked files actually changed by RH6 whose path is either in the baseline ownership list above or appears as an operational/historical-classification finding in the accepted RH1 audit, plus `launcher/tests/test_release_dependency_audit.py` and `launcher/tests/test_repository_safety.py` when those tests changed. Reject directories, wildcards, nonexistent paths, unrelated dirty paths, or any changed RH6 file absent from this set. Re-read the file and record its SHA-256.

- [ ] **Step 9: Stage only that verified exact path set and commit.**

```cmd
git add --pathspec-from-file=E:\Github\artifacts\v512-plan-execution\rh6-commit-paths.txt
git diff --cached --name-only
git commit -m "docs: retire old installer repository dependencies"
```

Require `git diff --cached --name-only` to equal the sorted evidence path set exactly before commit; otherwise unstage RH6 paths and STOP. Root `README.md`/`SECURITY.md` are not staged because they do not exist in the current tracked tree.

**Review:** C0/I0, with exact dependency-audit evidence.

---

## Task RH7: Retirement/Human Tooling Workstream Acceptance

- [ ] **Step 1: Run all retirement/Human tooling tests.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_release_dependency_audit.py tests/test_repository_safety.py tests/test_project_release_audit_ledger.py tests/test_installer_repo_forensics.py tests/test_retirement_predelete_check.py tests/test_publish_human_release.py tests/test_verify_human_release_assets.py -q
```

- [ ] **Step 2: Run exact RH repository-safety, Ruff, and diff checks.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
launcher\.venv\Scripts\ruff.exe check scripts\release_dependency_audit.py scripts\check_repository_safety.py scripts\project_release_audit_ledger.py scripts\capture_installer_repo_forensics.py scripts\retirement_predelete_check.py scripts\publish_human_release.py scripts\verify_human_release_assets.py launcher\tests\test_release_dependency_audit.py launcher\tests\test_repository_safety.py launcher\tests\test_project_release_audit_ledger.py launcher\tests\test_installer_repo_forensics.py launcher\tests\test_retirement_predelete_check.py launcher\tests\test_publish_human_release.py launcher\tests\test_verify_human_release_assets.py
git diff --check
```
- [ ] **Step 3: Verify by source/test inspection that no implementation module created in RH1–RH6 contains a repository DELETE API or canonical tag mutation path except fake/controller command modeling explicitly designed only for validation. Actual DELETE remains outside worker code path.**
- [ ] **Step 4: Record exact branch HEAD, task commits/reviews, dependency-audit input/result digest schema, forensic inventory schema, ledger event schemas, and draft-publisher command-order evidence.**
- [ ] **Step 5: Independent `ag/gemini-pro-agent` review against Spec Revision 3.4 + this plan. Required C0/I0.**
- [ ] **Step 6: Reopen owning RH task on any C/I finding; rerun acceptance.**
- [ ] **Step 7: Mark `RETIREMENT_HUMAN_TOOLING_C0_I0` only after all pass.**

No live repository deletion, tag mutation, draft creation, asset upload, or publication occurs in RH7.

---

# Controller-Only Retirement/Human Promotion Gates

These are later controller execution gates. Plan approval or source implementation approval does **not** itself authorize them.

## G14a — Complete Forensic Capture

- [ ] Fresh-read immutable repository numeric ID/node_id, exact owner/name, visibility/state, default branch/default-head, ALL releases, ALL custom assets, ALL tags/peeled commits, and branch-head refs in scope using RH3 tooling.
- [ ] Canonical inventory digests are complete and persisted outside retiring repo.

## G14b — Exact Broken Installer + Historical-Failure External Custody

- [ ] Controller creates the **real** custody root `E:\Github\artifacts\v512-retirement-custody` only in this live forensic phase, then custodies exact old v5.1.2 `NekoFamilyProxy-Installer.exe` bytes there.
- [ ] Resolve the broken Installer’s exact historical source/build commit from trusted build provenance. Materialize `installer/scripts/verify-core-install.ps1` from that historical commit/source custody (not the RT9-fixed worktree), hash those historical bytes, and run those exact bytes against the exact historical Core payload evidence in an isolated temporary directory. Require the historically verified failure exit code 6 and hash the exact normalized failure output.
- [ ] Write canonical `KnownBrokenEvidenceV1` to `E:\Github\artifacts\v512-retirement-custody\known-broken-v512-installer-evidence.json`, fsync/read-back/hash it, and bind that path/digest into `ArtifactCustodyEvidence`.
- [ ] Live/custody/build evidence must agree on repository/release/asset IDs, Installer size/SHA-256, historical source commit, historical verifier SHA-256, historical failure output digest, Core payload digest, and provenance digest. Any disagreement is `FORENSIC_ARTIFACT_CUSTODY_INCOMPLETE` and blocks retirement.

## G14c/G14d — Dependency + Replacement Readiness

- [ ] Run RH1 audit against exact approved source/config/tooling/docs snapshot; operational dependency count must be zero.
- [ ] Verify canonical main repo + production Updates architecture is ready and machine baseline/live self-resolution gates already passed.

## G14e/G14f — Durable Retirement Preconditions

- [ ] Construct final retirement evidence package including dependency/replacement digests.
- [ ] Append/readback `RETIREMENT_EVIDENCE_READY` in Project Release-Audit Ledger.
- [ ] Treat this as evidence only; never as DELETE authorization.

## G15 — Mutation-Free Human Preflight

- [ ] Locally prepare exact final Installer hash/size, approved bilingual body, expected one-asset set, and GitHub request payload.
- [ ] Capture current canonical `v5.1.2` tag + intended exact mutation.
- [ ] **Do not create a draft Human Release and do not upload asset.**

## G16/G17 — Exact Owner-Approved Canonical Tag Mutation

- [ ] Present current tag target, exact approved final SHA, and exact required mutation to Owner.
- [ ] Only after explicit Owner approval, controller performs exactly that mutation.
- [ ] Fresh live readback/peel must show `refs/tags/v5.1.2^{commit} == approved final SHA`.

## G18/G19 — Current-Session Fresh DELETE Authorization

In one controller-controlled session immediately before DELETE:

- [ ] Fresh-capture immutable identity + complete release/asset/ref inventory.
- [ ] Require live immutable identity exact match to forensic target.
- [ ] Require all inventory digests exact match to latest approved forensic snapshot; any delta => `RETIREMENT_BLOCKED / FORENSIC_STATE_CHANGED` and recapture/audit/superseding ledger workflow.
- [ ] Fresh-capture dependency-audit input snapshot; mismatch => `RETIREMENT_BLOCKED / DEPENDENCY_AUDIT_STALE` and rerun audit.
- [ ] Reverify tag authority, replacement readiness, external Installer custody, and latest ledger readback.
- [ ] If session is interrupted/stale, discard G19 PASS and rerun G18/G19.

## G20 — Controller-Only DELETE

- [ ] Immediately after current-session G19 PASS, Project Controller fresh-confirms exact owner/name + numeric ID/node_id and issues deletion of **entire** `Valeneko-pranmong/Neko-Family-Proxy-Installer` repository.
- [ ] No Hermes implementer/reviewer/coding worker performs this operation.

## G21 — Post-Delete Live Verification

- [ ] Fresh-query GitHub; old repository/release/tag/asset namespace must no longer act as public authority.
- [ ] Rerun zero-operational-dependency verification.
- [ ] If live verification unavailable, Human Release stays blocked.

## G22 — Durable Actual Deletion Outcome

- [ ] Append/readback `INSTALLER_REPOSITORY_DELETED` with `result=VERIFIED_DELETED`, immutable target identity, pre-delete digests, delete result/timestamp, post-delete verification digest, and post-delete dependency digest.
- [ ] Ledger failure/readback failure blocks Human Release even if repository deletion itself succeeded.

## G23 — Draft → Validate → Publish Canonical Human v5.1.2

- [ ] Only after G22 PASS, create main-repo `v5.1.2` as `draft=true`, `prerelease=false`.
- [ ] Upload exact qualified `NekoFamilyProxy-Installer.exe`.
- [ ] While still draft, live-read tag/source/body/asset set and re-download/re-hash remote Installer; require exact size/SHA-256 and exactly one custom asset.
- [ ] Any validation failure => STOP; do not set `draft=false`.
- [ ] Only validation PASS => set `draft=false`.
- [ ] Fresh public readback verifies tag/source, bilingual v5.1.0-style body, migration notice, exact one Installer asset, no machine assets, and old repo remains unavailable.

## G24 — Production v5.1.3 Remains Blocked

No production v5.1.3 release without a new explicit Owner authorization.
