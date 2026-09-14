# v5.1.2 Runtime Trust & Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every behavior change follows `superpowers:test-driven-development`; each task ends in an independent `ag/gemini-pro-agent` review with Critical 0 / Important 0.

**Goal:** Make packaged v5.1.2 discover machine updates from the dedicated Updates channel, derive its local authority only from authenticated durable updater state, enroll the baseline offline from the exact embedded signed envelope, enforce correct ordering/mandatory/offline semantics, and fix the real Core post-install verifier blocker.

**Architecture:** Use one signed declarative `update-trust-profile-v1` resource as the only packaged carrier of machine channel routing and release-verification keys. `NekoUpdater.exe` embeds only the common Profile Authority public root, never production/proof release keys; it loads the profile from one fixed install-root path, verifies the profile signature/canonical schema, and then uses only that verified profile keyset. Production and proof packages differ only in the signed profile resource/profile identifier/endpoint as permitted by Spec 3.4, while the baseline `NekoUpdater.exe` bytes remain identical. Fresh enrollment pins exact `profile_id`, profile-envelope SHA-256, and `keyset_sha256` in the existing enrollment marker contract before signed baseline state is committed; runtime exposes no CLI/env/config/path selector that can replace the enrolled profile. Preserve exact committed, high-water, observed/admitted, and failed release bindings separately; authentication/admission durably advances `highwater` + `observed` before artifact transfer, and transport failures remain non-bricking for a valid committed install.

**Tech Stack:** Python 3.11+, pytest, Ruff, existing Ed25519 `release-v2` verifier/state machine, PowerShell 5.1, Inno Setup/PyInstaller integration tests.

**Spec:** `docs/superpowers/specs/2026-09-13-neko-family-5-1-2-baseline-forced-update-revision-3-4.md`

**Master plan:** `docs/superpowers/plans/2026-09-13-neko-family-5-1-2-baseline-release-implementation.md`

## Global Constraints

- Production machine repository: `Valeneko-pranmong/Neko-Family-Proxy-Updates`.
- Human repository is not a machine-update discovery endpoint.
- No user/runtime switch may change production trust to proof trust.
- `NekoUpdater.exe` and normal Launcher runtime must never embed production/proof release public-key registries directly after RT1; packaged runtime release keys come only from one successfully verified fixed-path signed trust profile.
- The common Profile Authority public root is identical in proof/production binaries and is distinct from both production and proof release-signing authorities. Its private key is controller custody only and never enters a worktree, Hermes worker, test artifact, argv, environment, or repository.
- The installed trust profile path is fixed at `<install_root>\\trust\\update-profile-v1.json`; no packaged CLI/env/registry/user-config/profile-path override or fallback is permitted.
- Fresh enrollment pins exact `profile_id`, exact canonical profile-envelope SHA-256, and exact canonical release-keyset SHA-256 in `EnrollmentMarker`; normal runtime has no supported transition that changes those values in place. A different signed profile requires a separately built package/fresh enrollment, not a runtime switch.
- Production local sequence/release_id must never be synthesized from `__version__` or unsigned compile-time constants.
- Mandatory formula uses **committed runtime sequence**, not high-water.
- High-water preserves the full highest authenticated binding `(sequence, release_id, payload_sha256)`, not only the integer sequence.
- `observed` preserves the exact admitted/authenticated binding associated with high-water; `failed` alone decides whether that exact high-water authority is terminally suppressed. An observed high-water authority that is not failed remains retryable.
- Active game/session is never force-terminated to satisfy a mandatory update.
- A discovery outage does not invalidate an already valid committed runtime.
- Final baseline enrollment uses the exact signed envelope and exact installed Launcher/Updater/Core identities and works without network access.
- No task here performs production signing or public GitHub mutation.

---

## Task RT0 / K1: Freeze the Signed Trust-Profile Architecture — Plan Gate

**Purpose:** Close the proof-key/byte-identical-helper architecture before execution. RT0/K1 is now a **plan/controller architecture contract**, not an impossible pre-implementation PASS test against the current hard-coded source. No production source is changed, no Hermes implementation worker is started, and no private authority material is created or exposed during plan review.

**Current source fact that motivates the selected design:** `launcher/src/neko_launcher/updater/main.py` currently imports `PRODUCTION_RELEASE_PUBLIC_KEYS` and passes that registry into packaged `--session`; `run_session(...)` itself accepts explicit keys. The current packaged helper therefore cannot satisfy separate proof release keys plus byte-identical proof/production helper bytes. Existing enrollment already provides a useful pinning primitive: `EnrollmentMarker.keyset_sha256` is strict/fail-closed and `load_enrollment(...)` rejects a mismatched expected keyset.

**Selected architecture — signed declarative profile carrier:**

```text
common code / same NekoUpdater.exe bytes
    embeds only PROFILE_AUTHORITY_PUBLIC_KEYS
             |
             v
fixed <install_root>\trust\update-profile-v1.json
    canonical closed-schema profile envelope
    signed by dedicated Profile Authority private key
    payload = profile_id + channel + owner/repository + exact release public-key registry
             |
             +--> production profile contains production release key(s) only
             +--> proof profile contains proof release key(s) only

fresh enrollment pins:
    profile_id
    profile_envelope_sha256
    keyset_sha256

runtime:
    fixed path -> verify profile signature -> require enrollment pins -> use verified release keys
    NO CLI/env/registry/config/path override and NO fallback registry
```

The Profile Authority is a **third authority domain**, distinct from production release signing and proof release signing. Its public root is identical in proof/production code. Its private key is controller custody only. A worker may receive the public root and pre-signed profile envelope bytes, never the Profile Authority private key and never the production release private key.

**Required invariants:**

```text
A. proof release authority/key is separate from production release authority/key
B. packaged production Updater contains neither proof release key nor a proof fallback registry
C. baseline NekoUpdater.exe used by proof is byte-for-byte identical to production-candidate NekoUpdater.exe
D. no user-controlled CLI/env/registry/config/profile-path/runtime switch can change enrolled trust
E. the same packaged helper implementation can authenticate/apply a proof-signed N+1 release when installed with the separately signed proof profile
F. arbitrary unsigned/self-signed profile bytes are rejected before any release envelope/state evidence is trusted
G. profile_id/profile SHA/keyset SHA are immutable for one enrollment; profile replacement is fail-closed, not an in-place profile transition
```

**Execution-time K1A authority bootstrap (not performed by plan approval):** after explicit Owner execution approval + K0, and before the first RT1 production-code edit, the controller establishes/read-backs two non-production authority domains only. (1) **Profile Authority** public custody at `E:\Github\authority\v512-update-profile-authority\public-v1.json`, planned `key_id=neko-update-profile-v512-1`; (2) **Proof Release Authority** public custody at `E:\Github\authority\v512-proof-release-authority\public-v1.json`, planned `key_id=neko-update-proof-v512-1`. Each public-custody file is exact canonical UTF-8 JSON plus one LF with closed fields `{schema_version,key_id,public_key_hex,public_key_sha256}`: `schema_version=1`; `key_id` matches `[A-Za-z0-9._-]{1,64}`; `public_key_hex` is exactly 64 lowercase hex characters for one 32-byte Ed25519 public key; and `public_key_sha256 = sha256(bytes.fromhex(public_key_hex)).hexdigest()`. Read-back requires byte-canonical form, exact field set, key-id expectation, recomputed public-key SHA, and records the SHA-256 of the exact custody file bytes. Both corresponding private keys remain outside repo/worktree/Hermes and are usable only by controller-owned signers. K1A cross-verifies the existing production release public key `neko-update-prod-1` against authenticated historical production evidence and never accesses the production private key. **K1A does not create or sign trust-profile or release envelopes**, because the canonical profile codec/shared release assembler are RT1 deliverables. Exact profile sealing and proof-envelope sealing are deferred to K1B-A/K1B-B after a clean committed `RT1_CODE_HEAD`. K1A performs no release signing, sequence reservation, GitHub mutation, or release publication. Missing/malformed/mismatched Profile Authority public custody is `PROFILE_AUTHORITY_INPUT_MISSING`; missing/malformed/mismatched Proof Release Authority public custody is `PROOF_AUTHORITY_INPUT_MISSING`; either blocks RT1.

**Plan-gate verdict:** this selected architecture closes the former K1 design ambiguity. Final plan review must still verify every downstream RT/RA/master reference uses this one carrier. The first executable trust task is RT1; **RT2+, RA1+, and RH1+ remain blocked until exact `RT1_CODE_HEAD` packaged conformance evidence is independently reviewed `UPDATER_TRUST_FEASIBLE / C0_I0`, canonical `docs/superpowers/evidence/v512-k1-acceptance.json` is sealed in immutable `K1_ACCEPTANCE_COMMIT` on the integration branch, the Git-only **RT1 security-tool immutability guard** defined below passes, and only then `scripts/verify_v512_k1_acceptance.py --require-git-immutability` passes for the exact accepted `K1B_CUSTODY_SHA256`.**

---

## Task RT1: Implement Signed Immutable Update Trust Profile + K1 Conformance

**Dependencies:** Owner execution approval, K0 baseline acceptance, RT0/K1 architecture contract above, and completed K1A Profile Authority + Proof Release Authority public-custody bootstrap. Exact signed production/proof profiles are **not** a pre-implementation dependency. RT1 first implements/tests both detached assemblers and runtime trust code, commits a clean `RT1_CODE_HEAD`, then K1B-A seals profiles, the conformance harness builds/measures exact package + proof-candidate fixture bytes, and K1B-B seals proof release envelopes from those measured identities before packaged conformance/review. RT1 is the only implementation task allowed before final K1 acceptance; RT2+/RA1+/RH1+ wait for reviewed `UPDATER_TRUST_FEASIBLE / C0_I0`, immutable canonical `v512-k1-acceptance.json` in `K1_ACCEPTANCE_COMMIT`, the Git-only **RT1 security-tool immutability guard** defined below, **and then** a fresh `verify_v512_k1_acceptance.py --require-git-immutability` PASS for the exact accepted custody chain.

**Files:**
- Modify: `launcher/src/neko_launcher/updater/trust.py` — retain only the common Profile Authority public-root registry for packaged trust bootstrap; remove direct packaged production release-key authority from `main.py` use.
- Create: `launcher/src/neko_launcher/updater/trust_profile.py` — canonical profile-envelope schema, signature verification, keyset digest, fixed-path loader.
- Create: `scripts/build_update_trust_profile.py` — deterministic unsigned profile-spec canonicalizer + detached-signature profile-envelope assembler/verifier; it has no private-key loader/input and is never packaged into Launcher/Updater.
- Create: `scripts/assemble_release_v2_envelope.py` — generic detached-signature `release-v2` envelope assembler/verifier over the existing canonical payload + `verify_release_envelope_v2` contract; no private-key loader/input and never packaged.
- Create: `scripts/verify_v512_k1_acceptance.py` — closed-schema verifier for K1 acceptance JSON, exact evidence/custody digests, and immutable single-introduction Git history; read-only, no signer/private-key inputs.
- Modify: `launcher/src/neko_launcher/updater/main.py` — packaged `--session` resolves release keys only from the fixed verified installed profile and enrollment pin; no trust/profile arguments.
- Modify: `launcher/src/neko_launcher/updater/state_models.py` — extend pre-release `EnrollmentMarker` schema with immutable `profile_id` and `profile_envelope_sha256` while retaining `keyset_sha256`.
- Modify: `launcher/src/neko_launcher/updater/enrollment.py` — create/read/validate the profile pins and expose a read-only trust-binding validation primitive used by packaged helper startup.
- Create: `launcher/src/neko_launcher/infrastructure/update_channel_profile.py` — immutable routing projection from `VerifiedUpdateTrustProfile`; no compiled production release-key constant.
- Modify: `launcher/src/neko_launcher/infrastructure/github_release.py`, `github_asset_downloader.py`, `github_release_binding.py` to consume that verified routing profile.
- Create: `launcher/tests/test_update_trust_profile.py`
- Create: `launcher/tests/test_build_update_trust_profile.py`
- Create: `launcher/tests/test_assemble_release_v2_envelope.py`
- Create: `launcher/tests/test_verify_v512_k1_acceptance.py`
- Create: `launcher/tests/test_updater_trust_feasibility.py`
- Create: `launcher/tests/test_update_channel_profile.py`
- Modify: `launcher/tests/updater/test_enrollment.py`, `test_updater_main.py`, `launcher/tests/test_github_release.py`, `test_github_asset_downloader.py`, `test_github_release_binding.py`
- Create after GREEN: `docs/superpowers/evidence/v512-updater-trust-feasibility.md`
- Controller creates only after reviewed C0/I0: `docs/superpowers/evidence/v512-k1-acceptance.json`

