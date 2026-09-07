# Software Update Phase 3 — Slice L Implementation Plan: Candidate Preparation (5.1.0a3) & Gate #2 Package

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the bounded, release-critical Owner Gate #2 engineering blockers in the Controlled-Core client path, release-v2 offline tooling, and release publication workflow before bumping the Launcher to `5.1.0a3`, building standalone candidates, and assembling the Owner Gate #2 Production Authorization Package. No production mutation is part of this plan.

**Architecture:** This is an amendment to the original Slice L candidate-preparation intent, not a replacement of that intent. Units A-C are new prerequisites discovered by the verified Phase 3 §14.1/§17 audit. Only after they are independently reviewed and green may Unit D perform the original version bump, candidate packaging, packaged GUI smoke, installer-authority preparation, and external Owner package assembly. The Controlled-Core credential remains a narrowly scoped in-memory input to the fixed Admin artifact-grant request; v2 release signing remains offline and file-based; ordinary tag pushes may build candidates but cannot publish a GitHub release.

**Tech Stack:** Python 3.11, PyInstaller 6.21.0, pytest 8.3.5, Ruff 0.11.2, Ed25519 via `cryptography`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-06-software-update-phase-3-design.md` (§§12, 13, 14.1, 17).

---

## Global Constraints and Execution Contract

- Release-oriented scope only: Critical/Important findings required for Slice L. Do not expand to hostile-local defenses, revive family lease/job architecture, or refactor unrelated code.
- Preserve the existing `5.1.0a2` artifacts. New output is isolated at `E:\Github\artifacts\phase3\5.1.0a3-candidate`.
- No private key, production public key, raw distribution capability, capability digest, grant URL, or invented Core identity may enter Git, docs, logs, argv, environment, helper IPC, or test fixtures intended as production data.
- No network publication, deployment, production signing, production capability provisioning, active-release mutation, public sequence allocation, tag, or GitHub release occurs in Units A-D.
- The current authoritative environment is `launcher\.venv`. Historical `build\venv-5.1` commands below are retained only as stale historical context and must not be used for this candidate.
- Run commands from the repository root unless a step explicitly starts with `cd launcher`.
- Every implementation unit follows this exact lifecycle: tests-only change and narrow commit; run the named focused test and capture a genuine assertion-level RED (collection/import/configuration errors do not count); production change; focused GREEN plus Ruff; blocker review with Critical=0 and Important=0; narrow production commit. Do not mix tests and production in either commit.
- After each unit, run `launcher\.venv\Scripts\python.exe -m pytest -q` and `launcher\.venv\Scripts\python.exe -m ruff check launcher/src launcher/tests scripts installer/scripts`; use authoritative test/build summaries for counts.
- If any RED is not genuine, any focused/full suite fails, or blocker review reports Critical/Important findings, stop that unit. Do not bump, package, sign, publish, or proceed by waiver.
- Owner Gate #2 remains closed throughout this plan. Local green status is `ENGINEERING_PASS / READY_FOR_OWNER_AUTHORIZATION`, never `LIVE_UPDATE_AUTO_COMPLETE`.

---

## Amendment Prerequisites (must complete before the candidate bump)

### Task 1 / Unit A — Controlled-Core Capability Client Path

**Files:**
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_client.py`
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_apply.py`
- Modify: `launcher/src/neko_launcher/bootstrap/app_factory.py`
- Reuse without changing storage semantics unless a focused defect requires it: `launcher/src/neko_launcher/infrastructure/distribution_credential.py`
- Test: `launcher/tests/test_software_update_client.py`
- Test: `launcher/tests/test_software_update_apply.py`
- Test: `launcher/tests/test_software_update_composition.py`
- Test privacy boundary if needed: `launcher/tests/test_software_update_privacy.py`

**Required interfaces and boundaries:**
- Existing credential primitives remain `get_distribution_capability()`, `set_distribution_capability()`, and `clear_distribution_capability()` at Credential Manager target `NEKO-FAMILY/SoftwareUpdateDistribution/v1`.
- Add an injection seam such as `distribution_capability_provider: Callable[[], str | None]`; production composition supplies `get_distribution_capability`, while tests supply spies/fakes. Do not read the credential in the constructor, manifest/check path, metadata-only path, or Launcher-only path.
- Keep anonymous `HttpArtifactGrantGateway.grant(artifact_id)` for Launcher grants. Add a separate, explicit Core operation such as `grant_core(artifact_id, capability)` rather than making every grant implicitly authenticated. If implementation review proves an optional argument is cleaner, it must still make anonymous versus controlled calls explicit at each call site and preserve all negative tests below.
- Validate capability before opening the Core grant request: exactly 43 ASCII base64url characters (`[A-Za-z0-9_-]{43}`), decoding to exactly 32 bytes, and equal to the canonical RFC 4648 base64url no-padding re-encoding of those bytes. Reject missing, empty, malformed, padded, non-canonical, or wrong-length values with a closed safe error before network I/O.
- Send exactly `Authorization: NekoDistribution <canonical-base64url32-no-padding>` only on `POST <fixed normalized Admin base URL>/api/software-update/artifact-grant`. Keep the compact JSON body exactly `{"artifact_id":"<artifact-id>"}` (with the actual artifact ID as the string value).
- Treat the normalized Admin base URL captured by `HttpArtifactGrantGateway` construction as the sole authority. The Core method constructs the same fixed grant endpoint internally; it must not accept an origin, endpoint, header map, or arbitrary URL from its caller.
- Never attach Authorization to manifest requests, anonymous Launcher grants, artifact GETs, redirects, logs/errors/repr, downloader helpers, subprocess arguments/environment, or Launcher↔Updater IPC. Continue using the no-redirect opener.
- `SoftwareUpdateApplyService.prepare()` may request the capability only after the verified v2 payload and helper response establish `changed["core"] is True`, and immediately before the changed Core grant. Missing/invalid local capability fails closed before that grant and aborts the prepared helper safely. Changed Launcher-only and metadata-only updates perform zero credential reads.

- [ ] **Step 1: Write the tests-only contract.** Add focused tests proving: anonymous Launcher grant has no Authorization header; Core grant has the exact scheme/value on the exact fixed Admin grant origin and unchanged body; redirects are not followed and cannot receive the header; artifact GET has no Authorization/cookies; malformed/missing capability causes zero Core grant network calls; verified changed Core reads once; Launcher-only and metadata/no-download paths read zero times; capability/grant URL is absent from exceptions, repr, diagnostics, downloader calls, helper command, and IPC bodies.
- [ ] **Step 2: Commit tests only.** `git add launcher/tests/test_software_update_client.py launcher/tests/test_software_update_apply.py launcher/tests/test_software_update_composition.py launcher/tests/test_software_update_privacy.py && git commit -m "test: specify controlled core grant capability path"`
- [ ] **Step 3: Prove genuine RED.** Run `launcher\.venv\Scripts\python.exe -m pytest -q launcher/tests/test_software_update_client.py launcher/tests/test_software_update_apply.py launcher/tests/test_software_update_composition.py launcher/tests/test_software_update_privacy.py`. Record failing assertion names showing the absent Core-only interface/lazy provider/header behavior; stop if failure is import or collection only.
- [ ] **Step 4: Implement the minimum production path** in the three named production files. Do not modify capability provisioning UI or Admin server behavior.
- [ ] **Step 5: Prove focused GREEN and lint.** Run the Step 3 pytest command, then `launcher\.venv\Scripts\python.exe -m ruff check launcher/src/neko_launcher/infrastructure/software_update_client.py launcher/src/neko_launcher/infrastructure/software_update_apply.py launcher/src/neko_launcher/bootstrap/app_factory.py launcher/tests/test_software_update_client.py launcher/tests/test_software_update_apply.py launcher/tests/test_software_update_composition.py launcher/tests/test_software_update_privacy.py`.
- [ ] **Step 6: Run full regression** using the global commands.
- [ ] **Step 7: Blocker review.** Independently inspect the diff against §14.1 for exact-origin confinement, lazy reads, no forwarding, no secret-bearing diagnostics, no anonymous Core fallback, and old-install preservation. Require Critical=0 and Important=0; otherwise return to tests.
- [ ] **Step 8: Commit production only.** `git add launcher/src/neko_launcher/infrastructure/software_update_client.py launcher/src/neko_launcher/infrastructure/software_update_apply.py launcher/src/neko_launcher/bootstrap/app_factory.py launcher/src/neko_launcher/infrastructure/distribution_credential.py && git commit -m "feat: authorize controlled core artifact grants"`
- [ ] **Owner-gate stop:** no real capability is created, read for evidence, copied, rotated, or provisioned; no Admin endpoint or storage policy is changed.

---

### Task 2 / Unit B — Phase 3 Release-v2 Offline Tooling

**Files:**
- Inspect/preserve legacy semantics: `scripts/sign_software_release.py`
- Create: `scripts/build_software_release_v2.py`
- Reuse verifier/model: `launcher/src/neko_launcher/updater/manifest_v2.py`
- Reuse canonical JSON: `launcher/src/neko_launcher/updater/canonical_json.py`
- Create: `launcher/tests/test_build_software_release_v2.py`
- Keep existing regression: `launcher/tests/test_sign_software_release.py`

**CLI and data contract:**
- Create a focused v2 tool rather than silently changing the legacy v1 signer's payload contract. The new CLI accepts explicit JSON release metadata input, explicit `--launcher-artifact` and `--core-artifact` file paths, explicit `--private-key-file`, explicit `--key-id`, explicit `--public-key-file`, and explicit `--output`.
- Input JSON supplies all non-derived v2 fields and component metadata required by `parse_release_v2`, including exact `artifact_id`, version, installed identity, formats/distributions as supported by the verified v2 model, and updater protocol. The tool derives each artifact SHA-256 and byte size from the supplied files and rejects disagreement rather than trusting claimed values. Do not invent or broaden model values; if distribution is represented by the current verified payload/interface, accept only its closed values, otherwise reject an attempted unknown distribution at the tool input boundary without altering signed schema.
- Private key input is file path only. Reject `--private-key`, inline material, environment-key modes, non-Ed25519 keys, malformed key files, invalid/implicit key IDs, malformed/extra-field schemas, unknown component/distribution/format/protocol values, and artifact metadata mismatch.
- Write canonical signed envelope JSON to the explicit output using create-new/no-overwrite semantics. If repository convention supports an explicit overwrite policy, it must be a separately named opt-in flag with tests; default remains refusal.
- Before reporting success, load the separately supplied public-key file, call `verify_release_envelope_v2`, and independently re-hash/re-size both artifact files against the verified payload. Verification must be offline. Do not generate a production key or use network access.

- [ ] **Step 1: Write `launcher/tests/test_build_software_release_v2.py` only.** Use temporary artifact files and ephemeral Ed25519 keys. Cover canonical deterministic payload/envelope construction, separate-public-key verification, SHA/size derivation and mismatch rejection, output create-new behavior, malformed/extra fields, unsupported protocols/formats/distributions, wrong public key, inline/env private-key rejection, and no secret bytes in stdout/stderr.
- [ ] **Step 2: Commit tests only.** `git add launcher/tests/test_build_software_release_v2.py && git commit -m "test: specify offline phase 3 release v2 tooling"`
- [ ] **Step 3: Prove genuine RED.** Run `launcher\.venv\Scripts\python.exe -m pytest -q launcher/tests/test_build_software_release_v2.py`; the RED must be assertion-level for the missing behavior, not merely an unhandled import/collection failure.
- [ ] **Step 4: Implement `scripts/build_software_release_v2.py`** with importable pure helpers plus `main()`, canonical serialization, create-new output, safe generic errors, and no network code. Leave `scripts/sign_software_release.py` behavior intact.
- [ ] **Step 5: Prove focused GREEN and legacy compatibility.** Run `launcher\.venv\Scripts\python.exe -m pytest -q launcher/tests/test_build_software_release_v2.py launcher/tests/test_sign_software_release.py`, then `launcher\.venv\Scripts\python.exe -m ruff check scripts/build_software_release_v2.py launcher/tests/test_build_software_release_v2.py`.
- [ ] **Step 6: Run full regression** using the global commands.
- [ ] **Step 7: Blocker review.** Require Critical=0 and Important=0 for private-key ingress, canonical bytes, v2 schema fidelity, artifact binding, output overwrite, secret-safe output, and offline-only behavior.
- [ ] **Step 8: Commit production only.** `git add scripts/build_software_release_v2.py && git commit -m "feat: add offline phase 3 release v2 builder"`
- [ ] **Owner-gate stop:** exercise only ephemeral test keys. Do not generate/use a production key, sign a candidate, allocate a public sequence, or publish an envelope.

---

### Task 3 / Unit C — Release Workflow Publication Gate

**Files:**
- Modify: `.github/workflows/release.yml`
- Create: `launcher/tests/test_release_workflow_publication_gate.py`

**Workflow contract:**
- Preserve candidate compilation of both `NekoLauncher.exe` and `NekoUpdater.exe`, updater `--self-check`, checksum assembly, and `actions/upload-artifact` on ordinary `v*` tag pushes.
- Separate candidate build/artifact upload from public GitHub release publication. Add `workflow_dispatch` input `publish_release` of type boolean with explicit default `false` (and an explicit tag/ref input if required to identify a pre-existing candidate), or use a dedicated protected GitHub environment approval job. The chosen YAML must make `gh release create` unreachable when `github.event_name == 'push'`, even for a tag.
- Prefer a separate `publish-release` job with least privilege: build job `contents: read`; publication job alone `contents: write`. Its `if:` must require manual dispatch and the explicit true input (plus successful candidate job). Do not add secrets; `github.token` remains job-scoped only where publication is authorized.
- Publication must consume the checksummed candidate artifact produced by the same authorized run or an explicitly verified immutable artifact; no rebuild-with-different-input shortcut.

- [ ] **Step 1: Write the static tests only.** Parse `.github/workflows/release.yml` and assert: tag push remains a trigger; both PyInstaller specs and updater self-check remain; artifact upload and `SHA256SUMS.txt` remain; no build/tag-push step can run `gh release create`; publication requires `workflow_dispatch` plus explicit boolean true (or named protected environment); publication alone has write permission; no new `secrets.*` reference appears.
- [ ] **Step 2: Commit tests only.** `git add launcher/tests/test_release_workflow_publication_gate.py && git commit -m "test: require manual release publication gate"`
- [ ] **Step 3: Prove genuine RED.** Run `launcher\.venv\Scripts\python.exe -m pytest -q launcher/tests/test_release_workflow_publication_gate.py`; capture the assertion showing ordinary tag push can currently publish.
- [ ] **Step 4: Implement the minimum workflow split** in `.github/workflows/release.yml`, retaining candidate artifacts/checksums and updater carry/build.
- [ ] **Step 5: Prove focused GREEN and syntax review.** Run the Step 3 pytest command and inspect the parsed workflow event/condition values (including YAML parsers that coerce `on`) rather than relying on text grep.
- [ ] **Step 6: Run full regression** using the global commands.
- [ ] **Step 7: Blocker review.** Require Critical=0 and Important=0 for every event path, job dependency, permissions, artifact identity, and expression truth table. Explicitly evaluate `push/tag`, `workflow_dispatch=false`, and `workflow_dispatch=true`.
- [ ] **Step 8: Commit production only.** `git add .github/workflows/release.yml && git commit -m "ci: gate public release publication on owner dispatch"`
- [ ] **Owner-gate stop:** do not dispatch the workflow, push a tag, approve an environment, or publish a GitHub release.

---

## Original Candidate-Preparation Intent, Re-sequenced After Units A-C

### Task 4 / Unit D — Candidate 5.1.0a3 and Installer Authority Preparation

**Files:**
- Modify only for version identity: `launcher/pyproject.toml`
- Modify only for version identity: `launcher/src/neko_launcher/__init__.py`
- Modify: `installer/scripts/build_beta_installer.py`
- Create/modify focused version test: `launcher/tests/test_phase3_candidate_version.py`
- Create: `launcher/tests/test_build_beta_installer.py`
- Create packaged smoke harness: `launcher/tests/smoke/test_packaged_smoke_a3.py`
- Use existing: `launcher/NekoLauncher.spec`
- Use existing: `launcher/NekoUpdater.spec`
- Create candidate output outside repo: `E:\Github\artifacts\phase3\5.1.0a3-candidate\`
- Create Owner package outside repo: `E:\Github\Project manager\OWNER_GATE_2_PRODUCTION_PACKAGE.md`

**Prerequisite gate:**
- [ ] Confirm Units A-C focused/full suites are green, each blocker review is Critical=0/Important=0, and each has its tests-only then narrow production commit. If not, STOP before changing version declarations.

**Version and installer-authority contract:**
- Version bump is strictly `launcher/pyproject.toml` and `launcher/src/neko_launcher/__init__.py`, both to `5.1.0a3`.
- Derive repository root in `installer/scripts/build_beta_installer.py` from the resolved script location (`Path(__file__).resolve()...`) or a validated explicit build argument. Remove reliance on historical hardcoded `E:\Github\Neko-Family-Proxy`; reject repo roots lacking the expected installer source rather than falling back.
- Candidate installer authority requires explicit operator-controlled approved Launcher and Updater SHA-256 values (CLI arguments or an explicit external build config path). Validate canonical lowercase hex64 and compare them to staged binaries before compilation. Do not retain the historical Launcher hash as a default and do not silently infer approval from whatever file happens to be staged.
- Core authority remains an explicit unchecked Owner input/placeholder until Owner supplies the approved identity. Do not invent a Core commit, hash, manifest identity, production key, or capability. If the existing historical Core authority remains for old beta reproducibility, candidate mode must require an explicit new authority input and must fail closed when absent.
- Tests must prove execution from this worktree uses this worktree's `installer/beta.iss`; the historical hardcoded path cannot be selected; omitted/stale/wrong Launcher or Updater authority fails before ISCC; exact explicit matching hashes pass the precompile gates; no candidate build can inherit `APPROVED_LAUNCHER_SHA256` silently.

- [ ] **Step 1: Write tests only** in `launcher/tests/test_phase3_candidate_version.py`, `launcher/tests/test_build_beta_installer.py`, and `launcher/tests/smoke/test_packaged_smoke_a3.py`. Keep packaged smoke marked/skipped unless explicit candidate paths are supplied, but make its assertions executable: exact owned parent/child handles/PIDs, real visible top-level title containing `NEKO FAMILY PROXY`, version `5.1.0a3`, no unhandled dialog, no error log, normal bounded shutdown, no owned child left, and no candidate-created `_MEI` directory left. Never global-enumerate or global-kill same-name processes.
- [ ] **Step 2: Commit tests only.** `git add launcher/tests/test_phase3_candidate_version.py launcher/tests/test_build_beta_installer.py launcher/tests/smoke/test_packaged_smoke_a3.py && git commit -m "test: specify phase 3 a3 candidate authority"`
- [ ] **Step 3: Prove genuine RED before production edits.** Run `launcher\.venv\Scripts\python.exe -m pytest -q launcher/tests/test_phase3_candidate_version.py launcher/tests/test_build_beta_installer.py`; record assertion-level failures for a2 identity, historical repo path, and implicit stale hash authority.
- [ ] **Step 4: Implement the narrow version and installer changes** only in the three production files named above (`launcher/pyproject.toml`, `launcher/src/neko_launcher/__init__.py`, and `installer/scripts/build_beta_installer.py`). Do not touch installer payloads or production config.
- [ ] **Step 5: Prove focused GREEN and lint.** Run `launcher\.venv\Scripts\python.exe -m pytest -q launcher/tests/test_phase3_candidate_version.py launcher/tests/test_build_beta_installer.py`, then `launcher\.venv\Scripts\python.exe -m ruff check installer/scripts/build_beta_installer.py launcher/tests/test_phase3_candidate_version.py launcher/tests/test_build_beta_installer.py launcher/tests/smoke/test_packaged_smoke_a3.py`.
- [ ] **Step 6: Run full regression** using the global commands.
- [ ] **Step 7: Blocker review before packaging.** Require Critical=0 and Important=0 for exact version scope, safe path derivation, explicit hash authority, stale-value rejection, no invented Core identity, and no production inputs embedded in Git.
- [ ] **Step 8: Commit production only.** `git add launcher/pyproject.toml launcher/src/neko_launcher/__init__.py installer/scripts/build_beta_installer.py && git commit -m "release: prepare 5.1.0a3 candidate authority"`

**Build environment and candidate packaging:**

The current `launcher\.venv` uses the Python rooted at `E:\Github\tools\hermes-portable\python` with Tcl/Tk 8.6.12. This is local build-environment evidence only. Machine-global `TCL_LIBRARY`/`TK_LIBRARY` may point to incompatible Tcl/Tk 8.6.15. Never hardcode this machine path or these variables into shipped runtime, source defaults, specs, installer runtime, or workflow.

- [ ] **Step 9: Record environment evidence.** Run `launcher\.venv\Scripts\python.exe -c "import sys,tkinter; print(sys.executable); print(sys.base_prefix); print(tkinter.Tcl().eval('info patchlevel'))"` and record the actual Python root and Tcl patch level in the external candidate evidence.
- [ ] **Step 10: Create only the new output directory.** Ensure `E:\Github\artifacts\phase3\5.1.0a3-candidate` is empty/new; do not delete or overwrite `E:\Github\artifacts\phase2\5.1.0a2-candidate`.
- [ ] **Step 11: Build both standalone binaries with machine-scoped Tcl/Tk overrides.** In `cmd.exe` syntax, derive `<pyroot>` from Step 9 and run `set "TCL_LIBRARY=<pyroot>\tcl\tcl8.6" && set "TK_LIBRARY=<pyroot>\tcl\tk8.6" && launcher\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --distpath E:\Github\artifacts\phase3\5.1.0a3-candidate --workpath E:\Github\artifacts\phase3\5.1.0a3-candidate\build-launcher launcher\NekoLauncher.spec`, then the equivalent command for `launcher\NekoUpdater.spec` with a distinct `build-updater` workpath. If invoked from Git Bash, use `env TCL_LIBRARY="<pyroot>\\tcl\\tcl8.6" TK_LIBRARY="<pyroot>\\tcl\\tk8.6" ...` while passing Windows paths to native Python.
- [ ] **Step 12: Verify binaries and updater self-check.** Run `E:\Github\artifacts\phase3\5.1.0a3-candidate\NekoUpdater.exe --self-check`; require exit 0. Verify both expected EXEs exist and derive SHA-256/size from the files, not logs.
- [ ] **Step 13: Run genuine packaged GUI smoke.** Run `launcher\.venv\Scripts\python.exe -m pytest -q launcher/tests/smoke/test_packaged_smoke_a3.py --candidate-dir=E:\Github\artifacts\phase3\5.1.0a3-candidate` (add the narrowly scoped pytest option in that test/conftest only if required). Require a real visible `NEKO FAMILY PROXY` window, version `5.1.0a3`, no unhandled dialog, no error log, exact owned process lifecycle, and no leftovers. A process-start-only or mocked-window result is not acceptance.
- [ ] **Step 14: Record authoritative candidate evidence.** Record commands, Python/Tcl/Tk evidence, test/build summaries, exact SHA-256 and byte size for Launcher/Updater, and smoke outcome under the candidate output. Keep secrets and grant URLs absent.

**Owner Gate #2 package outside the repository:**

- [ ] **Step 15: Create `E:\Github\Project manager\OWNER_GATE_2_PRODUCTION_PACKAGE.md`.** Include:
  - exact candidate Launcher/Updater/installer hashes and byte sizes only after those files exist;
  - explicit unchecked Owner fields for approved Core source identity, Core artifact hash/size, Core installed-identity hash, and immutable object identity—placeholders only, never invented values;
  - exact production public-key provisioning patch location (`launcher/src/neko_launcher/updater/trust.py`, or the reviewed replacement location) and an unchecked Owner approval field;
  - offline v2 signing command procedure using `scripts/build_software_release_v2.py`, private-key file path supplied by Owner at execution time, separately supplied public-key file, explicit input/output/artifact paths, and no example private key bytes;
  - capability provisioning schema/process from §14.1, including Credential Manager target and canonical base64url32 format, but no capability and no capability digest;
  - immutable upload-map template for Launcher/Core artifact IDs, hashes, sizes, formats/distributions, private Core object/version, and grant expiry constraints; all production values unchecked;
  - ordered checklist: approve identities → provision public key → privately stage immutable Core and deny anonymous access → configure scoped capability registry → offline sign → upload immutable envelope/artifacts → verify grants/storage → deploy Admin enforcement → activate release → bootstrap capability → Gate3 tests;
  - rollback order and revoke order, including stopping activation, revoking capability scope/new grants, retaining old complete generation, and restoring prior signed active release under Owner authorization;
  - explicit unchecked Owner authorization fields for production key custody, public key, capability provisioning, Core identity, immutable upload, Admin deploy, active release, publication/tag, rollback/revoke, and Gate3 execution.
- [ ] **Step 16: Package review.** Require Critical=0 and Important=0, exact candidate metadata, no secret/capability/digest/private-key content, no claimed Core authority, no checked Owner field, and no production action performed.
- [ ] **Step 17: Do not commit the Owner package.** It is deliberately outside the repository at `E:\Github\Project manager` and is handed to the Owner as authorization material only.

---

## Subsequent Cross-Repository Admin Readiness Unit (not part of A-D)

After this repository's Units A-D are accepted, conduct a separate cross-repository Admin readiness unit. First perform read-only discovery against the actual Admin repository and §14.1 contract; only then write a separately approved implementation plan for protected capability registry, constant-time digest comparison, trusted active-release component classification, private-storage signed grants, anonymous-origin denial, bounded safe errors, revocation, and provider tests. Do not invent Admin paths, filenames, environment names, provider details, migrations, or deployment commands in this repository plan. No Admin production deploy/configuration is authorized here.

---

## Final STOP — Owner Gate #2

- [ ] Confirm local status is only `ENGINEERING_PASS / READY_FOR_OWNER_AUTHORIZATION`.
- [ ] STOP pending Owner-supplied and Owner-approved production Ed25519 key/public-key provisioning, distribution capability provisioning, canonical Core identity/artifact authority, immutable production upload map, Admin enforcement deployment, active-release activation, tag/publication authorization, and rollback/revoke authorization.
- [ ] Do not sign, deploy, upload, activate, provision, tag, publish, or represent Gate #2/Gate #3 as passed.

Historical note: the original stale plan used `build\venv-5.1\Scripts\python.exe`, proposed creating `launcher/NekoUpdater.spec`, and sequenced the version bump before release blockers. `launcher\.venv` and the existing updater spec are now authoritative; the original candidate-bump/package/Gate #2 intent is preserved above but correctly gated after Units A-C.