**Profile envelope v1 byte contract:** the persisted file bytes are exactly `canonical_json_dumps(envelope_obj) + b"\n"`; there is exactly one terminal LF and no BOM, CRLF, leading/trailing whitespace, or second newline. `envelope_obj` has exactly `{schema_version, key_id, payload, signature_b64}` with `schema_version == 1` and `key_id` matching `[A-Za-z0-9._-]{1,64}`. `payload` has exactly `{profile_id, channel, owner, repository, release_keys}`. `release_keys` is a non-empty list sorted strictly by unique `key_id`; each item has exactly `{key_id, public_key_hex}`, where `key_id` follows the same pattern and `public_key_hex` is exactly 64 lowercase hex characters encoding one 32-byte Ed25519 public key. The bytes signed by Profile Authority are exactly `payload_bytes = canonical_json_dumps(payload)` with **no terminal LF**. `signature_b64` is strict canonical RFC 4648 base64 for exactly one 64-byte Ed25519 signature over those exact `payload_bytes`; decode→re-encode must reproduce the field byte-for-byte. `verify_update_trust_profile(raw)` first requires exactly one final LF, requires `canonical_json_loads(raw[:-1])` to round-trip to the exact body bytes, reconstructs `payload_bytes` from the parsed payload, verifies the detached signature under the selected Profile Authority root, and rejects all duplicate/unknown/non-canonical fields or encodings. `profile_payload_sha256 = sha256(payload_bytes)` and has no LF. `profile_envelope_sha256 = sha256(raw)` therefore includes the terminal LF. `keyset_sha256 = sha256(canonical_json_dumps({"release_keys": release_keys}))` and has no LF. Production payload is fixed to `profile_id="production"`, `channel="stable"`, owner `Valeneko-pranmong`, repository `Neko-Family-Proxy-Updates`, and contains only the authenticated approved production release public registry. The isolated proof payload is fixed to `profile_id="proof-v512"`, `channel="stable"`, owner `Valeneko-pranmong`, repository `Neko-Family-Proxy-Updates-Proof`, and contains only the K1A Proof Release Authority public registry. The proof repository identity is a declarative harness endpoint; K1/RA proof transport may intercept/emulate it locally and no public repository creation is implied or authorized. For Spec §9, the **separate proof channel** is this isolated routing/trust domain (`proof-v512` + proof repository endpoint + Proof Release Authority), while the ReleaseSetV2 protocol track intentionally remains `channel="stable"` so proof exercises the same stable-channel runtime codepath instead of introducing a hidden proof-only channel switch.

**Interfaces:**

```python
@dataclass(frozen=True)
class VerifiedUpdateTrustProfile:
    profile_id: str
    channel: str
    owner: str
    repository: str
    release_public_keys: Mapping[str, bytes]
    keyset_sha256: str
    profile_envelope_sha256: str
    profile_authority_key_id: str
    profile_authority_public_key_sha256: str


def verify_update_trust_profile(
    raw: bytes,
    *,
    profile_authority_public_keys: Mapping[str, bytes],
) -> VerifiedUpdateTrustProfile: ...


def load_installed_update_trust_profile(install_root: Path) -> VerifiedUpdateTrustProfile:
    # packaged runtime uses only install_root / "trust" / "update-profile-v1.json"
    # and compiled PROFILE_AUTHORITY_PUBLIC_KEYS; no caller-selected path/root keys
    ...
```

`UpdateChannelProfile.from_verified(profile)` copies/freeze-maps `release_public_keys` and derives `latest_release_api` / `browser_download_prefix` from the verified owner/repository. Packaged production composition never constructs a raw profile from user/test dictionaries.

**Controller profile-sealing boundary:** `scripts/build_update_trust_profile.py` defines a closed `UpdateTrustProfileSpec(profile_id, channel, owner, repository, release_keys)` plus `canonicalize_profile_payload(spec) -> bytes` and `assemble_verified_profile_envelope(*, payload_bytes: bytes, profile_authority_key_id: str, detached_signature: bytes, profile_authority_public_keys: Mapping[str, bytes]) -> bytes`. `canonicalize_profile_payload(...)` returns exactly the canonical payload bytes defined above with no LF. The assembler requires a 64-byte detached signature over those exact bytes, verifies it against the exact selected Profile Authority public key, constructs `signature_b64` using canonical RFC 4648 base64, serializes the closed envelope as canonical JSON plus exactly one LF, computes/observes the resulting exact-file SHA, then re-parses the same returned bytes through `verify_update_trust_profile` and requires payload/profile/keyset/root identities to match before success. It never accepts a prebuilt envelope body or alternate newline/encoding mode. It has **no** private-key path/value/env/registry argument and never invokes a signer. Unit tests use ephemeral keys only to produce detached test signatures; real K1B-A profile signatures come from the controller-held Profile Authority.

**Controller proof-release envelope boundary:** `scripts/assemble_release_v2_envelope.py` reuses `canonical_json_dumps`, `canonical_json_loads`, `parse_release_v2`, and `verify_release_envelope_v2`. It defines `canonicalize_release_v2_payload(document: object) -> bytes` and `assemble_verified_release_v2_envelope(*, payload_bytes: bytes, key_id: str, detached_signature: bytes, release_public_keys: Mapping[str, bytes]) -> bytes`. It first requires the payload bytes to round-trip as exact canonical ReleaseSetV2, then builds the existing `{envelope_version,key_id,payload_b64,signature_b64}` schema, serializes it using the existing sorted compact UTF-8 JSON + trailing LF file contract, parses it back, and requires `verify_release_envelope_v2(...)` to return the same payload SHA/binding before success. It has no signer/private-key input/path/env/registry and never invokes `scripts/sign_software_release.py`. K1B-B's Proof Release Authority signer signs the exact canonical payload out-of-process and supplies only `(key_id, detached_signature)` to this assembler. RA4 later reuses the same assembler for production signing so proof and production cannot drift to different envelope construction logic.

**K1 acceptance-record contract:** `docs/superpowers/evidence/v512-k1-acceptance.json` is canonical UTF-8 JSON + one LF with exact closed fields `schema_version=1`, `task_id="RT1-K1"`, `rt1_code_head_sha`, `profile_authority_custody_sha256`, `proof_release_authority_custody_sha256`, `k1b_custody_path`, `k1b_custody_sha256`, `evidence_path`, `evidence_sha256`, `reviewer_model="ag/gemini-pro-agent"`, `critical_count=0`, `important_count=0`, `reviewed_at`. All SHA fields are lowercase hex64 except `rt1_code_head_sha`, which is the exact lowercase Git object id recorded at Step 8. `reviewed_at` is RFC3339 UTC with `Z`. `scripts/verify_v512_k1_acceptance.py` validates canonical bytes/schema, exact evidence and external-custody hashes, re-validates `k1b-custody-v1.json` closed schema, and independently re-hashes **every referenced profile, proof envelope, and baseline/candidate Launcher/Updater/Core artifact file**. It loads/revalidates both K1A public-authority records first. It then runs `verify_update_trust_profile()` on exact K1B-A profile bytes using only the K1A Profile Authority public root, requires each recorded profile payload/envelope/keyset SHA to recompute exactly, requires production routing exactly `production/stable/Valeneko-pranmong/Neko-Family-Proxy-Updates` with release registry exactly equal authenticated `neko-update-prod-1`, and proof routing exactly `proof-v512/stable/Valeneko-pranmong/Neko-Family-Proxy-Updates-Proof` with release registry exactly equal K1A Proof Release Authority public custody. It parses each K1B-B proof `release-v2.json`, calls `verify_release_envelope_v2(document, verified_proof_profile.release_public_keys)`, requires verified `key_id` == K1A Proof Release Authority key id, recomputed payload/envelope hashes, exact `schema_version=2` / `channel="stable"` / updater protocol `1..1`, exact baseline seq1/id/minimum/mandatory + all-component `version="5.1.2"` contract, exact candidate seq2/id/minimum/mandatory + launcher/core `5.1.3-proof` + unchanged-updater `5.1.2` contract, canonical artifact IDs/formats, and exact signed components == recorded artifact component objects. Neither proof envelope may verify under the production profile registry. For Launcher/Updater it requires artifact SHA == installed identity SHA. For Core it creates a fresh verifier-owned temporary directory and calls the **same production extraction primitive used by `generation_builder`**, `neko_launcher.updater.zip_extractor.extract_core_bundle(custodied_zip, extracted_core_root)`, so path/duplicate/link/size/expansion checks are not reimplemented in the acceptance tool; it then calls `neko_launcher.updater.core_manifest_verifier.verify_canonical_core_bundle(extracted_core_root)`. Acceptance requires extraction success, `result.valid is True`, and signed/recorded `installed_identity_sha256 == result.manifest_sha256 == sha256((extracted_core_root / "core-manifest.json").read_bytes()).hexdigest()`. It also requires exact ZIP artifact SHA/size and cross-checks every artifact record against the corresponding signed proof ReleaseSetV2 component before accepting the custody manifest. When `--require-git-immutability` is supplied it additionally requires the tracked acceptance record to have exactly one introduction commit and no later modification; that introduction commit is `K1_ACCEPTANCE_COMMIT` and must be an ancestor of current HEAD. The verifier never treats a freshly computed current digest as authority: expected digests come only from the tracked acceptance record.

**RT1 security-tool immutability guard:** after `K1_ACCEPTANCE_COMMIT` is sealed, the following closed path set is immutable relative to accepted `RT1_CODE_HEAD`: `scripts/build_update_trust_profile.py`, `scripts/assemble_release_v2_envelope.py`, `scripts/verify_v512_k1_acceptance.py`, `launcher/src/neko_launcher/updater/trust.py`, and `launcher/src/neko_launcher/updater/trust_profile.py`. These paths are owned by RT1/K1 only; any later need to change one reopens RT1, creates a new `RT1_CODE_HEAD`, regenerates K1B-A/K1B-B custody/evidence, and requires a new independent K1 review + acceptance commit. The guard never assumes symbolic names such as `RT1_CODE_HEAD` or `K1_ACCEPTANCE_COMMIT` are Git refs. Instead it independently resolves the **single** acceptance-record introduction commit from Git history, reads `rt1_code_head_sha` from the acceptance JSON blob stored in that exact commit (not from the working-tree copy), requires the current acceptance-record bytes to equal the committed bytes, requires that resolved RT1 commit to be an ancestor of `HEAD`, requires **zero commits after it** to have touched any closed RT1 security path, and requires the current index/worktree bytes for those paths to equal that accepted RT1 commit. This catches both current drift and modify-then-revert history. Before **every downstream use** of the current-path K1 verifier, profile builder, shared release assembler, or accepted Profile Authority/profile-codec implementation, run this exact repo-root command:

```cmd
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
```

Only after this Git-only guard prints `RT1_SECURITY_TOOL_GUARD_OK` may the controller invoke `scripts/verify_v512_k1_acceptance.py` or either detached assembler. Any failure is `RT1_SECURITY_TOOL_DRIFT`; do not run the current-path verifier/assembler as authority and do not waive the failure with passing tests/lint.

**Enrollment binding:** `EnrollmentMarker` carries `profile_id`, `profile_envelope_sha256`, and `keyset_sha256`. RT1 adds a read-only `validate_enrollment_trust_binding(...)` primitive that reads the existing fixed marker under the existing trusted-leaf/root checks and requires exact helper/root/profile/keyset binding before `SlotStore` trusts state evidence. There is no API that mutates these fields after enrollment; mismatch returns fail-closed `UNKNOWN_KEY`/`PROTOCOL_INVALID` as assigned by tests. Existing bootstrap payload/state transition semantics are not changed in RT1.

- [ ] **Step 1: Write trust-profile + both detached-assembler + K1-acceptance-verifier RED tests first.** Add `test_verify_v512_k1_acceptance.py` cases for exact acceptance schema/canonical LF bytes, evidence/custody digest mismatch, malformed nested K1B-B custody manifest, missing or mutated referenced profile/proof-envelope/**artifact** custody, bad profile signature/root/routing/keyset or profile payload/envelope/keyset SHA mismatch, bad proof-envelope signature/key/cross-trust/schema/channel/updater-protocol/seq-id-mandatory/component-version-id-format contract, artifact path/hash/size/installed-identity mismatch, `extract_core_bundle()` rejection (including traversal/duplicate/link/limit violations) or `verify_canonical_core_bundle()` failure/manifest-SHA mismatch, signed-component-vs-artifact-record mismatch, candidate Updater divergence from baseline, wrong `rt1_code_head_sha`, mutable/multiple-introduction acceptance history in a temporary Git repo, and one immutable introduction whose commit is an ancestor of current HEAD. The verifier must expose no signer/private-key inputs.

- [ ] **Step 1a: Write trust-profile + both detached-assembler RED cases.** Profile cases cover canonical happy path with a test Profile Authority key; exact returned `profile_authority_key_id` + `profile_authority_public_key_sha256`; byte-stable `payload_bytes` with no LF; exact envelope body + one terminal LF; exact `profile_envelope_sha256` including that LF; deterministic `keyset_sha256` without LF; strict 64-byte signature + canonical base64; and successful decode→re-encode equality. Negative cases reject missing LF, CRLF, double LF, BOM, surrounding whitespace, non-canonical JSON, duplicate/unknown fields, field-name `signature` instead of `signature_b64`, non-canonical/invalid base64, wrong signature length, bad root signature, wrong detached signature, unknown profile-root `key_id`, duplicate/unsorted release keys, duplicate release `key_id`, uppercase/non-hex/wrong-length public keys, empty keyset, production profile containing a proof key, and source-dictionary mutation. Release-envelope cases require canonical ReleaseSetV2 payload validation, exact detached-signature assembly, same payload SHA/binding through `verify_release_envelope_v2`, rejection of malformed/non-canonical payload/wrong key/wrong signature, and byte-stable sorted compact JSON + LF output. Inspect both builder CLIs/APIs and assert neither exposes private-key input/path/env/registry or invokes a signer.

- [ ] **Step 2: Write packaged-helper RED tests before production changes.** Assert current `main.py --session` still imports/uses `PRODUCTION_RELEASE_PUBLIC_KEYS` and therefore fails the new contract. New tests require one fixed profile path, root-signature verification before `SlotStore`, exact enrollment pin match, no argv/env/registry/profile-path override, and zero fallback to a compiled production/proof release registry.

- [ ] **Step 3: Write enrollment-pin RED tests.** Construct a valid marker/profile pair, then independently change profile id, profile envelope bytes, release keyset, helper SHA, or install-root identity and require fail-closed trust-binding validation before state evidence is selected. Exact rerun is read-only/idempotent. Add a test proving no public runtime API can rewrite the profile pins in an enrolled marker.

- [ ] **Step 4: Run the complete trust RED set.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_update_trust_profile.py tests/test_build_update_trust_profile.py tests/test_assemble_release_v2_envelope.py tests/test_verify_v512_k1_acceptance.py tests/test_updater_trust_feasibility.py tests/updater/test_enrollment.py tests/updater/test_updater_main.py -q
```

Expected RED: signed profile loader/pins do not exist and packaged `--session` still uses the compiled production release registry.

- [ ] **Step 5: Implement only the profile verifier/fixed-path loader, public Profile Authority root binding, detached-signature profile builder/assembler, detached `release-v2` assembler, read-only K1 acceptance verifier, enrollment pins, and packaged helper startup trust resolution required by Steps 1–3.** Test-only pure verifier/builder injection may accept test public registries/signatures; packaged `load_installed_update_trust_profile()` and `main --session` may not. Both assemblers accept only already-produced detached signature bytes plus public verification keys—never private key bytes/path/env/registry. The release assembler must call the existing `parse_release_v2`/`verify_release_envelope_v2` contract rather than duplicating signature/schema logic. `verify_v512_k1_acceptance.py` may read only the named acceptance/evidence/custody files plus Git history and exposes no mutation/signer/private-key path. Do not add a profile selection argument, environment variable, registry lookup, alternate path, unsigned fallback, or proof key to production code.

- [ ] **Step 6: Write routing RED tests, then refactor machine discovery/downloader/resolver to `UpdateChannelProfile.from_verified(...)`.** Proof tests construct a **verified test profile**, not a raw runtime switch. Preserve `UPDATER_INCOMPATIBLE`: installed `NekoUpdater.exe` SHA must still equal the signed updater component before staging.

- [ ] **Step 7: Run implementation GREEN before any real profile sealing.** This proves the canonical codec/verifier/builders with ephemeral test signatures while K1A real private authorities remain untouched by workers.

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_update_trust_profile.py tests/test_build_update_trust_profile.py tests/test_assemble_release_v2_envelope.py tests/test_verify_v512_k1_acceptance.py tests/test_updater_trust_feasibility.py tests/test_update_channel_profile.py tests/updater/test_enrollment.py tests/updater/test_updater_main.py tests/test_github_release.py tests/test_github_asset_downloader.py tests/test_github_release_binding.py -q
.venv\Scripts\ruff.exe check ../scripts/build_update_trust_profile.py ../scripts/assemble_release_v2_envelope.py ../scripts/verify_v512_k1_acceptance.py src/neko_launcher/updater/trust.py src/neko_launcher/updater/trust_profile.py src/neko_launcher/updater/main.py src/neko_launcher/updater/state_models.py src/neko_launcher/updater/enrollment.py src/neko_launcher/infrastructure/update_channel_profile.py src/neko_launcher/infrastructure/github_release.py src/neko_launcher/infrastructure/github_asset_downloader.py src/neko_launcher/infrastructure/github_release_binding.py tests/test_update_trust_profile.py tests/test_build_update_trust_profile.py tests/test_assemble_release_v2_envelope.py tests/test_verify_v512_k1_acceptance.py tests/test_updater_trust_feasibility.py tests/test_update_channel_profile.py tests/updater/test_enrollment.py tests/updater/test_updater_main.py tests/test_github_release.py tests/test_github_asset_downloader.py tests/test_github_release_binding.py
cd ..
git diff --check
```

- [ ] **Step 8: Commit the RT1 implementation/tests before real authority sealing and record `RT1_CODE_HEAD`.** Commit code/tests only—no K1 evidence file yet. Require clean tracked worktree after the commit; K1B-A, Step 10 fixture measurement, K1B-B, and packaged conformance must all run from this exact immutable code HEAD.

```cmd
git add scripts/build_update_trust_profile.py scripts/assemble_release_v2_envelope.py scripts/verify_v512_k1_acceptance.py launcher/src/neko_launcher/updater/trust.py launcher/src/neko_launcher/updater/trust_profile.py launcher/src/neko_launcher/updater/main.py launcher/src/neko_launcher/updater/state_models.py launcher/src/neko_launcher/updater/enrollment.py launcher/src/neko_launcher/infrastructure/update_channel_profile.py launcher/src/neko_launcher/infrastructure/github_release.py launcher/src/neko_launcher/infrastructure/github_asset_downloader.py launcher/src/neko_launcher/infrastructure/github_release_binding.py launcher/tests/test_update_trust_profile.py launcher/tests/test_build_update_trust_profile.py launcher/tests/test_assemble_release_v2_envelope.py launcher/tests/test_verify_v512_k1_acceptance.py launcher/tests/test_updater_trust_feasibility.py launcher/tests/test_update_channel_profile.py launcher/tests/updater/test_enrollment.py launcher/tests/updater/test_updater_main.py launcher/tests/test_github_release.py launcher/tests/test_github_asset_downloader.py launcher/tests/test_github_release_binding.py
git commit -m "feat: bind updates to signed trust profiles"
git rev-parse HEAD
git status --short
```

- [ ] **Step 9 — K1B-A controller-only exact profile sealing from `RT1_CODE_HEAD`:** only after Step 8 has a clean committed code HEAD, require `git rev-parse HEAD == RT1_CODE_HEAD` and no tracked source delta. The controller uses that exact `scripts/build_update_trust_profile.py` to emit canonical payload bytes for production and proof specs. Production contains only authenticated `neko-update-prod-1` public registry; proof contains only exact K1A Proof Release Authority public custody. The controller-held Profile Authority signer signs those exact payload bytes out-of-process; the builder receives only detached signatures + public keys, assembles/verifies exact byte-contract envelopes, and the controller atomically writes/fsyncs/read-backs them at `E:\Github\artifacts\v512-update-trust-profiles\production\update-profile-v1.json` and `E:\Github\artifacts\v512-update-trust-profiles\proof\update-profile-v1.json`. Require exact K1A Profile Authority key/root identity, exact profile payload/envelope SHA, exact keyset SHA, and designated release registry after read-back. **K1B-A does not create a proof release envelope yet.** Missing/signature/custody/readback/source-HEAD mismatch is `K1B_PROFILE_SEALING_BLOCKED` and keeps RT2+/RA1+/RH1+ blocked.

- [ ] **Step 10 — Build/measure exact K1 conformance package trees and deterministic N+1 fixture before release signing.** From clean `RT1_CODE_HEAD`, build production-equivalent and proof-equivalent **baseline** package trees with the K1B-A profiles external at the fixed installed path. Mechanical diff permits only the signed trust-profile resource/profile id/endpoint; require byte-identical baseline `NekoUpdater.exe` and identical non-allowlisted code/module/resource inventory. Copy the exact proof-baseline `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip` bytes into controller custody under `E:\Github\artifacts\v512-k1-proof-fixtures\baseline\` and read back hashes/sizes/installed identities. In `launcher/tests/test_updater_trust_feasibility.py`, the RED/GREEN harness also owns a deterministic proof-only candidate fixture used only for K1 trust feasibility: candidate updater bytes are the exact baseline `NekoUpdater.exe`; component metadata is fixed as follows: baseline launcher/updater/core each `version="5.1.2"`, candidate launcher/core `version="5.1.3-proof"`, candidate updater `version="5.1.2"`; artifact IDs are exactly `NekoLauncher.exe` / `NekoUpdater.exe` / `NekoProxyCore.zip`; artifact formats are exactly `raw-pe-v1` / `raw-pe-v1` / `zip-core-v1`. Candidate launcher bytes are the fixed test payload `b"k1-proof-launcher-v2\n"`; candidate Core is built from exactly the six mandatory production-verifier files exercised by `tests/updater/test_generation_builder.py`: `NekoProxyCore.exe`, `NekoProxyCore.dll`, `runtime-settings.nkps`, `bin/Redirector.bin`, `bin/nfapi.dll`, and `bin/v2ray-sn.exe`, each with fixed test bytes. Its exact `core-manifest.json` is `canonical_json_dumps({"rid":"win-x64","executable":"NekoProxyCore.exe","source_commit":"k1-proof-candidate","files": <entries sorted by path with exact size+lowercase sha256>})`; no trailing LF is added. Before zipping, require `verify_canonical_core_bundle(candidate_core_dir).valid is True` and set candidate Core `installed_identity_sha256` to that result's `manifest_sha256` (the SHA-256 of exact `core-manifest.json` bytes). The ZIP contains only the six files + `core-manifest.json`, uses lexicographically sorted normalized forward-slash entry names, `ZIP_STORED`, fixed DOS timestamp `1980-01-01 00:00:00`, and fixed non-symlink file attributes so the ZIP is byte-stable. Copy/read-back candidate artifacts under `E:\Github\artifacts\v512-k1-proof-fixtures\candidate\`. Record exact baseline/candidate component identities **before any Proof Release Authority signer invocation**. These synthetic candidate bytes are isolated test evidence only and never enter production package/history/public surfaces. The synthetic Launcher is an identity/update-payload fixture consistent with the existing balanced helper E2E; K1 acceptance proves the real helper trust/authenticate/stage/handoff/apply boundary only and **does not satisfy or replace Spec §10 packaged restart/relaunch/probation evidence**. RA8/RA9 must still prove the full packaged v5.1.2→v5.1.3-proof lifecycle, including restart/relaunch/probation/commit, with their packaged proof harness.

- [ ] **Step 11 — K1B-B controller-only proof-envelope sealing + canonical custody manifest:** using only the exact Step 10 read-back identities, construct two proof-only canonical ReleaseSetV2 payloads with **all** top-level fields fixed: `schema_version=2`, `channel="stable"`, `updater_protocol={"minimum":1,"maximum":1}`, plus the sequence/id/mandatory/minimum/components fields below. Baseline is `release_sequence=1`, `release_id="proof-k1-0001"`, `mandatory=false`, `minimum_supported_sequence=1`, and its exact components use the Step 10 baseline identities/metadata (`5.1.2`, canonical artifact IDs/formats). Candidate is `release_sequence=2`, `release_id="proof-k1-0002"`, `mandatory=true`, `minimum_supported_sequence=2`, keeps the exact baseline Updater bytes/identity/`version="5.1.2"`, and uses the exact deterministic candidate Launcher/Core identities with `version="5.1.3-proof"`; artifact IDs/formats remain canonical. No other field is controller-selectable. Both payloads never enter production sequence/history. The controller obtains `(key_id, detached_signature)` for each exact payload from the K1A Proof Release Authority out-of-process and uses only the immutable `RT1_CODE_HEAD` `assemble_release_v2_envelope.py`; `scripts/sign_software_release.py` is forbidden. Atomically custody/read-back envelopes as `E:\Github\artifacts\v512-k1-proof-fixtures\baseline\release-v2.json` and `E:\Github\artifacts\v512-k1-proof-fixtures\candidate\release-v2.json`. Then atomically write/fsync/read-back canonical `E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json` with exact closed top-level keys `schema_version=1`, `rt1_code_head_sha`, `authorities`, `profiles`, `artifacts`, `package_evidence`, `proof_releases`. `authorities` contains Profile Authority + Proof Release Authority `{key_id,public_key_sha256,custody_file_sha256}` plus authenticated production `{key_id,public_key_sha256,keyset_sha256}`. `profiles.production|proof` contain `{path,payload_sha256,envelope_sha256,keyset_sha256}`, where `payload_sha256` is the exact `profile_payload_sha256` defined above. `artifacts.baseline|candidate` each contain exactly `launcher`, `updater`, `core`; every component record is `{path,version,artifact_id,artifact_sha256,artifact_size,installed_identity_sha256,artifact_format}` and must byte/hash/size/identity-match the exact file at `path`. `package_evidence` contains `{production_updater_sha256,proof_updater_sha256,updater_byte_identical,baseline_components_sha256,candidate_components_sha256}` where each components SHA is over canonical `{"components": <exact ReleaseSetV2 components>}`. `proof_releases.baseline|candidate` contain `{path,release_sequence,release_id,payload_sha256,envelope_sha256,key_id}`. The manifest verifier requires `artifacts.baseline` exactly equals the component object signed by `proof-k1-0001` and `artifacts.candidate` exactly equals the component object signed by `proof-k1-0002`; no path/hash record may be inferred from an envelope alone. Canonical manifest bytes are JSON + exactly one LF; record its SHA-256 as `K1B_CUSTODY_SHA256`. Any mismatch is `K1B_PROOF_SEALING_BLOCKED`.

- [ ] **Step 12 — Run accepted packaged conformance and write K1 evidence from exact K1B-A/K1B-B custody chain.** Install/enroll the exact proof baseline using the K1B-A proof profile + `proof-k1-0001`, then expose exact `proof-k1-0002` through the local/emulated proof transport and require the real packaged helper boundary to authenticate, stage, hand off, and apply the changed candidate Launcher/Core while the candidate Updater remains byte-identical to the baseline/production helper. Require post-apply updater SHA unchanged, proof envelopes rejected by production profile, production envelope/key rejected by proof profile, and validly signed profile replacement rejected by enrollment pins before state/release evidence selection. Re-run the GREEN/Ruff/diff commands below and write `docs/superpowers/evidence/v512-updater-trust-feasibility.md` recording `rt1_code_head_sha`, `K1B_CUSTODY_SHA256`, K1A public authority custody SHAs, authenticated production registry/keyset digest, both profile payload/envelope/keyset SHAs, both proof payload/envelope SHAs + proof key id, exact baseline/candidate component identities, production/proof updater SHA, fixed installed profile path, negative switch/fallback/profile-replacement/cross-trust results, and invariants A–G PASS/FAIL. No private key material or secret path is recorded.

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_update_trust_profile.py tests/test_build_update_trust_profile.py tests/test_assemble_release_v2_envelope.py tests/test_verify_v512_k1_acceptance.py tests/test_updater_trust_feasibility.py tests/test_update_channel_profile.py tests/updater/test_enrollment.py tests/updater/test_updater_main.py tests/test_github_release.py tests/test_github_asset_downloader.py tests/test_github_release_binding.py -q
.venv\Scripts\ruff.exe check ../scripts/build_update_trust_profile.py ../scripts/assemble_release_v2_envelope.py ../scripts/verify_v512_k1_acceptance.py src/neko_launcher/updater/trust.py src/neko_launcher/updater/trust_profile.py src/neko_launcher/updater/main.py src/neko_launcher/updater/state_models.py src/neko_launcher/updater/enrollment.py src/neko_launcher/infrastructure/update_channel_profile.py src/neko_launcher/infrastructure/github_release.py src/neko_launcher/infrastructure/github_asset_downloader.py src/neko_launcher/infrastructure/github_release_binding.py tests/test_update_trust_profile.py tests/test_build_update_trust_profile.py tests/test_assemble_release_v2_envelope.py tests/test_verify_v512_k1_acceptance.py tests/test_updater_trust_feasibility.py tests/test_update_channel_profile.py tests/updater/test_enrollment.py tests/updater/test_updater_main.py tests/test_github_release.py tests/test_github_asset_downloader.py tests/test_github_release_binding.py
cd ..
git diff --check
git rev-parse HEAD
git status --short
```

- [ ] **Step 13: Independent `ag/gemini-pro-agent` reviews exact `RT1_CODE_HEAD` + exact K1A public custody + exact `K1B_CUSTODY_SHA256` + Step 12 evidence. Required C0/I0 and explicit `UPDATER_TRUST_FEASIBLE`.** Any Critical/Important finding invalidates candidate K1 acceptance: reopen RT1, create a new code commit when source changes, regenerate K1B-A/package identities/K1B-B custody as applicable, rerun conformance/evidence, and review again. A workaround that embeds both release keysets, permits user profile selection, allows either detached assembler to load/invoke a private key/signer, weakens byte canonicalization/signature checks, or uses proof fixture envelopes not reproduced by the shared assembler is `ARCHITECTURE_FEASIBILITY_REGRESSION` and returns to Owner plan review.

- [ ] **Step 14 — Controller seals the reviewed K1 evidence + machine-verifiable acceptance record only after C0/I0:** require evidence `rt1_code_head_sha == RT1_CODE_HEAD`, compute `EVIDENCE_SHA256` over the exact reviewed `v512-updater-trust-feasibility.md` bytes, require recorded `K1B_CUSTODY_SHA256` equals a fresh exact read-back hash, and re-hash/re-verify all K1A public records, K1B-A profiles, K1B-B proof fixture artifacts/envelopes, and the closed custody manifest. Create canonical `docs/superpowers/evidence/v512-k1-acceptance.json` with the exact contract above, using those pre-reviewed digests and reviewer verdict; do not self-derive expected digests from the record after writing. Before commit run the verifier without Git-immutability mode against the candidate record and exact evidence/custody. Commit exactly the evidence Markdown + acceptance JSON in one controller evidence commit, record that commit as `K1_ACCEPTANCE_COMMIT`, then run the **RT1 security-tool immutability guard** above and only on PASS run the verifier again with `--require-git-immutability`, requiring the introduction commit it reports equals `K1_ACCEPTANCE_COMMIT`. Downstream tasks begin only from a branch containing this verified immutable record. Any source/evidence/custody mismatch invalidates K1 acceptance and requires regeneration/re-review.

```cmd
git add docs/superpowers/evidence/v512-updater-trust-feasibility.md docs/superpowers/evidence/v512-k1-acceptance.json
git commit -m "docs(evidence): seal updater trust feasibility"
git rev-parse HEAD
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_k1_acceptance.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --evidence docs\superpowers\evidence\v512-updater-trust-feasibility.md --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json --require-git-immutability
```

**Acceptance:** `UPDATER_TRUST_FEASIBLE / C0_I0` is bound to the immutable `docs/superpowers/evidence/v512-k1-acceptance.json`, which in turn binds (`RT1_CODE_HEAD`, exact K1A public-custody file hashes, `K1B_CUSTODY_SHA256`, exact evidence SHA, reviewer C0/I0, `K1_ACCEPTANCE_COMMIT`). The Git-only RT1 security-tool immutability guard must also PASS before every downstream K1-verifier/assembler use. Only then may RT2+, RA1+, and RH1+ implementation dispatch.

---

## Task RT2: Model Exact Committed/High-Water/Observed/Failed Bindings

**Files:**
- Modify: `launcher/src/neko_launcher/application/software_update_models.py` (`AuthenticatedReleaseBinding`, authenticated `LocalReleaseIdentity`, separate `DevelopmentReleaseIdentity`)
- Modify: `launcher/src/neko_launcher/infrastructure/software_release_identity.py` (`sha256_file` retained; rename unsigned source-mode loader to `load_development_release_identity`)
- Modify: `launcher/tests/test_software_release_identity.py`
- Modify: `launcher/tests/test_software_update_policy.py` fixture constructors to use exact committed/high-water/observed/failed bindings introduced by this task
- Create: `launcher/tests/test_authenticated_release_identity.py` with model-level tests first

**Interfaces:**
- Produces `AuthenticatedReleaseBinding`, authenticated `LocalReleaseIdentity`, and development-only `DevelopmentReleaseIdentity` used by RT3–RT6.

Exact development-only contract:

```python
@dataclass(frozen=True)
class DevelopmentReleaseIdentity:
    release_sequence: Literal[0]
    release_id: Literal["dev-unpublished"]
    launcher_version: str
    launcher_installed_identity_sha256: str
    core_version: str
    core_installed_identity_sha256: str


def load_development_release_identity(
    *,
    launcher_version: str,
    launcher_executable: Path,
    core_version: str,
    core_manifest: Path,
) -> DevelopmentReleaseIdentity:
    ...
```

`DevelopmentReleaseIdentity` is accepted only by explicit development/source-mode utilities and `tests/test_software_release_identity.py`; production update composition, policy, staging, pending, and authenticated reader APIs accept only `LocalReleaseIdentity`.

- [ ] **Step 1: Write the binding-model RED tests.** Include pairwise same-sequence conflict cases across `committed`, `high_water`, `observed`, and non-null `failed`: whenever two local bindings carry the same numeric sequence they must be the exact same `(release_sequence, release_id, payload_sha256)` binding, otherwise construction fails closed.

```python
from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
    LocalReleaseIdentity,
)


def test_local_identity_keeps_full_committed_and_high_water_bindings():
    committed = AuthenticatedReleaseBinding(8, "stable-0008", "1" * 64)
    high_water = AuthenticatedReleaseBinding(9, "stable-0009", "2" * 64)
    failed = high_water
    local = LocalReleaseIdentity(
        committed=committed,
        high_water=high_water,
        observed=high_water,
        failed=failed,
        launcher_version="5.1.2",
        launcher_installed_identity_sha256="3" * 64,
        updater_version="5.1.2",
        updater_installed_identity_sha256="4" * 64,
        core_version="5.1.2",
        core_installed_identity_sha256="5" * 64,
    )
    assert local.release_sequence == 8
    assert local.high_water.release_sequence == 9
    assert local.failed == high_water
```

- [ ] **Step 2: Add the source-mode migration RED cases before implementation:** `load_development_release_identity(...)` returns only `DevelopmentReleaseIdentity`; authenticated `LocalReleaseIdentity` rejects seq0; production policy/composition test fixtures cannot pass a development identity as authenticated authority.

- [ ] **Step 3: Run the complete RT2 RED set before implementation.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_authenticated_release_identity.py tests/test_software_release_identity.py tests/test_software_update_policy.py -q
```

Expected RED: `AuthenticatedReleaseBinding`/new authenticated constructor and `DevelopmentReleaseIdentity`/development loader do not yet exist, while legacy seq0 identity is still accepted in authenticated model paths.

- [ ] **Step 4: Implement the minimal dataclasses and validation.**

```python
@dataclass(frozen=True)
class AuthenticatedReleaseBinding:
    release_sequence: int
    release_id: str
    payload_sha256: str


@dataclass(frozen=True)
class LocalReleaseIdentity:
    committed: AuthenticatedReleaseBinding
    high_water: AuthenticatedReleaseBinding
    observed: AuthenticatedReleaseBinding
    failed: AuthenticatedReleaseBinding | None
    launcher_version: str
    launcher_installed_identity_sha256: str
    updater_version: str
    updater_installed_identity_sha256: str
    core_version: str
    core_installed_identity_sha256: str

    @property
    def release_sequence(self) -> int:
        return self.committed.release_sequence
```

Validate positive authenticated sequences and lowercase 64-hex payload/identity hashes. Do not permit authenticated seq0. Require `committed.release_sequence <= high_water.release_sequence`, require `observed == high_water` for an enrolled production identity, and require `failed is None or failed.release_sequence <= high_water.release_sequence`. Enforce a pairwise local authority invariant: any two non-null bindings among `committed`, `high_water`, `observed`, and `failed` that have the same numeric sequence must be exactly equal in sequence/release_id/payload SHA; same-sequence local rebinding is invalid state. The equality `observed == high_water` is semantic, not redundant: `failed == high_water` means terminally suppressed; `failed != high_water` means the exact authenticated high-water remains resumable/retryable.

- [ ] **Step 5: Implement the Step 2 source-mode/type-separation RED contract:** retire sequence-0 from authenticated `LocalReleaseIdentity`, implement the exact `DevelopmentReleaseIdentity` dataclass + `load_development_release_identity(...)` signature above, migrate the existing unsigned hash-only loader, and update every current `dev-unpublished` model fixture to the development type. Do not add new behavior tests after implementation; Step 2 already owns the negative production-boundary assertions.

- [ ] **Step 6: Update existing test fixtures to construct exact bindings, without changing behavior expectations yet.**

- [ ] **Step 7: Run model/source-mode/policy tests GREEN, then Ruff and diff check.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_authenticated_release_identity.py tests/test_software_release_identity.py tests/test_software_update_policy.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/application/software_update_models.py src/neko_launcher/infrastructure/software_release_identity.py tests/test_authenticated_release_identity.py tests/test_software_release_identity.py tests/test_software_update_policy.py
cd ..
git diff --check
```

- [ ] **Step 8: Commit exactly the RT2-owned migration files.**

```cmd
git add launcher/src/neko_launcher/application/software_update_models.py launcher/src/neko_launcher/infrastructure/software_release_identity.py launcher/tests/test_authenticated_release_identity.py launcher/tests/test_software_release_identity.py launcher/tests/test_software_update_policy.py
git commit -m "refactor: preserve authenticated release bindings"
```

**Review:** C0/I0. Reviewer must specifically reject any representation that reduces high-water to an integer only.

---

## Task RT3: Read Authenticated Local Identity From Durable Updater State

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/authenticated_release_identity.py`
- Reuse: `launcher/src/neko_launcher/infrastructure/software_release_identity.py` from RT2 (`sha256_file` and development-only loader contract; RT3 does not re-own that migration)
- Modify: `launcher/tests/test_authenticated_release_identity.py` (created and model-owned by RT2; RT3 extends it with reader/state integration cases)
- Reuse: `launcher/src/neko_launcher/updater/slot_store.py`, `slot_selector.py`, `state_models.py`, `manifest_v2.py`, `trust_profile.py`, and RT1's enrollment trust-binding validator.

**Interface contract:** `AuthenticatedReleaseIdentityReader(trust_profile: VerifiedUpdateTrustProfile)`; method `read(install_root: Path) -> LocalReleaseIdentity`. Constructor copies/freeze-maps only `trust_profile.release_public_keys`; `read()` first requires the fixed enrollment marker to match the same `profile_id`, `profile_envelope_sha256`, and `keyset_sha256`, then selects/verifies durable state with that exact registry. It has no network, raw-key, or alternate-profile fallback and either returns a fully authenticated identity or raises the task's fail-closed identity error.

- [ ] **Step 1: Add RED fixture helper that writes a valid enrolled slot state whose `evidence[payload_sha]` contains the signed envelope used by the committed generation.**

Use `tests.software_update_helpers.signed_envelope()` + `valid_v2_release_document()` and existing state serialization helpers; do not invent a parallel fake state format.

- [ ] **Step 2: Add the complete RT3 RED set before implementation:** happy path; rollback history with committed N/high-water+observed+failed N+1; retryable admitted state with committed N/high-water+observed N+1 and `failed != high_water`; high-water/observed mismatch; missing evidence; invalid signature; payload/release-id mismatch; Launcher/Core identity mismatch; Updater file mismatch; enrollment incomplete; corrupt slots.

```python
def test_reader_returns_authenticated_committed_and_high_water(tmp_path, verified_profile):
    install = make_enrolled_install(
        tmp_path,
        committed=(8, "stable-0008"),
        high_water=(8, "stable-0008"),
        trust_profile=verified_profile,
    )
    local = AuthenticatedReleaseIdentityReader(verified_profile).read(install)
    assert local.committed.release_sequence == 8
    assert local.committed.release_id == "stable-0008"
    assert local.high_water == local.committed
```

- [ ] **Step 3: Run and verify RED because `AuthenticatedReleaseIdentityReader` does not exist yet.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_authenticated_release_identity.py -q
```

Expected RED: import/name failure for the reader or the new reader-specific happy-path assertion; environment/setup failures do not count.

- [ ] **Step 4: Implement the reader using existing slot selection and `verify_release_envelope_v2`; resolve committed/high-water/observed/failed evidence by exact payload SHA and implement only validation required by the complete Step 2 RED matrix. No unsigned fallback.**

Exact reader algorithm:

1. Call RT1's fixed-marker trust-binding validator for `install_root` and this reader's `VerifiedUpdateTrustProfile`; require exact `profile_id/profile_envelope_sha256/keyset_sha256` match before opening authoritative state.
2. Construct `SlotStore(install_root / "state" / "slot-a.bin", install_root / "state" / "slot-b.bin", self._keys)` from only the verified profile release registry and call `load()`.
3. Require `SelectionStatus.SELECTED`, non-null state, `enrollment_complete=True`, and non-null `committed` + `highwater` bindings.
4. Resolve `state.committed.binding.payload_sha256` in `state.evidence`; base64/decode its stored exact envelope, verify with `verify_release_envelope_v2(..., self._keys)`, and require returned `(release_sequence, release_id, payload_sha256)` to equal the committed binding exactly.
5. Require signed Launcher/Core installed identities to equal the committed `Generation` identities and hash installed `NekoUpdater.exe` against the signed Updater installed identity.
6. Require non-null `state.observed`, require `state.observed == state.highwater`, resolve/verify the observed/high-water payload evidence when it differs from committed, and independently resolve/verify `failed` when present. Never accept a bare sequence without signed evidence.
7. Return `LocalReleaseIdentity(committed=..., high_water=..., observed=..., failed=..., launcher/updater/core versions and installed identities from the authenticated committed envelope/state)`. A state with `highwater == observed > committed` and `failed != highwater` is a valid authenticated-but-not-terminally-failed resumable authority: RT5 may report `LATEST` at the authority-ordering layer only together with `retry_staging=true`, never as terminal/no-work `LATEST`.

- [ ] **Step 5: Run focused GREEN tests plus updater enrollment/slot regressions after the full Step 2 matrix passes.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_authenticated_release_identity.py tests/updater/test_enrollment.py tests/updater/test_slot_selector.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/infrastructure/authenticated_release_identity.py tests/test_authenticated_release_identity.py
cd ..
git diff --check
```

- [ ] **Step 6: Commit exactly RT3 files and request independent review.**

```cmd
git add launcher/src/neko_launcher/infrastructure/authenticated_release_identity.py launcher/tests/test_authenticated_release_identity.py
git commit -m "feat: read authenticated installed release identity"
```

**Review:** C0/I0; Sol-high escalation only if durable-state trust semantics remain genuinely unresolved after normal review.

---

## Task RT4: Wire Production Composition To Authenticated Identity + Machine Profile

**Files:**
- Modify: `launcher/src/neko_launcher/bootstrap/app_factory.py` (`compose_update_check_service` and provider factories)
- Modify: `launcher/src/neko_launcher/bootstrap/pending_update_bootstrap.py`
- Modify: `launcher/tests/test_software_update_composition.py`
- Modify: `launcher/tests/test_pending_update_bootstrap.py`

**Consumes:** RT1 `load_installed_update_trust_profile`, `UpdateChannelProfile.from_verified`, and `AuthenticatedReleaseIdentityReader`.

- [ ] **Step 1: Write RED composition test proving production composition does not construct `dev-unpublished/0`, does not accept a raw release-key registry, and derives discovery + local-state verification from one exact verified installed profile.**

Required production/test seam extends the **existing** signature without removing its required `config` argument: `compose_update_check_service(config: LauncherConfig, *, verified_profile: VerifiedUpdateTrustProfile | None = None, resolver: AuthenticatedReleaseGateway | None = None, root_dir: Path | None = None, identity_reader: AuthenticatedReleaseIdentityReader | None = None) -> UpdateCheckService`.

Resolve `install_root = root_dir or get_expected_install_root()`. When `verified_profile is None`, production composition must call `load_installed_update_trust_profile(install_root)` at the fixed path. It then derives both `UpdateChannelProfile.from_verified(profile)` and `AuthenticatedReleaseIdentityReader(profile)` from that **same object**. Tests may inject an already-verified profile or fake identity reader; there is no `key_registry` parameter and no packaged CLI/env/user-config trust seam.

```python
def test_production_composition_uses_authenticated_identity_reader(config, tmp_path):
    reader = FakeIdentityReader(local_identity(sequence=8))
    service = compose_update_check_service(
        config,
        root_dir=tmp_path,
        identity_reader=reader,
    )
    result = service._local_identity_provider()
    assert result.committed.release_sequence == 8
    assert reader.calls == [tmp_path]
```

- [ ] **Step 2: RED test that the release gateway is built from `UpdateChannelProfile.from_verified(the_same_profile)` and therefore production resolves only the profile-authenticated Updates repository. Assert a mismatched profile object between gateway and identity reader is rejected by composition rather than silently mixing trust domains.**

- [ ] **Step 3: RED pending-bootstrap test proving it reads the same durable local authority instead of constructing `dev-unpublished`.**

- [ ] **Step 4: Run RED focused tests before production composition changes.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_composition.py tests/test_pending_update_bootstrap.py -q
```

Expected RED: production composition/pending bootstrap still constructs `dev-unpublished/0` and does not route through the authenticated identity reader/machine profile.

- [ ] **Step 5: Replace hard-coded source-mode identity lambdas with the authenticated reader and fixed signed-profile loader in production composition. Keep explicit development/test factories separate; delete/forbid the production raw-key injection seam.**

- [ ] **Step 6: Run GREEN + relevant gateway tests/Ruff/diff-check.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_composition.py tests/test_pending_update_bootstrap.py tests/test_github_release.py tests/test_github_release_binding.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/bootstrap/app_factory.py src/neko_launcher/bootstrap/pending_update_bootstrap.py tests/test_software_update_composition.py tests/test_pending_update_bootstrap.py
cd ..
git diff --check
```

- [ ] **Step 7: Commit.**

```cmd
git add launcher/src/neko_launcher/bootstrap/app_factory.py launcher/src/neko_launcher/bootstrap/pending_update_bootstrap.py launcher/tests/test_software_update_composition.py launcher/tests/test_pending_update_bootstrap.py
git commit -m "feat: compose updates from authenticated local state"
```

**Review:** C0/I0.

---

## Task RT5: Enforce Authenticated Ordering and Exact Mandatory Formula

**Files:**
- Modify: `launcher/src/neko_launcher/application/software_update_policy.py` (`evaluate_release`)
- Modify: `launcher/src/neko_launcher/application/software_update_models.py` to add authenticated `ReleaseSet.payload_sha256` plus exact `UpdateCheckResult.retry_staging: bool` lifecycle intent required by the contract
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_v2.py` so `V2ReleaseManifestVerifierAdapter.verify()` preserves the verifier-returned payload SHA-256 in `ReleaseSet` instead of discarding it
- Modify: `launcher/tests/test_software_update_policy.py`
- Modify: `launcher/tests/test_software_update_v2_adapter.py`
- Modify: `launcher/tests/test_software_update_models.py`

**Result interface extension:** append `retry_staging: bool = False` as the final field of `UpdateCheckResult`. Existing result constructors remain non-retry by default; only RT5 policy sets it true for an exact observed-unfailed high-water authority whose artifact lifecycle is incomplete.

**Ordering contract:** high-water binding governs replay/rebinding; committed binding governs runtime minimum-supported policy; observed+failed distinguish retryable authenticated authority from terminally suppressed authority. RT5 is policy/model only and does not mutate updater durable state.

- [ ] **Step 1: Add parameterized RED tests for normal baseline.**

```python
@pytest.mark.parametrize(
    ("remote_seq", "mandatory_flag", "minimum", "expected_state"),
    [
        (9, False, 8, UpdateState.AVAILABLE),
        (9, True, 8, UpdateState.MANDATORY),
        (9, False, 9, UpdateState.MANDATORY),
    ],
)
def test_newer_release_uses_committed_sequence_for_mandatory(
    remote_seq, mandatory_flag, minimum, expected_state
):
    local = local_with(committed=bind(8), high_water=bind(8), observed=bind(8))
    remote = release_for(
        bind(remote_seq),
        mandatory=mandatory_flag,
        minimum_supported_sequence=minimum,
    )
    result = evaluate_release(local, remote, UpdateInvocationReason.STARTUP)
    assert result.state == expected_state
```

- [ ] **Step 2: Add RED exact-same-binding matrix before implementation.**

```python
def test_committed_exact_high_water_is_latest():
    local = local_with(committed=bind(8), high_water=bind(8), observed=bind(8))
    result = evaluate_release(local, release_for(bind(8)), UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.LATEST
    assert result.mandatory is False


def test_exact_failed_high_water_is_known_not_fresh_update():
    local = local_with(committed=bind(8), high_water=bind(9), observed=bind(9), failed=bind(9))
    result = evaluate_release(local, release_for(bind(9)), UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.LATEST
    assert result.mandatory is False
    assert result.changed_components == ()


def test_exact_observed_unfailed_high_water_is_retryable_mandatory():
    local = local_with(committed=bind(8), high_water=bind(9), observed=bind(9), failed=None)
    remote = release_for(bind(9), mandatory=True, minimum_supported_sequence=8)
    result = evaluate_release(local, remote, UpdateInvocationReason.STARTUP)
    assert result.state == UpdateState.LATEST  # no new authority
    assert result.mandatory is True
    assert result.retry_staging is True
    assert result.changed_components == ("launcher", "core")
```

- [ ] **Step 3: Add RED same-sequence conflict, lower-than-high-water replay, and semantic-version-irrelevance tests.** A remote with the same numeric sequence but different `(release_id, payload_sha256)` must be `VERIFY_FAILED / SAME_SEQUENCE_IDENTITY_CONFLICT`; lower-than-high-water must be rejected; semantic version never changes ordering.

`ReleaseSet.payload_sha256` is mandatory after this task. The v2 adapter obtains it only from `verify_release_envelope_v2`; policy compares exact `(release_sequence, release_id, payload_sha256)` against local committed/high-water/observed/failed bindings. Never infer authority equality from semantic version or component hashes alone.

Exact matrix:

```text
remote.sequence > high_water.sequence
    => AVAILABLE or MANDATORY from committed-sequence formula
remote == committed == high_water == observed
    => LATEST / no update
remote == high_water == observed > committed AND failed == high_water
    => LATEST / known failed / do not reapply
remote == high_water == observed > committed AND failed != high_water
    => LATEST / no new authority; preserve mandatory formula; retry_staging=true;
       preserve changed_components by comparing authenticated remote identities to committed runtime identities
remote.sequence == high_water.sequence AND remote binding != high_water
    => VERIFY_FAILED / SAME_SEQUENCE_IDENTITY_CONFLICT
remote.sequence < high_water.sequence
    => VERIFY_FAILED / DOWNGRADE_REJECTED
```

- [ ] **Step 4: Run the complete RT5 RED set before implementation.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_policy.py tests/test_software_update_v2_adapter.py tests/test_software_update_models.py -q
```

Expected RED: the v2 adapter discards authenticated `payload_sha256`, `UpdateCheckResult.retry_staging` does not exist, exact observed-unfailed high-water cannot express "same authority but resume incomplete staging", and replay/conflict assertions do not satisfy the new binding contract.

- [ ] **Step 5: Implement only payload propagation + policy/lifecycle intent.** Append `UpdateCheckResult.retry_staging: bool = False` exactly as defined above; existing constructors rely on the false default and policy explicitly sets true only for retryable admitted authority. Compute Launcher/Core `changed_components` against the **committed runtime identities before same-high-water lifecycle branching**. Apply checks in this order: lower-than-high-water reject; same-high-water binding conflict reject; exact committed baseline => `LATEST, retry_staging=false, changed_components=()`; exact failed high-water => `LATEST, retry_staging=false, changed_components=()`; exact observed-unfailed high-water above committed => `LATEST, retry_staging=true` while preserving mandatory formula **and the committed-vs-remote changed_components needed by staging**; newer-than-high-water => AVAILABLE/MANDATORY with `retry_staging=false`. This preserves Spec Section 7's "same exact authority = no new update" ordering while Spec Section 8 can resume an already admitted incomplete authority. Do not write updater state in RT5.

Exact formula:

```python
mandatory = (
    remote.mandatory
    or local.committed.release_sequence < remote.minimum_supported_sequence
)
```

- [ ] **Step 6: Run GREEN + policy/coordinator/stage regressions, Ruff, and diff-check.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_policy.py tests/test_software_update_v2_adapter.py tests/test_software_update_models.py tests/test_software_update_coordinator.py tests/test_software_update_stage.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/application/software_update_policy.py src/neko_launcher/application/software_update_models.py src/neko_launcher/infrastructure/software_update_v2.py tests/test_software_update_policy.py tests/test_software_update_v2_adapter.py tests/test_software_update_models.py
cd ..
git diff --check
```

- [ ] **Step 7: Commit exactly RT5 files.**

```cmd
git add launcher/src/neko_launcher/application/software_update_policy.py launcher/src/neko_launcher/application/software_update_models.py launcher/src/neko_launcher/infrastructure/software_update_v2.py launcher/tests/test_software_update_policy.py launcher/tests/test_software_update_v2_adapter.py launcher/tests/test_software_update_models.py
git commit -m "fix: enforce authenticated update ordering"
```

**Review:** C0/I0; reviewer must verify committed-vs-high-water/observed/failed semantics, exact same admitted authority remains `LATEST` at the authority-ordering layer while `retry_staging=true` drives lifecycle resumption, retryable results retain committed-vs-remote `changed_components`, and RT5 contains no durable-state mutation.

---

## Task RT6: Durably Admit Authenticated Authority Before Artifact Staging

**Purpose:** Close Spec Case 2 at the real pipeline boundary. `SoftwareUpdateCoordinator` currently invokes `SoftwareUpdateStageService.stage()` before `SoftwareUpdateApplyService.prepare_pending()`/helper `BEGIN`; therefore authenticated authority must be persisted **before** `stage()` starts any Launcher/Core download. RT6 adds a one-shot helper admission IPC that re-verifies the exact envelope and writes authority while remaining IDLE, without creating an update transaction or incoming directory.

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/software_update_authority_admission.py`
- Modify: `launcher/src/neko_launcher/application/software_update_coordinator.py`
- Modify: `launcher/src/neko_launcher/bootstrap/app_factory.py`
- Modify: `launcher/src/neko_launcher/updater/main.py`
- Modify: `launcher/src/neko_launcher/updater/broker.py`
- Modify: `launcher/src/neko_launcher/updater/staging_handoff.py`
- Modify: `launcher/src/neko_launcher/updater/state_machine.py`
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_apply.py` to retire the unsafe direct-online `prepare()` path; production apply consumes only a verified durable pending update through `prepare_pending(...)`
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_stage.py` so `LATEST + retry_staging=true` continues artifact staging instead of returning early
- Modify: `launcher/src/neko_launcher/infrastructure/software_update_pending_store.py` so a verified pending envelope must bind exactly to local `high_water == observed` and must not equal `failed`
- Modify: `launcher/src/neko_launcher/ui/app_window.py` to remove compatibility fallbacks that call direct-online `prepare()`; UI apply/close paths require `prepare_pending(pending)` when verified pending exists
- Create: `launcher/tests/test_software_update_authority_admission.py`
- Modify: `launcher/tests/test_software_update_coordinator.py`
- Modify: `launcher/tests/test_software_update_composition.py`
- Modify: `launcher/tests/test_software_update_service.py` for outage regression only
- Modify: `launcher/tests/updater/test_staging_handoff.py`
- Modify: `launcher/tests/updater/test_broker_balanced.py`
- Modify: `launcher/tests/updater/test_updater_main.py`
- Modify: `launcher/tests/updater/test_state_machine.py`
- Modify: `launcher/tests/test_software_update_apply.py`, `launcher/tests/test_software_update_privacy.py`
- Modify: `launcher/tests/e2e/test_github_release_update_e2e.py` so production-style E2E reaches apply only through coordinator staging + durable pending + `prepare_pending(...)`
- Modify: `launcher/tests/test_software_update_stage.py`, `launcher/tests/test_software_update_pending_store.py`
- Modify: `launcher/tests/ui/test_app_window.py`
- Regression: `launcher/tests/test_pending_update_bootstrap.py`

**Launcher-side interface:**

```python
@dataclass(frozen=True)
class AuthorityAdmissionResult:
    accepted: bool
    binding: AuthenticatedReleaseBinding | None
    changed: bool
    error: str | None


class SoftwareUpdateAuthorityAdmissionService:
    def admit(self, envelope_bytes: bytes) -> AuthorityAdmissionResult: ...
```

`SoftwareUpdateAuthorityAdmissionService` spawns the installed `NekoUpdater.exe --session` through the same non-shell process restrictions used by updater apply, sends exactly one IPC message `ADMIT_AUTHORITY` with body `{"envelope_b64": <base64 exact envelope bytes>}`, receives exactly one `AUTHORITY_ADMITTED` response with `receive_message(timeout_s=5.0)`, validates its closed schema, closes both pipe directions, waits at most 5.0 seconds for the helper process to exit, requires exit code 0, and only then returns accepted success. Nonzero exit, response/process timeout, malformed response, premature EOF, or process-lifecycle error is fail-closed. It exposes no CLI/env/user trust override and does not download artifacts.

**Updater session completion contract:** define `SessionDisposition` in `launcher/src/neko_launcher/updater/main.py` as exact enum members `ADMISSION_ONLY`, `APPLY_VERIFIED`, and `FAILED`; change `serve_session(...) -> SessionDisposition`. Current `run_session()` always calls `activate_verified_generation(...)` after any successful boolean `serve_session()` result, which is incompatible with an admission-only IDLE session. `ADMIT_AUTHORITY` returns `SessionDisposition.ADMISSION_ONLY`; `run_session()` must close the channel/session, skip `activate_verified_generation(...)`, close the slot store, and return exit 0. Existing `BEGIN -> APPLY` returns `SessionDisposition.APPLY_VERIFIED` and retains the current activation path. `FAILED` returns nonzero. No admission-only success may enter probation/activation or require a transaction.

**Updater-side interface:** define in `staging_handoff.py`:

```python
@dataclass(frozen=True)
class AuthorityAdmissionResponse:
    accepted: bool
    binding: Binding | None
    changed: bool
    error: str | None


def handle_authority_admission_request(
    current_state: State,
    envelope_b64: str,
    public_keys: Mapping[str, bytes],
) -> tuple[AuthorityAdmissionResponse, State | None]: ...
```

Add `BrokerCoordinator.admit_authority(envelope_b64: str) -> AuthorityAdmissionResponse`. The handler has **no `root_dir` argument** and therefore cannot create an incoming directory. The `public_keys` argument above is an internal dependency only: packaged `main --session` must first load the one fixed signed trust profile, require its `profile_id/profile_envelope_sha256/keyset_sha256` to match enrollment, then pass only that resolved release registry into `SlotStore`/`BrokerCoordinator`; no IPC/argv/env/config field may supply or replace it. The handler re-verifies `release-v2`, protocol, and exact binding using that same session-fixed registry. The IPC `AUTHORITY_ADMITTED` response body is closed and exact: `accepted`, `release_sequence`, `release_id`, `payload_sha256`, `changed`, `error`; success requires all three binding fields and `error=None`, rejection requires all three binding fields null, `changed=false`, and one exact error from `SIGNATURE_INVALID`, `SCHEMA_INVALID`, `PROTOCOL_UNSUPPORTED`, `LOCK_BUSY`, `DOWNGRADE_REJECTED`, `SAME_SEQUENCE_CONFLICT`, `CANDIDATE_SUPPRESSED`, `STATE_CORRUPT`, or `IO_FAILED`. Launcher converts those binding fields to `AuthenticatedReleaseBinding` only after validating the full response schema.

**Admission state contract:**

```text
precondition: current.phase == IDLE, enrollment_complete == true
newer authenticated binding:
    committed/previous unchanged
    highwater = candidate
    observed = candidate
    failed = current.failed
    evidence = current.evidence + {candidate.payload_sha256: exact envelope_b64}
    transaction = null
    cleanup = null
    rollback = null
    phase = IDLE
    revision += 1
exact already-observed/highwater binding, not failed:
    accepted idempotently, changed=false, no state write
exact failed binding:
    CANDIDATE_SUPPRESSED
same sequence different release_id/payload:
    SAME_SEQUENCE_CONFLICT
lower than high-water/observed/committed floor:
    DOWNGRADE_REJECTED
```

`state_machine.py` adds one narrow enrolled `IDLE -> IDLE` authority-admission transition. It is valid only when committed/previous/failed are unchanged, no transaction/cleanup/rollback exists, `highwater == observed` advances to one strictly newer exact binding, existing evidence entries are byte-for-byte unchanged, exactly the candidate payload evidence is added, and no other state field changes except revision. Existing enrollment-completion `IDLE -> IDLE` remains separate. Arbitrary IDLE mutation stays invalid.

**Coordinator ordering contract:**

```text
authenticated resolve/check
    -> if state is AVAILABLE/MANDATORY OR retry_staging=true:
         admission_service.admit(resolved.envelope_bytes)
         -> fresh local_identity_provider() read
         -> evaluate_release(fresh_local, same authenticated remote)
         -> if refreshed result is AVAILABLE/MANDATORY OR retry_staging=true:
              SoftwareUpdateStageService.stage(...)
         -> otherwise return without staging
    -> otherwise return without staging
```

`stage()` must never transfer bytes before successful/idempotent helper admission, even if a caller bypasses the coordinator. RT6 adds an internal stage admission gate before any pending lookup, staging-directory creation, or downloader call: derive exact remote binding from authenticated `ReleaseSet.payload_sha256` and require `remote_binding == local.high_water == local.observed`, `remote_binding != local.failed`, and `remote.sequence > local.committed.sequence`; otherwise raise fixed `SoftwareUpdateStageError("AUTHORITY_NOT_ADMITTED")` (existing replay/conflict diagnostics still take precedence when applicable). A first-seen newer authority therefore cannot be staged directly. After durable admission, fresh evaluation of that exact same authority is `LATEST` with `retry_staging=true`, which means "no new authority, resume incomplete lifecycle" rather than "do nothing". RT6 then returns early for `LATEST` only when `retry_staging == false`; `LATEST + retry_staging=true` proceeds through the normal changed-component download/promote path. If concurrent state change produces `LATEST` with `retry_staging=false`, coordinator returns without staging. Admission conflict/downgrade/state-corruption fails closed. After admission, a network/download failure in `stage()` leaves updater state IDLE with committed N and exact `highwater=observed=N+1`; it does **not** create `failed=N+1`, does not fabricate durable pending, and requires no PREPARING recovery because helper `BEGIN` has not run yet.

**Pending exact-binding contract:** `PendingUpdateStore.load_verified(local_identity)` must re-verify the pending envelope and keep the returned payload SHA. Construct exact pending binding `(release_sequence, release_id, payload_sha256)` and return pending only when it equals both `local_identity.high_water` and `local_identity.observed`, is strictly newer than `local_identity.committed`, and is not equal to `local_identity.failed`. A lower pending is stale/replay and a same-sequence different payload/release binding is invalid; neither is applied. This prevents a previously staged or corrupted same-sequence pending from bypassing the admitted authority binding.

**No bypass path:** current `SoftwareUpdateApplyService.prepare()` independently resolves a release, sends helper `BEGIN`, and downloads directly into helper `incoming/` before a durable pending record exists. That path violates the pre-stage admission/retry contract and must cease to be production-capable in RT6. After RT6, production apply accepts only `prepare_pending(VerifiedPendingUpdate)`. Keep the legacy zero-argument `prepare()` only as a fail-closed compatibility method returning/raising fixed diagnostic `PENDING_UPDATE_REQUIRED`; it must not resolve, admit, download, spawn a helper, or mutate updater state. `app_factory.py` must stop wiring a release resolver/asset downloader into production `SoftwareUpdateApplyService`; those network dependencies remain owned by discovery/stage services. `app_window.py` currently has two `hasattr(..., "prepare_pending") else prepare()` compatibility fallbacks; RT6 removes those fallbacks so both explicit apply and safe-close apply invoke only `prepare_pending(pending)` and surface/ignore failure according to their existing UI boundary without ever switching to direct-online resolution. Production composition/UI tests and GitHub-update E2E must prove the real path is `authenticated check -> ADMIT_AUTHORITY -> stage/promote durable pending -> prepare_pending -> BEGIN/APPLY`.

- [ ] **Step 1: Write updater-handler/state-machine RED tests before implementation.** Prove valid newer admission yields IDLE→IDLE exact state above; same exact unfailed binding is idempotent with no write; exact failed candidate is suppressed; same-sequence conflict/lower sequence reject; arbitrary IDLE→IDLE mutation remains rejected; no transaction/incoming identity is created.

- [ ] **Step 2: Write broker/session RED tests.** Before either `ADMIT_AUTHORITY` or `BEGIN`, packaged session startup must resolve exactly one fixed signed profile and validate its enrollment pins; a changed/missing/bad-signature profile stops before `SlotStore`/broker work. `ADMIT_AUTHORITY` must then be accepted as a one-shot first message, invoke `BrokerCoordinator.admit_authority` with only the session-fixed verified release registry, durably write the admitted state before `AUTHORITY_ADMITTED`, then return the exact admission-only session disposition. Assert `run_session()` returns success for that disposition **without invoking `activate_verified_generation`**. Add lost-response durability coverage: if state write succeeds but the response/pipe closes before the Launcher observes success, a later exact admission must be idempotent and retryable rather than failed/rebound. Existing `BEGIN -> REQUEST_READY -> APPLY` must return the apply/activation disposition and preserve activation behavior.

- [ ] **Step 3: Write launcher admission-service RED tests.** Assert exact `NekoUpdater.exe --session` argv, exact IPC message/response schema, exact binding conversion, and fail-closed malformed/EOF/error behavior. Assert no sequence/release/key/path trust argument is passed on argv.

- [ ] **Step 4: Write coordinator/stage/pending RED ordering tests using call-order fakes.** Require first-seen AVAILABLE/MANDATORY remote to call `admit` before the first downloader/stage call, require a fresh local identity read after admission, require refreshed policy to return `LATEST + retry_staging=true`, and require `stage(resolved, refreshed_local)` with `highwater=observed=remote`. Directly invoke stage with a first-seen newer-but-not-admitted remote and require `AUTHORITY_NOT_ADMITTED` before pending lookup/directory creation/downloader invocation. Prove admitted `LATEST + retry_staging=true` does not early-return but ordinary `LATEST + retry_staging=false` does. Add a rediscovery case that starts already admitted and proves idempotent admission + staging retry. Add pending-store cases proving only exact `(sequence, release_id, payload_sha256) == high_water == observed` and `!= failed` loads; conflicting/stale/failed pending is rejected. Add a failure case where stage download raises after admission and prove no pending is fabricated.

- [ ] **Step 5: Write restart/outage + no-bypass RED scenarios.** Begin with committed N; admit mandatory N+1; force stage download failure before `PendingUpdateStore.promote`; reconstruct identity from durable state and require committed=N, `highwater=observed=N+1`, `failed!=N+1`, no pending. Make discovery unavailable and require committed runtime remains non-bricking; restore exact N+1 and require RT5 returns `LATEST`, `mandatory=true`, `retry_staging=true`; admission is idempotent and staging retries. Separately call legacy `SoftwareUpdateApplyService.prepare()` and require fixed `PENDING_UPDATE_REQUIRED` before resolver/spawner/downloader/state mutation; then prove production-style E2E applies only via verified pending + `prepare_pending(...)`. In `test_software_update_apply.py`, migrate every legacy `prepare()` case whose real purpose is BEGIN/APPLY/IPC/hash/process behavior to an equivalent verified-pending fixture + `prepare_pending(...)`; replace resolver-refetch/direct-download-specific legacy cases with the single fail-closed `PENDING_UPDATE_REQUIRED` contract and no-call assertions. Do the same migration for direct-prepare cases in `test_software_update_privacy.py` and `test_github_release_update_e2e.py`. Add `tests/ui/test_app_window.py` RED cases for both current source fallbacks (explicit apply and safe-close apply) proving a service without `prepare_pending` is never allowed to fall back to `prepare()`, while verified pending calls `prepare_pending(pending)` exactly once. The GREEN suite must contain no production/UI/E2E path that treats direct-online prepare as valid.

- [ ] **Step 6: Run the complete RT6 RED suite before production changes.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_authority_admission.py tests/test_software_update_coordinator.py tests/test_software_update_composition.py tests/test_software_update_service.py tests/test_software_update_stage.py tests/test_software_update_pending_store.py tests/test_software_update_apply.py tests/test_software_update_privacy.py tests/e2e/test_github_release_update_e2e.py tests/ui/test_app_window.py tests/updater/test_staging_handoff.py tests/updater/test_broker_balanced.py tests/updater/test_updater_main.py tests/updater/test_state_machine.py -q
```

Expected RED: the helper has no `ADMIT_AUTHORITY` one-shot path, IDLE→IDLE authenticated admission is rejected, coordinator calls `stage()` without durable helper admission, stage has no fail-closed exact-admission gate and treats every `LATEST` as terminal/no-stage, pending verification does not bind exact payload to admitted high-water, and the new admission service does not exist. Import/environment failures do not count.

- [ ] **Step 7: Implement the exact helper admission handler, narrow state-machine transition, typed session disposition/no-activation admission completion, launcher admission service, coordinator/app-factory wiring, `SoftwareUpdateStageService` retry-staging gate, exact-binding pending verification, retirement of direct-online `SoftwareUpdateApplyService.prepare()`, removal of both UI direct-prepare fallbacks, and the Step 5 test/E2E migration to `prepare_pending(...)`.** Do not alter PREPARING abort/recovery semantics in RT6; artifact staging now happens before helper `BEGIN`, so a stage transport failure must never enter PREPARING. `prepare_pending(...)` remains the only production apply entry point after durable pending verification.

- [ ] **Step 8: Run GREEN + stage/pending/apply regressions, Ruff, and diff-check.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_software_update_authority_admission.py tests/test_software_update_coordinator.py tests/test_software_update_composition.py tests/test_software_update_service.py tests/test_software_update_stage.py tests/test_software_update_pending_store.py tests/test_pending_update_bootstrap.py tests/test_software_update_apply.py tests/test_software_update_privacy.py tests/e2e/test_github_release_update_e2e.py tests/ui/test_app_window.py tests/updater/test_staging_handoff.py tests/updater/test_broker_balanced.py tests/updater/test_updater_main.py tests/updater/test_state_machine.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/infrastructure/software_update_authority_admission.py src/neko_launcher/infrastructure/software_update_apply.py src/neko_launcher/infrastructure/software_update_stage.py src/neko_launcher/infrastructure/software_update_pending_store.py src/neko_launcher/application/software_update_coordinator.py src/neko_launcher/bootstrap/app_factory.py src/neko_launcher/ui/app_window.py src/neko_launcher/updater/main.py src/neko_launcher/updater/broker.py src/neko_launcher/updater/staging_handoff.py src/neko_launcher/updater/state_machine.py tests/test_software_update_authority_admission.py tests/test_software_update_coordinator.py tests/test_software_update_composition.py tests/test_software_update_service.py tests/test_software_update_stage.py tests/test_software_update_pending_store.py tests/test_software_update_apply.py tests/test_software_update_privacy.py tests/e2e/test_github_release_update_e2e.py tests/ui/test_app_window.py tests/updater/test_staging_handoff.py tests/updater/test_broker_balanced.py tests/updater/test_updater_main.py tests/updater/test_state_machine.py
cd ..
git diff --check
```

- [ ] **Step 9: Commit exactly RT6 files and request independent review.**

```cmd
git add launcher/src/neko_launcher/infrastructure/software_update_authority_admission.py launcher/src/neko_launcher/infrastructure/software_update_apply.py launcher/src/neko_launcher/infrastructure/software_update_stage.py launcher/src/neko_launcher/infrastructure/software_update_pending_store.py launcher/src/neko_launcher/application/software_update_coordinator.py launcher/src/neko_launcher/bootstrap/app_factory.py launcher/src/neko_launcher/ui/app_window.py launcher/src/neko_launcher/updater/main.py launcher/src/neko_launcher/updater/broker.py launcher/src/neko_launcher/updater/staging_handoff.py launcher/src/neko_launcher/updater/state_machine.py launcher/tests/test_software_update_authority_admission.py launcher/tests/test_software_update_coordinator.py launcher/tests/test_software_update_composition.py launcher/tests/test_software_update_service.py launcher/tests/test_software_update_stage.py launcher/tests/test_software_update_pending_store.py launcher/tests/test_software_update_apply.py launcher/tests/test_software_update_privacy.py launcher/tests/e2e/test_github_release_update_e2e.py launcher/tests/ui/test_app_window.py launcher/tests/updater/test_staging_handoff.py launcher/tests/updater/test_broker_balanced.py launcher/tests/updater/test_updater_main.py launcher/tests/updater/test_state_machine.py
git commit -m "feat: admit authenticated authority before staging"
```

**Review:** C0/I0; reviewer must verify durable state is written before any `SoftwareUpdateStageService.stage()` download, stage itself rejects non-admitted authority before any I/O, admission never creates PREPARING/transaction/incoming state, admission-only helper completion never invokes activation, direct-online `prepare()`/UI fallback cannot bypass durable admission/pending, stage honors `retry_staging=true`, pending bytes bind exactly to admitted high-water/observed authority, helper re-verifies the envelope, and exact observed-unfailed authority remains retryable after stage failure.

---

## Task RT7: Enroll Fresh Baseline From Exact Embedded Signed Envelope

**Files:**
- Create: `launcher/src/neko_launcher/bootstrap/baseline_enrollment.py`
- Modify: `launcher/src/neko_launcher/updater/enrollment.py` only to expose/reuse the existing enrollment primitive needed by the orchestrator without changing state-transition semantics
- **Do not modify:** `launcher/src/neko_launcher/updater/state_machine.py`
- Create: `launcher/tests/test_baseline_enrollment.py`
- Modify: `launcher/tests/updater/test_enrollment.py`
- Regression only: `launcher/tests/updater/test_state_machine.py`

**State-machine boundary:** RT7 must use the existing enrollment/state transition contract. If the RED tests prove the current transition contract cannot represent authenticated signed-baseline enrollment required by Spec Revision 3.4, STOP with `BASELINE_ENROLLMENT_CONTRACT_BLOCKED` and revise the architecture/implementation plan before any change to `state_machine.py`. The RT7 implementer is not authorized to expand the state-machine contract opportunistically.

**Interface:**

**Interface contract:** `enroll_baseline_from_signed_envelope(*, install_root: Path, envelope_path: Path, trust_profile: VerifiedUpdateTrustProfile) -> BaselineEnrollmentResult`, where `BaselineEnrollmentResult` contains `enrolled: bool`, `binding: AuthenticatedReleaseBinding | None`, and `error: str | None`. The function accepts no raw public-key mapping and no sequence/release_id/version authority parameters outside the signed envelope. It verifies the release envelope only with `trust_profile.release_public_keys` and writes enrollment marker pins from that same verified profile (`profile_id`, `profile_envelope_sha256`, `keyset_sha256`).

- [ ] **Step 1: Build a test fixture with exact temporary installed files and a test-signed `release-v2` envelope whose Launcher/Updater/Core identities match those bytes.**

- [ ] **Step 2: Write the complete RT7 RED set before implementation:** offline happy path with no network authority; exact rerun idempotence; bad signature; unknown key; wrong channel/protocol; wrong Launcher/Updater/Core identity; malformed envelope; and pre-existing same-sequence conflicting binding.

```python
def test_offline_baseline_enrollment_commits_signed_identity(tmp_path):
    install, envelope, verified_profile = make_matching_install_and_envelope(tmp_path, sequence=8)
    result = enroll_baseline_from_signed_envelope(
        install_root=install,
        envelope_path=envelope,
        trust_profile=verified_profile,
    )
    assert result.enrolled
    selected = load_selected_state(install / "state", verified_profile.release_public_keys)
    assert selected.enrollment_complete is True
    assert selected.committed.binding.release_sequence == 8
    assert selected.highwater == selected.committed.binding
    assert selected.observed == selected.committed.binding
    assert selected.failed is None
```

- [ ] **Step 3: Run RED because the baseline enrollment orchestrator does not exist.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_baseline_enrollment.py -q
```

Expected RED: import/name failure for `enroll_baseline_from_signed_envelope` or the new happy-path contract; unrelated fixture/environment failures do not count.

- [ ] **Step 4: Implement exact trust-profile binding + envelope verification + Launcher/Updater/Core identity checks, then construct enrollment marker/state using existing enrollment/state serializers.** Require the profile already verified under RT1's Profile Authority root, use only its release keyset for `release-v2`, and persist the exact profile id/profile-envelope SHA/keyset SHA in the marker before state becomes enrolled. The completed baseline IDLE state must set `committed=<verified generation>`, `highwater=<verified binding>`, `observed=<same verified binding>`, `failed=None`, and retain the exact signed release envelope in evidence under its payload SHA so RT3's production identity invariant `observed == highwater` is true from first enrollment.

Do not accept sequence/release_id/raw-key/profile-path arguments from Installer/build metadata. Sequence/release_id come only from the verified release envelope; profile trust comes only from the verified fixed-path trust profile.

- [ ] **Step 5: Run focused GREEN + updater enrollment/state-machine regression after implementing only the complete Step 2 contract while preserving state-machine monotonicity and durable slot writes. The state-machine test is regression evidence only; no production state-machine file is in this task diff.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_baseline_enrollment.py tests/updater/test_enrollment.py tests/updater/test_state_machine.py tests/updater/test_slot_selector.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/bootstrap/baseline_enrollment.py src/neko_launcher/updater/enrollment.py tests/test_baseline_enrollment.py tests/updater/test_enrollment.py
cd ..
git diff --check
```

- [ ] **Step 6: Assert `git diff --name-only TASK_BASE_SHA..HEAD` does not contain `launcher/src/neko_launcher/updater/state_machine.py`; if it does, STOP/revert RT7 and return to plan revision.**

- [ ] **Step 7: Commit.**

```cmd
git add launcher/src/neko_launcher/bootstrap/baseline_enrollment.py launcher/src/neko_launcher/updater/enrollment.py launcher/tests/test_baseline_enrollment.py launcher/tests/updater/test_enrollment.py
git commit -m "feat: enroll signed v5.1.2 baseline offline"
```

**Review:** C0/I0; Sol-high escalation only if reviewer identifies a genuine enrollment transition/trust conflict.

---

## Task RT8: Wire Exact Baseline Envelope Into Installer Build/First Enrollment

**Files:**
- Modify: `installer/scripts/build_beta_installer.py`
- Modify: `installer/beta.iss`
- Modify: `launcher/src/neko_launcher/main.py`
- Modify: `launcher/tests/test_build_beta_installer.py`
- Modify: `launcher/tests/test_main.py`

**Enrollment invocation contract:** add one internal command mode `NekoLauncher.exe --enroll-baseline`. It accepts no sequence, release_id, key, channel, profile, trust-root, or arbitrary path argument. It resolves the expected install root, reads exactly `<install_root>\trust\update-profile-v1.json` through RT1's fixed-path signed-profile loader and exactly `<install_root>\baseline\release-v2.json`, then calls RT7 with that `VerifiedUpdateTrustProfile`. It returns exit 0 only on verified enrollment/idempotent exact state and exits without constructing the normal UI. This is not a proof/user trust switch.

- [ ] **Step 1 — Builder/tamper RED:** write builder tests for required build-time inputs `--baseline-envelope <path>` **and** `--trust-profile <path>`, byte-identical staging to `baseline\release-v2.json` and `trust\update-profile-v1.json`, `embedded_envelope_sha256`, `embedded_trust_profile_sha256`, `profile_id`, `keyset_sha256`, Profile Authority signature verification, and one-byte tamper rejection for either file **before any builder/ISS change**. These builder arguments are controller/build inputs only; no packaged runtime command accepts them.

```python
def test_builder_requires_signed_baseline_envelope(tmp_path):
    with pytest.raises(SystemExit):
        run_builder_without_baseline_envelope(tmp_path)
```

- [ ] **Step 2: Run the builder/tamper RED set.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_build_beta_installer.py -q
```

Expected RED: the builder does not require/stage/hash the exact envelope and tamper detection is absent.

- [ ] **Step 3 — Builder implementation:** add exactly build-time `--baseline-envelope <path>` and `--trust-profile <path>`; verify the trust profile under the approved Profile Authority public root, require its channel/profile contract, stage exact bytes at `baseline\release-v2.json` and `trust\update-profile-v1.json`, hash after copy, require input/staged byte equality, and record `embedded_envelope_sha256`, `embedded_trust_profile_sha256`, `profile_id`, and `keyset_sha256`. Do **not** change `beta.iss` yet.

- [ ] **Step 4: Run builder GREEN.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_build_beta_installer.py -q
```

- [ ] **Step 5 — Command-mode RED:** write `tests/test_main.py` cases for `--enroll-baseline`: fixed `{app}\trust\update-profile-v1.json` + `{app}\baseline\release-v2.json`, Profile Authority verification before release verification, exact marker profile/keyset pins, no UI construction, success/idempotence exit 0, verification/conflict nonzero, and rejection of extra trust/profile/key/sequence/release/path arguments.

- [ ] **Step 6: Run command-mode RED before changing `main.py`.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_main.py -q
```

Expected RED: `--enroll-baseline` is not recognized or violates fixed-path/no-UI assertions.

- [ ] **Step 7 — Command-mode implementation:** implement only the internal `--enroll-baseline` dispatch in `main.py` by calling RT7; do not duplicate envelope/state verification.

- [ ] **Step 8: Run command-mode GREEN.**

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_main.py tests/test_baseline_enrollment.py -q
```

- [ ] **Step 9 — ISS integration RED:** while `beta.iss` is still unchanged, add an integration assertion in `tests/test_build_beta_installer.py` that the generated/checked installer script must install exact `trust\update-profile-v1.json` to `{app}\trust\update-profile-v1.json` and exact `baseline\release-v2.json` to `{app}\baseline\release-v2.json`, invoke exactly `{app}\NekoLauncher.exe --enroll-baseline` only after both files and component bytes are in place, and suppress normal launch on nonzero enrollment. Run it RED.

```cmd
.venv\Scripts\python.exe -B -m pytest tests/test_build_beta_installer.py -q
```

Expected RED: current `beta.iss` lacks the exact install/invocation/fail-closed contract.

- [ ] **Step 10 — ISS implementation:** update `beta.iss` only after Step 9 RED to satisfy that exact contract. Do not pass unsigned sequence/release_id/trust/profile inputs; the command discovers both authority files only from their fixed installed paths.

- [ ] **Step 11: Run full GREEN + RT7/main tests/Ruff/diff check.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_build_beta_installer.py tests/test_baseline_enrollment.py tests/test_main.py -q
.venv\Scripts\ruff.exe check src/neko_launcher/main.py tests/test_main.py tests/test_build_beta_installer.py ../installer/scripts/build_beta_installer.py
cd ..
git diff --check
```

- [ ] **Step 12: Commit.**

```cmd
git add installer/scripts/build_beta_installer.py installer/beta.iss launcher/src/neko_launcher/main.py launcher/tests/test_build_beta_installer.py launcher/tests/test_main.py
git commit -m "feat: embed and enroll signed baseline authority"
```

**Review:** C0/I0.

---

## Task RT9: Fix `verify-core-install.ps1` For The Real Array Manifest

**Files:**
- Modify: `installer/scripts/verify-core-install.ps1`
- Create: `launcher/tests/test_verify_core_install_script.py`; generate Core manifest/files under pytest `tmp_path` so the test owns the exact array-schema bytes and no static fixture directory is required.

- [ ] **Step 1: Write a functional RED test that creates a temporary valid Core tree with `files` as an array and invokes Windows PowerShell.**

```python
def test_real_array_manifest_verifies_successfully(tmp_path):
    core = make_core_fixture_with_array_manifest(tmp_path)
    proc = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(VERIFY_SCRIPT),
            "-CoreDir", str(core),
            "-ExpectedCommit", EXPECTED_COMMIT,
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 2: Run only that test and confirm current script fails with the known array/property-map behavior (historically exit 6).**

- [ ] **Step 3: Add RED tests for missing file, wrong size, wrong SHA-256, wrong source commit, duplicate/unsafe path, malformed/non-array `files`, v2ray pin mismatch, missing protected `runtime-settings.nkps`, and prohibited plaintext key/settings material.**

- [ ] **Step 4: Run the complete new verifier test set RED before changing the PowerShell.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_verify_core_install_script.py -q
```

Expected RED: the valid array-schema case fails with the existing property-map behavior (historically exit 6) and/or one of the strict new malformed/path cases is not yet rejected as specified.

- [ ] **Step 5: Replace `.PSObject.Properties` enumeration with strict array-entry validation. Each entry must be an object containing exactly allowed path/size/sha256 fields with a safe relative path.**

Representative PowerShell shape:

```powershell
if (-not ($manifest.files -is [System.Array]) -or $manifest.files.Count -le 0) {
    Write-Output "FAIL: manifest files must be a non-empty array"
    exit 6
}
foreach ($entry in $manifest.files) {
    $path = [string]$entry.path
    $expectedSize = [int64]$entry.size
    $expectedSha = ([string]$entry.sha256).ToLowerInvariant()
    # validate safe relative path, then Test-Path/Length/Get-FileHash
}
```

- [ ] **Step 6: Run all verifier functional tests GREEN.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_verify_core_install_script.py -q
```

- [ ] **Step 7: Run the fixed script against the exact historical v5.1.2 payload path recorded by the read-only audit and require exit 0 for those valid Core bytes. If the recorded local payload is unavailable at execution, record `HISTORICAL_PAYLOAD_EVIDENCE_MISSING` and STOP RT9 acceptance until the exact payload evidence is restored or the plan is explicitly revised; do not silently skip this evidence. Do not publish/rebuild anything here.**

- [ ] **Step 8: Run Ruff for the Python test and `git diff --check`.**

- [ ] **Step 9: Commit.**

```cmd
git add installer/scripts/verify-core-install.ps1 launcher/tests/test_verify_core_install_script.py
git commit -m "fix: verify real core manifest array schema"
```

**Review:** C0/I0, with specific path-traversal/schema-strictness review.

---

## Task RT10: Runtime Workstream Acceptance

**Files:** no new production behavior; acceptance only.

- [ ] **Step 1: Run the explicit RT0–RT9 touched-test matrix.**

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34\launcher
.venv\Scripts\python.exe -B -m pytest tests/test_update_trust_profile.py tests/test_build_update_trust_profile.py tests/test_assemble_release_v2_envelope.py tests/test_verify_v512_k1_acceptance.py tests/test_updater_trust_feasibility.py tests/test_update_channel_profile.py tests/test_github_release.py tests/test_github_asset_downloader.py tests/test_github_release_binding.py tests/test_authenticated_release_identity.py tests/test_software_release_identity.py tests/test_software_update_composition.py tests/test_pending_update_bootstrap.py tests/test_software_update_models.py tests/test_software_update_policy.py tests/test_software_update_v2_adapter.py tests/test_software_update_service.py tests/test_software_update_coordinator.py tests/test_software_update_authority_admission.py tests/test_software_update_stage.py tests/test_software_update_apply.py tests/test_software_update_privacy.py tests/test_software_update_pending_store.py tests/e2e/test_github_release_update_e2e.py tests/ui/test_app_window.py tests/test_baseline_enrollment.py tests/test_build_beta_installer.py tests/test_main.py tests/test_verify_core_install_script.py tests/updater/test_enrollment.py tests/updater/test_slot_selector.py tests/updater/test_staging_handoff.py tests/updater/test_broker_balanced.py tests/updater/test_updater_main.py tests/updater/test_state_machine.py -q
```

- [ ] **Step 2: Run the exact runtime acceptance Ruff/diff commands.**

```cmd
.venv\Scripts\ruff.exe check ../scripts/build_update_trust_profile.py ../scripts/assemble_release_v2_envelope.py ../scripts/verify_v512_k1_acceptance.py src/neko_launcher/updater/trust.py src/neko_launcher/updater/trust_profile.py src/neko_launcher/application/software_update_models.py src/neko_launcher/application/software_update_policy.py src/neko_launcher/application/software_update_service.py src/neko_launcher/application/software_update_coordinator.py src/neko_launcher/infrastructure/update_channel_profile.py src/neko_launcher/infrastructure/github_release.py src/neko_launcher/infrastructure/github_asset_downloader.py src/neko_launcher/infrastructure/github_release_binding.py src/neko_launcher/infrastructure/software_release_identity.py src/neko_launcher/infrastructure/authenticated_release_identity.py src/neko_launcher/infrastructure/software_update_v2.py src/neko_launcher/infrastructure/software_update_authority_admission.py src/neko_launcher/infrastructure/software_update_apply.py src/neko_launcher/infrastructure/software_update_stage.py src/neko_launcher/infrastructure/software_update_pending_store.py src/neko_launcher/bootstrap/app_factory.py src/neko_launcher/bootstrap/pending_update_bootstrap.py src/neko_launcher/bootstrap/baseline_enrollment.py src/neko_launcher/main.py src/neko_launcher/ui/app_window.py src/neko_launcher/updater/main.py src/neko_launcher/updater/broker.py src/neko_launcher/updater/staging_handoff.py src/neko_launcher/updater/state_machine.py tests ../installer/scripts/build_beta_installer.py
cd ..
git diff --check
```

- [ ] **Step 3: Re-verify immutable K1 acceptance before accepting the runtime workstream.** First run the Git-only **RT1 security-tool immutability guard** and require the exact five RT1 security paths to remain byte-identical to `RT1_CODE_HEAD`. Then validate the tracked acceptance record's single-introduction Git history, exact evidence SHA, exact K1A public-custody SHAs, exact `K1B_CUSTODY_SHA256`, all referenced K1B-A profile and K1B-B artifact/proof-envelope custody, and `RT1_CODE_HEAD` ancestry.

```cmd
cd /d E:\Github\worktrees\Neko-Family-Proxy-v5.1.2-r34
launcher\.venv\Scripts\python.exe -B -c "import json,subprocess,sys; p=r'docs/superpowers/evidence/v512-k1-acceptance.json'; paths=[r'scripts/build_update_trust_profile.py',r'scripts/assemble_release_v2_envelope.py',r'scripts/verify_v512_k1_acceptance.py',r'launcher/src/neko_launcher/updater/trust.py',r'launcher/src/neko_launcher/updater/trust_profile.py']; cs=subprocess.check_output(['git','log','--format=%H','--',p],text=True).splitlines(); (len(cs)==1) or sys.exit('K1 acceptance record history is not single-introduction'); c=cs[0]; subprocess.run(['git','diff','--exit-code',c,'--',p],check=True); r=json.loads(subprocess.check_output(['git','show',f'{c}:{p}'],text=True)); h=r['rt1_code_head_sha']; subprocess.run(['git','merge-base','--is-ancestor',h,'HEAD'],check=True); late=subprocess.check_output(['git','log','--format=%H',f'{h}..HEAD','--',*paths],text=True).splitlines(); (not late) or sys.exit('RT1 security paths changed after accepted RT1_CODE_HEAD'); subprocess.run(['git','diff','--exit-code',h,'--',*paths],check=True); print('RT1_SECURITY_TOOL_GUARD_OK',c,h)"
launcher\.venv\Scripts\python.exe -B scripts\verify_v512_k1_acceptance.py --repo-root . --acceptance-record docs\superpowers\evidence\v512-k1-acceptance.json --evidence docs\superpowers\evidence\v512-updater-trust-feasibility.md --k1b-custody E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json --require-git-immutability
```

Any missing/modified/mismatched K1 acceptance input blocks RT10; acceptance may not reconstruct or replace it.

- [ ] **Step 4: Re-run repository safety after runtime acceptance because RT1/RT8 touch packaged routing/install behavior.**

```cmd
launcher\.venv\Scripts\python.exe -B scripts\check_repository_safety.py
```

- [ ] **Step 5: Record exact `BASE_SHA`, `HEAD_SHA`, test counts/results, each accepted task commit/review verdict, `RT1_CODE_HEAD`, `K1_ACCEPTANCE_COMMIT`, and `K1B_CUSTODY_SHA256`.**

- [ ] **Step 6: Independent `ag/gemini-pro-agent` workstream review against Spec Revision 3.4 + this plan. Required verdict: Critical 0 / Important 0.**

- [ ] **Step 7: If C/I findings exist, reopen the owning RT task; do not patch acceptance task directly. Re-run acceptance after remediation/re-review.**

- [ ] **Step 8: Mark workstream `RUNTIME_TRUST_C0_I0` only after all above pass.**

This workstream acceptance still does not authorize production signing, public repository creation, tag mutation, release upload, or deletion.
