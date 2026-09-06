# Neko Family 5.1 — Phase-3 transactional live update

- Date: 2026-09-06.
- Status: **PROPOSED / BLOCKED_AT_ARCHITECTURE_GATE**.
- Scope: Launcher `release/5.1`, coordinated narrow Core adaptation, existing Admin development branch for controlled Core grant authorization and storage adapter.
- Owner has authorized design and routine development checkpoints, **not implementation of this spec yet**. Written-spec approval, production authorization, and public release are separate gates.
- Design method: Superpowers architectural brainstorming; existing code inspected, alternatives compared, full spec followed by independent review. Owner requested one consolidated approval package rather than incremental questions.
- Primary design input: GPT-5.6 Sol High (Ultra request returned HTTP503), followed by front-agent reconciliation against source. Review acceptance is recorded separately against the exact final document hash. No implementation or E2E success is claimed here.

## 1. Decision and architecture

Use a stable external `NekoUpdater.exe` broker and **complete immutable release generations**, not in-place replacement of two independent paths. A durable two-slot state record selects exactly one Launcher/Core pair. Candidate process self-test and reversible activation precede the final committed selection. Old generation remains intact for rollback. Normal shortcuts invoke the stable broker, so recovery does not depend on a healthy replaceable Launcher.

```text
 Owner-controlled signing                         Runtime Config / permit
 exact release payload + Ed25519                   separate existing authority
             |                                                 |
 Admin manifest + artifact-grant                           normal Launcher only
             | HTTPS, bounded, no redirects                     |
 running Launcher ----BEGIN/READY; changed downloads--> incoming/<request>
             | private process-bound apply request              |
             v                                                  |
 stable NekoUpdater (no network, no Proxy authority)              |
   | lock root; verify signature/files; construct full generation|
   | ask Launcher to quiesce; wait exact owned process family    |
   | launch candidate in bounded credential-free probation      |
   |<-------------------- self-test result ---------------------|
   | durable COMMITTED slot -> permit normal startup             |
   |                                                            |
   +-- state slots A/B select ONE releases/<generation>           |
   |       +-- NekoLauncher.exe                                   |
   |       +-- ProxyCore/ entire canonical bundle ----------------+
   +-- previous complete generation (rollback, no network)
   +-- incomplete candidate -> rollback/cleanup; never mixed pair
```

`NekoUpdater.exe` is trusted manual-bootstrap code, not a third unsigned release component. It is **not auto-updated in Phase 3**. Incompatible helper protocol requires a new manually authenticated bootstrap, not an updater self-overwrite trick.

Generation switch means installed Launcher executable changes at a new path; the old running EXE is never overwritten. Disk may contain old and new generations simultaneously, but only one full compatible generation is authorized to run.

## 2. Verified baseline and real gaps

At discovery:

| Component | Verified revision / role |
|---|---|
| Launcher | `9cfeca79b160717e0624cfd0259f29f5050f8c82`, `release/5.1`, `5.1.0a2`; PR5 OPEN/DRAFT/CLEAN, relevant CI successful |
| Admin | `91c2eedeb5f460fb82c3ad36e01ccff2c97e62d7`, `feature/software-update-phase2-control-plane`; PR3 OPEN/DRAFT/CLEAN |
| Core public main | `77b849f660a6ce923715eb5254594e4d0ee99ec3` |
| Canonical a43 fixture source | `6ab94bb8fde80a5c675b39b6884c6d31db218dad` |

Fresh Phase-2 verification: Launcher 1239 passed / 3 skipped / 0 failed; full Ruff and repository-safety pass; Admin standalone build and 115 tests pass. An intermediate extra Tk-display skip was followed by focused 5/5 and final full 1239/3; not silently counted as a pass. Fresh packaged a2 no-login/no-START smoke proves real window, version, update-unavailable isolation, WAITING_FOR_GAME, exact parent/child normal exit and `_MEI` cleanup. It is not update E2E.

Preserved a2 candidate: `E:\Github\artifacts\phase2\5.1.0a2-candidate\NekoLauncher.exe`, SHA-256 `fcd76f78bfce724f7f77719df0ca8e5a34832fbb59f426b15d4bbbe694635eaf`, 30,479,674 bytes. No version bump for this document.

Source constraints:

- `launcher/NekoLauncher.spec`: PyInstaller onefile, `uac_admin=False`, assets embedded, `runtime_tmpdir=None`. Bootloader parent and Python child both matter.
- `launcher/src/neko_launcher/main.py`: imports app factory before main; current mutex then Tk, finally `os._exit`. New safe entry dispatch must precede these imports.
- `launcher/src/neko_launcher/bootstrap/single_instance.py`: current named-object existence check is not an acquired transaction mutex. Do not reuse it as the update lock.
- `launcher/src/neko_launcher/infrastructure/config.py`: fixed `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore` is current runtime location; new bootstrap must select generation-relative Core through validated broker composition, not arbitrary env override.
- `launcher/src/neko_launcher/bootstrap/app_factory.py`: update identity is still sequence0/dev-unpublished and public-key registry empty. Neither is installed-state authority.
- `launcher/src/neko_launcher/application/software_update_policy.py`: current equal-sequence check compares component identities; Phase 3 adds exact payload/release-id binding.
- `launcher/src/neko_launcher/infrastructure/core/core_process.py`: retain existing exact-owned Core spawn/control and kill-on-close job semantics. Do not transfer Proxy authorization to updater.
- Core `NekoProxyCore.Legacy/NetchRuntimeBootstrap.cs:18-21,56-59` changes CWD and creates `logging` in bundle; `NekoProxyCore.Host/Program.cs:45-48` uses BaseDirectory protected payload. This is an actual immutable-runtime gap, not hypothetical. Narrow Core write-root separation is required after approval.
- Core `NekoProxyCore.Host/NekoProxyCore.Host.csproj` embeds protected-settings key at approved build time and stages protected payload. Software-update private signing keys are a different authority. Do not falsely claim every key-like byte is absent from admitted Core; never extract or report protected key contents.
- No installer source was found in `E:\Github\NekoBetaInstaller` (out/payload/log only). Do not infer customer privilege support from historical Netch manifest.
- Existing `launcher/src/neko_launcher/e2e/final_windows_harness.py` has permissive legacy admission; new production validator must not adopt its fallback.

Canonical fixture remains **untouched** at `E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core`. All 1,022 mapped files rehashed, 371,717,577 bytes, zero mismatches. Manifest SHA-256 `d39f43c75ac84fa3189f93f935dd30b6538ee76b3c817652d711451c3f15b59a`; EXE SHA-256 `1b9b0ba313ac1f8c879f07f678a2f01e5b334c29fc17323533017aed2cbffcfe`. New adapted Core must receive a separately admitted inventory; this fixture is reference evidence, not silently replaced to make tests pass.

## 3. Trust, threat model, support and UAC

Release authenticity = embedded Ed25519 public keys and exact signed payload bytes. HTTPS/grant is transport only. Local checksums detect tears, not hostile alteration. IDs/PIDs/path strings are not capability authority. Runtime Config/permits never select update files or public keys.

Supported first layout: Windows x64, local fixed NTFS volume, per-user unelevated install at `FOLDERID_UserProgramFiles\NEKO FAMILY`. Resolve KnownFolder through Windows API, not inherited environment. Root derived from OS-reported helper image path and required exact KnownFolder child; no `--root`, registry/config root override or arbitrary destination. Require current-user ownership and protected DACL permitting current user and SYSTEM, no other unprivileged write/delete/WRITE_DAC. Validate ancestors/volume/final handles. Reject UNC, remote/removable, non-NTFS, cross-volume, reparse, other-user, Program Files/system paths and elevated tokens. Both helper and Launcher asInvoker. Driver installation/elevation remains manual outside update. If supported Core requires elevation, this layout is unsupported until a separately approved privilege design; do not insert `runas` or service workaround.

Source-mode updates disabled. Sandbox uses separately built test composition with fixed E:\Github root and injected test public key; production has no environment bypass. Signing tests use ephemeral keys **in memory only**, no private-key files or logged key bytes. Bootstrap is an Owner-authenticated helper checksum/distribution plus signed initial release; helper trust cannot originate in writable unsigned JSON. No claim of protection against a malicious administrator/kernel or arbitrary code already controlling the same Windows user (which can replace the trusted helper). No elevation amplifies local writes. Network/untrusted artifacts, accidental corruption, hostile filenames and path races are explicitly covered.

Recoverability fault model: arbitrary process kill/reboot/power interruption at every mutation, successful file flush honored, filesystem volume and at least one acknowledged committed snapshot plus old generation intact. Under that model recover to **whole new committed or whole old restored**, not an ambiguous runnable installation. Permanent media loss, loss of both valid state slots, malicious rollback of all local state, lying storage or loss of old+new bytes -> `REPAIR_REQUIRED`, no automatic trust reset. Do not market this as unconditional recovery from hardware corruption.

## 4. Layout and ownership

```text
<root>/NekoUpdater.exe                    stable, manually serviced
<root>/bootstrap/{release-envelope.json,launcher.artifact,core.artifact.zip}
<root>/state/control.lock                 permanent inode, never replaced
<root>/state/family.lease                 permanent inode, share-mode liveness
<root>/state/enrollment.bin                fixed 16384-byte bootstrap marker
<root>/state/slot-a.bin                    fixed 1048576 bytes
<root>/state/slot-b.bin                    fixed 1048576 bytes
<root>/incoming/<request-id>/             incomplete downloads, not executable
<root>/staging/<transaction-id>/generation/
<root>/releases/<generation-id>/
    release-envelope.json                exact authenticated envelope
    NekoLauncher.exe
    ProxyCore/canonical-core-manifest.json
    ProxyCore/...                        exact complete canonical inventory
<mutable KnownFolder LocalAppData>/NEKO FAMILY/
    update-logs/                         safe bounded codes only
    update-runtime/<generation-id>/       runtime log/scratch, no release authority
    ... existing preferences/auth storage (outside updater scope)
```

Generation ID is computed locally as `g-` + 20-digit zero-padded sequence + `-` + exact payload SHA256. Transaction/request ID = 32 lowercase hex random non-secret correlation. Never use signed release/artifact id as a path. Fresh exclusive-create transaction directories; IDs cannot select pre-existing unrelated content. Bootstrap/state directories must be enrolled before normal use; missing slots on an existing root are repair-required, never implicit reset to sequence0.

Immutable inventory contains protected payload as already approved Core distribution, not mutable Runtime Config/cache/logs. No copying live credentials into backups. Core remains a separately delivered component, not embedded in Launcher EXE or automatically published in public Launcher GitHub artifacts; `docs/current/runtime-distribution.md` distribution restrictions still apply. Local complete-generation layout does not grant public distribution authority.

## 5. Exact signed contract and compatibility

Keep Phase-2 envelope v1 unchanged: exact `envelope_version:1`, `key_id`, `payload_b64`, `signature_b64`, strict base64, 32-byte allowlisted public keys, 64-byte signature, verification of decoded bytes BEFORE UTF8/JSON payload. key_id is ASCII `[A-Za-z0-9._-]{1,64}`. Envelope bound 65,536 bytes; payload 49,152. Add duplicate-key detection at envelope/payload parsing boundaries, not after keys have already collapsed into a mapping.

Proposed **payload schema v2** deliberately rejects v1 for installation; Phase2 v1 detection remains separate. The first actual updater bootstrap uses v2. No v1 field is silently reinterpreted.

```text
ReleaseV2 = {
 schema_version: 2,
 channel: "beta",
 release_sequence: integer 1..9223372036854775807,
 release_id: ASCII /[A-Za-z0-9._-]{1,64}/,
 mandatory: boolean,
 minimum_supported_sequence: integer 1..release_sequence,
 updater_protocol: {minimum: integer 1..65535, maximum: integer minimum..65535},
 components: {launcher: LauncherComponent, core: CoreComponent}
}
Component common = {
 version: ASCII /[A-Za-z0-9._+-]{1,64}/,
 artifact_id: ASCII /[A-Za-z0-9._-]{1,96}/,
 artifact_sha256: lowerhex64,
 artifact_size: positive bounded integer,
 installed_identity_sha256: lowerhex64,
 artifact_format: fixed enum below
}
LauncherComponent: artifact_format="raw-pe-v1", size<=134217728;
 artifact_sha256 MUST equal installed_identity_sha256.
CoreComponent: artifact_format="zip-core-v1", size<=1073741824;
 installed_identity_sha256 = SHA256(exact canonical manifest bytes), not ZIP SHA.
```

All object key sets closed, missing/duplicate/unknown keys rejected recursively, no bool-as-int, float/exponent integer/coercion/nonfinite/UTF8 BOM/trailing JSON/invalid UTF8/lone surrogate. Release schema2 helper protocol1 must lie within signed range. Complete exact pair is compatibility authority; Core also obeys fixed runtime profile `zip-core-v1`/protocol1 defined here. Requiring a different native driver, helper, ABI or architecture needs a different reviewed profile/protocol and manual bootstrap if unsupported; version labels alone do not prove compatibility. Publishing authority must test exact pair. No separate component latest lookup.

A new sequence with unchanged component identities is allowed metadata-only; verify both local components, no download, same transaction/self-test/commit. Same-sequence exact payload => latest unless suppressed; same sequence but different payload or release id => conflict even if file identities equal.

## 6. Core inventory/package profile

Preserve canonical exact-byte inventory format observed in a43, rather than inventing ZIP hash as installed identity. Closed top fields: `source_commit`, `candidate`, `authority`, `file_count`, `total_bytes`, `neko_proxy_core_exe_hash`, `neko_proxy_core_dll_hash`, `protected_settings_payload_hash`, `redirector_bin_hash`, `nfapi_dll_hash`, `v2ray_sn_exe_hash`, `security`, `files`.

- `source_commit`: lowercase hex 7..40; evidence label only, not Git trust.
- `candidate`: ASCII version grammar above; `authority`: ASCII `[A-Za-z0-9._-]{1,64}`; label not trust. Production admission may not silently promote a synthetic-non-production fixture.
- `file_count`: integer1..8192 equal map cardinality. `total_bytes`: integer1..1073741824 equal actual mapped bytes. Manifest<=8MiB; `files` path->lowerhex64, excludes itself.
- Hash fields map exactly to `NekoProxyCore.exe`, `NekoProxyCore.dll`, `runtime-settings.nkps`, `bin/Redirector.bin`, `bin/nfapi.dll`, `bin/v2ray-sn.exe`; require map values and actual bytes match each.
- `security`: exact integer0 fields `runtime_settings_key_files`, `plaintext_settings_files`, `plaintext_secret_marker_hits`, and booleanfalse `external_dotnet_dependency`. These are assertions, not scanner authority.
- All mapped files must exist and hash; actual files must equal map plus manifest. Directories are only ancestors implied by files, no extra empty directories. No arbitrary files exempted as logs.
- Runtime admission rejects standalone `runtime-settings.key`, plaintext `settings.json` (case-insensitive leaf names), links/ADS and unlisted entries; verifies required self-contained runtime files and Core preflight. Build/security gate additionally runs the existing protected-payload/content privacy validation with synthetic secret markers, no real secret print/export. Do not claim a generic byte scanner can prove no arbitrary embedded secret. Exact inventory/signature is the code authority; the build/review gate owns semantic privacy.

ZIP entries: STORE/DEFLATE only, no encryption, multipart, symlink/device/reparse/Unix special entries. Reject mismatched central/local names, methods, flags, sizes (data-descriptor sizes resolved and checked), overlaps, duplicate/case-equivalent names, CRC mismatch, trailing appended payload not part of valid ZIP structure. No executable extraction before complete archive SHA/size verification. No `extractall`.

Limits: <=8193 regular entries including manifest, <=8192 mapped files, manifest<=8MiB, total expanded payload<=1GiB plus manifest, individual file<=256MiB, actual expansion<=200:1 per file and aggregate (empty compressed zero-byte file handled as zero-size only). Streaming counters enforce limits regardless of headers. Paths are relative POSIX ASCII printable with segments restricted to `[A-Za-z0-9._ ()'-]+`, no backslash/colon/NUL/wildcards/control, no empty/dot/dotdot segment, no leading/trailing segment spaces or dots; <=240 UTF16 units relative, <=120 per segment, <=16 segments. Reject reserved Win32 device names (including extension forms, CLOCK$, CONIN$, CONOUT$, COM/LPT variants); non-ASCII rejected, so superscript reserved variants cannot pass. Case-insensitive ordinal uniqueness, file/directory-prefix collisions, and OS-reported 8.3 alias collisions rejected. Header directory entries permitted only for implied ancestors and never counted as mapped files. Read-only grammar check found canonical parentheses/apostrophes; the explicit grammar above includes them. Test all untouched a43 paths; future failure is spec/profile discrepancy to review, never normalize fixture.

## 7. Windows handle/path discipline

Resolve all root ancestors by opened handle with `FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS` as appropriate, verify tag/attributes, owner/DACL, final volume/file IDs. Retain ancestor handles denying delete/rename through dependent actions. Leaf files regular, single-link, unnamed data only, no reparse/sparse/encrypted/offline/cloud-placeholder attributes. Source artifacts with Zone.Identifier may be read as unnamed stream only and copied fresh; generation destinations never inherit ADS.

Open trusted files denying write/delete sharing, hash the **same retained handle** used for admission. Before create/rename/delete, validate both parents and target identity under retained root; operations must not follow a substituted ancestor. No string startswith containment check or resolve-then-close-then-use. Fixed local paths derived from verified generation or transaction metadata only. Create destinations exclusively; source objects supplied by Launcher never choose destinations or cleanup roots. Mutations use verified same-volume handle-relative operations where available; path-based API only with retained non-renamable ancestors and revalidated leaf identity. All ctypes/native ABI signatures explicit and test 64-bit handles.

Hold generation file read guards denying writes/deletes for its entire managed lifetime; fresh destination not shared/hardlinked with old generation. For spawn: retained EXE guard, explicit absolute image path, quoted fixed argv, no shell/search PATH, suspended create, validate image/file identity, job assignment before resume. Restrict DLL search and child environment to OS necessities plus fixed product runtime locations; no inherited credentials, development PYTHONPATH/plugin injection, network proxy credentials or test-key settings. Handle-list inheritance explicit. Staging EXEs never run except finalized, fully verified probation candidate.

## 8. Durable record: authority is slots, not pointer rename

**Avoid mandatory directory `FlushFileBuffers` assumptions.** Windows does not offer the portable POSIX directory-fsync contract; `REPLACEFILE_WRITE_THROUGH` is unsupported. Therefore no rename of active.json is the commit point. Two pre-created fixed-size slot files store full authoritative state; no separate active pointer can disagree. A generation-directory rename only publishes bytes; selection is a later slot flush. If new directory metadata is absent after interruption, validated old generation is selected in recovery, preserving highwater if commit was durable.

Each slot is exactly1048576 bytes: header magic8 ASCII `NEKOUPD1`; uint32LE body_length (1..1048520); uint32LE format_version1; uint64LE revision(1..9223372036854775807); SHA25632 of header first24 bytes + body; body strict canonical UTF8 JSON (recursive ASCII key lexicographic order; compact comma/colon, no whitespace; strings ASCII-only, escape only quote/backslash as backslash escape and controls as lowercase six-byte unicode escape; integers base10 minimal no leading zero or plus, booleans/null lowercase; no floats; arrays retain order; compare reserialization bytes on read after duplicate rejection); zero-fill remaining bytes. No checksum authentication claim. Body schema below. Do not use mmap/append or replace slot inodes. Fixed files are created and flushed during manual enrollment before updates enabled. Each write overwrites **only older/invalid slot**, complete slot bytes, then checked `FlushFileBuffers`, then reread same handle to validate entire frame. Never truncate/remove/overwrite sole valid newest slot. Abandoned partial older slot ignored. Equal revisions with unequal bodies, impossible transition or unknown format fail closed. Highest valid revision wins, independently of mtime. No valid slot => repair required, not choose highest signed generation on disk. No startup network needed.

Every acknowledged durable transition must have completed write+flush+reread. If write/flush fails, preserve all files, stop dependent actions and recover before normal authorization; failure after mutation is not proof it did not happen. Recovery re-flushes a valid observed record before using it. Filesystem honest-flush premise explicitly required. Slot revisions increase for progress, rollback, cleanup and observation; overflow fail closed.

```text
State = {
 schema_version:1, revision: uint63 positive (matches header),
 installation_id: lowerhex32, helper_protocol:1, enrollment_complete:boolean,
 phase: Phase,
 committed: Generation|null,
 previous: Generation|null,
 highwater: Binding|null,
 observed: Binding|null,
 failed: Binding|null,
 transaction: Transaction|null,
 cleanup: [Cleanup (1..2)]|null,
 rollback: Rollback|null,
 evidence: {payload-sha256: canonical-base64-exact-envelope},
 last_error: ErrorCode|null
}
Binding = {release_sequence:uint63 positive, release_id:release-id, payload_sha256:hex64}
Generation = {binding:Binding, launcher_identity_sha256:hex64, core_identity_sha256:hex64}
Transaction = {
 id:hex32, request_id:hex32, candidate:Generation,
 old:Generation|null, incoming:DirectoryIdentity, staging:DirectoryIdentity|null, stage:"ADMITTED"|"BUILDING"|"VERIFIED"|"QUIESCING"|"PROBATION",
 mutation: {kind:MutationKind, target:Target, status:"INTENT"|"DONE"}|null
}
DirectoryIdentity = {volume_serial:lowerhex16, file_id:lowerhex32, parent_file_id:lowerhex32}
Cleanup = {transaction_id:hex32, request_id:hex32, directory:DirectoryIdentity, target:"incoming"|"staging", status:"INTENT"|"DONE"|"SKIPPED"}
Phase = "ENROLLING"|"IDLE"|"PREPARING"|"QUIESCING"|"PROBATION"|
        "ROLLING_BACK"|"CLEANING"|"REPAIR_REQUIRED"
MutationKind = "CREATE_STAGE"|"WRITE_CANDIDATE"|"PUBLISH_GENERATION"|
               "STOP_OLD"|"START_PROBATION"
Target = "stage"|"generation"|"old_process_family"|"candidate_process_family"
Rollback = {mode:"precommit"|"postcommit", target:Generation, probation_id:hex32, scratch:[Cleanup (0..2)], step:"DRAIN_INTENT"|"DRAIN_DONE"|"RESTORE_INTENT"|"RESTORE_DONE"}
```

Directory identities come from GetFileInformationByHandleEx(FileIdInfo), fixed hex encoding, not child claims. After exclusive directory creation and before any child mutation, persist its file/volume/parent identity. A kill between creation and identity persistence leaves inert unowned scratch: never recursively delete it automatically. On recovery re-open without following reparses and require all identity fields match before traversal/deletion; missing/mismatched identity leaves inert quarantine and a safe IO_FAILED code, not arbitrary deletion. No cleanup can target releases/state/bootstrap/helper/mutable user data.

No free path/file/chunk inventory in journal: partial BUILDING is discarded on failure, rather than resumed file-by-file. Every filesystem sub-operation belongs to durable enclosing INTENT; recovery deletes only identity-proven uncommitted scratch and rolls back, so every individual file mutation is recoverable without enormous journal. Operational journal metadata includes only hashes/IDs/enums/directory identities: no URL/JWT/permit/Runtime Config/credentials/signing material/IPC capability. The closed evidence map is the sole explicit addition: PUBLIC exact signed envelopes only, no artifact grant URLs. It is authentication evidence, not diagnostic metadata. Unknown/duplicate fields rejected. All nullable fields required explicitly.

Invariants: IDLE has committed nonnull, transaction/cleanup/rollback null; enrollment alone permits committed/highwater null. previous is null or differs from committed, has lower sequence and is a prior committed generation. Precommit rollback preserves previous unchanged. Only postcommit rollback selects previous then sets previous=null (retained older directories remain inert); a failed newer generation never becomes the rollback backup. transaction.old equals current committed until commit. observed is greatest admitted candidate sequence binding; highwater greatest **committed** sequence binding. Both monotonically nondecreasing, same-sequence exact binding immutable. `failed` is null or exact observed binding; once a higher observed sequence advances, older failed candidates are below observed and rejected, so unbounded blacklist unnecessary. Rollback reduces committed selection only, never observed/highwater. Every slot is self-contained: evidence contains exactly the distinct bindings referenced by committed/previous/highwater/observed/failed/transaction.candidate/transaction.old/rollback.target (or sole marker-bound initial envelope while ENROLLING), at most six distinct payloads by transition invariants. Each value is canonical base64 of an envelope<=65536 bytes, independently verified with embedded key set and matched to map key, release ID/sequence and Generation component fields. Authenticate and include candidate envelope in the SAME flushed snapshot that first advances observed; never point a durable floor only at staging or a generation directory. On each slot write recompute exact referenced set; other slot retains its own full map, so no external evidence GC is needed. Evidence corruption in a frame-valid higher record is repair-required, not permission to drop floors. Generation envelope copies are convenience; slots retain authentication even if namespace metadata is lost. CRC/hash-valid state pointing to nonmatching signed bytes never launches.

### 8.1 Snapshot selection predicates and legal transitions

Use these predicates in order, never collapse them into "valid":

1. Frame-valid: exact size/magic/version/length/zero padding/checksum/header revision. Torn/absent frame alone permits selecting the other frame.
2. Schema-valid: strict JSON/closed keys/value ranges, matching body revision, all phase invariants and evidence cardinality. A frame-valid but schema-invalid higher/equal frame => REPAIR_REQUIRED, never discard it as a tear.
3. Evidence-authenticated: every referenced binding is backed by this slot's independently verified exact envelope; no extra/missing entries. Failure => REPAIR_REQUIRED, never lower floors.
4. Transition-valid: if both frames structurally present, revisions differ by one (or equal identical initial records only); installation/helper binding fixed, floors monotonic, same-sequence bindings immutable; state change must be one row below. Unexpected gap or equal-but-different => REPAIR_REQUIRED. If the other frame is torn, latest authenticated schema-valid snapshot is sufficient; do not reconstruct unknown history.
5. Generation-complete: independently check bytes/layout against authenticated descriptor. Failure here NEVER discards snapshot/floors. It requests explicit rollback from the highest authenticated snapshot or repair if no backup.
6. Launchable: generation-complete plus root/lock/family proof, supported protocol and successful local probation. Failure rolls back explicitly, not reselect lower slot.

Pairwise slot algorithm is explicit: (a) read both physical slots under guards, classify framing independently; missing slot is enrollment/repair policy in §13.1, not ordinary torn overwrite. (b) With two frame-valid records, BOTH must be schema-valid and evidence-authenticated regardless of their revision ranking; **malformed stale-low also causes REPAIR_REQUIRED**. No adjacency waiver for malformed authenticated history. "Structurally present" means frame-valid; validate schema/evidence first and do not compare invalid objects. (c) If exactly one existing frame is torn, independently valid other snapshot may be selected without adjacency history; if neither valid frame, repair. (d) Two fully authenticated valid frames: equal only when identical revision1 ENROLLING; otherwise require consecutive revisions and legal low->high edge. Nonadjacent/equal unequal/illegal transition => repair. (e) Never discard highest/equal malformed evidence by choosing lower. Generation completeness and live launchability are assessed ONLY after selection and cannot alter that algorithm. These conservative malformed-history repair outcomes are corruption cases outside honest interrupted-write recovery, not permission to silently erase floors. Pairwise acceptance covers valid-high/malformed-low, malformed-high/valid-low, valid nonadjacent, equal unequal, equal initial, one torn, both torn, and missing-slot enrollment boundaries.

Common invariants: committed.sequence<=highwater.sequence<=observed.sequence; null floors only before first commit. failed=null or observed; advancing observed clears failed. transaction.old=committed and candidate.binding=observed, candidate.sequence>old.sequence. previous is lower than committed. Rollback target is committed for precommit and previous for postcommit. No new BEGIN during transaction/rollback/cleanup. `rollback` is nonnull only in ROLLING_BACK; `cleanup` nonnull only in CLEANING; `transaction` nonnull in PREPARING/QUIESCING/PROBATION, or retained frozen during precommit ROLLING_BACK to preserve scratch IDs. Postcommit ROLLING_BACK has transaction=null. Any transition to REPAIR_REQUIRED retains authority/evidence and frozen ancillary fields for diagnosis; no launch or further automatic mutation there. IDLE and CLEANING carry committed authority, never authorize a different generation.

The following is the exhaustive **normal** adjacent-snapshot automaton. An edge INTO INTENT must flush/reread before its operation starts. An edge INTO DONE is written only after that operation has completed and been independently checked. Other edges list their preconditions explicitly; selecting snapshots flush before any NORMAL_AUTH. `INTENT -> DONE` writes acknowledge completion of the exact operation, never infer it from names/mtime. `DONE -> next INTENT` is a separate durable write. Stage changes only as listed. Process death recovery NEVER resumes candidate staging; PREPARING takes pre-quiesce abort then cold-starts unchanged committed after family lease proof, while QUIESCING/PROBATION take rollback edges below. This avoids needing to reconstruct individual writes. Slot-write tears follow predicates above.

| Current -> next snapshot | Operation between intent and done / field changes |
|---|---|
| ENROLLING -> ENROLLING | Fixed marker-bound evidence, null selected/floors/transaction/rollback/cleanup; repeat only fixed bootstrap construction, no progress revision needed |
| ENROLLING -> IDLE(false) | Mandatory initial probation passed; initial committed/highwater/observed, other nullable fields null; enrollment_complete=false |
| IDLE(false) -> IDLE(true) | Enrollment final mirror only, identical authority/evidence, then remote BEGIN enabled |
| IDLE -> PREPARING ADMITTED mutation=null | BEGIN: incoming root already exclusively created; persist exact identity/evidence/new observed, then READY/download; candidate and old/floors fixed thereafter |
| ADMITTED null -> BUILDING CREATE_STAGE/stage INTENT | Durable permission to create stage container; no child writes yet |
| CREATE_STAGE INTENT -> DONE | Exclusive create stage container, capture/persist identity before child writes; crash before identity is inert quarantine |
| CREATE_STAGE DONE -> WRITE_CANDIDATE/stage INTENT | Begin all candidate file create/write/flush/verification inside identity-proven stage; old generation untouched |
| WRITE_CANDIDATE INTENT -> DONE | Every file flushed/verified, exact full inventory; interruption at any subcall rolls back and later removes only owned scratch |
| WRITE_CANDIDATE DONE -> PUBLISH_GENERATION/generation INTENT | Permission to rename stage/generation only to fixed payload-derived release destination |
| PUBLISH_GENERATION INTENT -> DONE (stage VERIFIED) | Final directory publish/revalidation complete; stage container remains as cleanup root, its identity is unchanged |
| PREPARING VERIFIED PUBLISH_GENERATION DONE -> QUIESCING STOP_OLD/old_process_family INTENT | Only idle-safe; send QUIESCE, block START, drain old exact family |
| QUIESCING STOP_OLD INTENT -> DONE | Exact whole old job empty, generation guards may close; no candidate started yet |
| QUIESCING STOP_OLD DONE -> PROBATION START_PROBATION/candidate_process_family INTENT | Candidate suspended/job-bound spawn, HELLO and mandatory credential-free self-test allowed |
| PROBATION START_PROBATION INTENT -> DONE | Mandatory Launcher/Core/Tk tests passed and exact family healthy; candidate still restricted |
| PROBATION START_PROBATION DONE -> CLEANING | Sole commit: committed=candidate, previous=old, highwater=observed, failed=null; copy known scratch identities into queue, clear transaction/rollback atomically; only after flush send NORMAL_AUTH |
| PREPARING -> CLEANING or IDLE (pre-quiesce abort) | Before any durable STOP_OLD INTENT/candidate spawn: error/cancel leaves healthy selected old family undisturbed; atomically failed=observed, preserve committed/previous/floors, queue known scratch identities, clear transaction. CLEANING iff queue nonempty, entries INTENT; otherwise IDLE. No drain/restart or new NORMAL_AUTH for already-authorized old |
| QUIESCING/PROBATION -> ROLLING_BACK DRAIN_INTENT | After STOP_OLD intent, error/cancel/interruption; rollback.mode=precommit,target=committed; failed=observed; freeze transaction and previous, preserve all floors |
| IDLE/CLEANING -> ROLLING_BACK DRAIN_INTENT | Concrete committed integrity/local-start failure; previous required; mode=postcommit,target=previous; failed=observed; preserve floors and any existing cleanup queue in frozen rollback record as specified below |
| ROLLING_BACK DRAIN_INTENT -> DRAIN_DONE | Broker terminates/drains only its failed family; on crash/reboot lock+family lease proof is equivalent drain evidence |
| DRAIN_DONE -> RESTORE_INTENT | Validate target full inventory, spawn it only in restricted probation; no normal imports/credentials/network/START |
| RESTORE_INTENT -> RESTORE_DONE | Mandatory target preflight/self-test PASS and exact child still healthy |
| RESTORE_DONE -> CLEANING or IDLE | Durable rollback selection: precommit preserves committed AND previous; postcommit sets committed=rollback.target,previous=null. Preserve floors/failed; copy retained scratch queue, clear transaction/rollback. CLEANING iff queue nonempty, IDLE otherwise. NORMAL_AUTH only AFTER selecting snapshot flush/reread |
| CLEANING queue head INTENT -> DONE | Identity-checked postorder delete only owned scratch; absent root succeeds only after verified parent and no substituted entry; DONE only after operation |
| CLEANING queue head INTENT -> SKIPPED | Before any deletion at offending object: mismatch/unknown extras detected with opened handles; leave remaining object inert, record IO_FAILED; no recursive guessing |
| CLEANING head DONE/SKIPPED -> CLEANING next head INTENT | Drop terminal queue head only, authority/evidence unchanged |
| CLEANING final DONE/SKIPPED -> IDLE | Clear queue; committed/floors/previous/failed/evidence unchanged |
| Any -> REPAIR_REQUIRED | Unrecoverable target/probation/state evidence failure; preserve existing authority/evidence, no normal authorization |

Exact mutation kind/target pairs are the five listed above; no RESTORE_OLD/DELETE_SCRATCH in transaction.mutation. Rollback.step is the sole rollback progress journal; Cleanup.status is the sole deletion journal. No other null/intent/reset transitions allowed. A normal candidate transaction never clears a mutation back to null after ADMITTED. ROLLING_BACK freezes it and terminal selection clears transaction as a whole. `last_error` changes only alongside these edges; no successful recovery revision churn.

Rollback extends closed schema with `scratch:[Cleanup (0..2)]`, a frozen copy of existing CLEANING queue for postcommit rollback, empty for precommit (transaction owns IDs). In ROLLING_BACK top cleanup=null. On rollback success precommit queues transaction.incoming then transaction.staging when known; postcommit restores rollback.scratch without rebuilding identities. Every committed-selection write atomically transfers scratch identities—never consult stale lower slot to recover deletion authority. Newly queued entries start INTENT, ordered incoming then staging; a restored postcommit frozen queue preserves its prior status/order, so completed/skipped work is not replayed. Publish moves only `staging/<id>/generation`, leaving `staging/<id>` container inode intact. Queue target staging always means that container. Already absent child generation is acceptable, release destination is never deleted. A queue with one known root has one entry; no known roots means direct IDLE. `Cleanup.status` is INTENT|DONE|SKIPPED; SKIPPED records identity mismatch/unknown extras, leaves object inert/quarantined and safe IO_FAILED, then permits idle without unauthorized deletion. Before first delete, selecting snapshot already owns the queue. Crash at any deletion returns to same INTENT and idempotently handles absent children under retained identity checks.

When restarting ROLLING_BACK, re-prove family quiescence and target inventory. For DRAIN_DONE, durably write/reread RESTORE_INTENT BEFORE restricted target spawn. For recovered RESTORE_INTENT, prior durable intent covers a new restricted attempt; fresh PASS writes RESTORE_DONE then selecting snapshot. For recovered RESTORE_DONE, explicitly permit repeat restricted probation under that earlier durable RESTORE_INTENT/DONE authorization; fresh PASS goes directly to selecting snapshot, no backward progress revision. Any fresh failure enters REPAIR_REQUIRED. Stale DONE never substitutes for live self-test. For post-quiesce/postcommit ROLLING_BACK, before rollback selection durable: old is restricted only, selected record stays unchanged but no normal family allowed. This does NOT apply to PREPARING abort, which preserves its already-authorized healthy old family without entering ROLLING_BACK. After rollback selection durable/before NORMAL_AUTH or ACK: target is committed; recovery starts only that target in fresh probation. ACK timeout/local failure of restored target => REPAIR_REQUIRED/ROLLBACK_FAILED, never oscillate to failed new. Precommit rollback leaves earlier previous descriptor intact, permitting later independently evidenced corruption of current to roll back further. A successful NORMAL_ACK followed by unrelated network/login failure never triggers rollback.

If evidence required by a higher schema-valid slot is corrupt, do not scan disk/substitute a lower snapshot. Missing generation bytes instead enters the postcommit rollback edge preserving higher floors. Ordinary repeated recovery after convergence makes no selection/authority mutation.

## 9. Replay, failure suppression, compatibility policy

Admission requires candidate sequence > observed (or exact known candidate resume within same incomplete transaction). Equal observed exact payload with failed binding => suppressed, no automatic retry; equal with different payload/release id => conflict. Remote sequence < max(observed,highwater,committed sequence) => downgrade. An earlier committed rollback generation remains locally runnable through explicit journaled recovery even when below these floors; it is not newly admitted from server. Highwater changes only at final commit, observed changes durably at admission; signature-valid high sequence can intentionally obsolete lower candidates, as release authority policy.

On precommit failure: old remains committed; record failed=observed and clear transaction after old validates/restores. New retry must have strictly higher sequence; explicit user retry of failed same sequence is a non-goal for Phase3. On durable commit then missing/corrupt new bytes at next startup: rollback to previously committed validated old, preserve highwater/observed and suppress new. Replay protection cannot survive malicious offline replacement of both slots and helper by same-user attacker; that stronger threat requires external monotonic authority and is not claimed.

`mandatory` never interrupts a live game/Proxy session. Application apply is automatic after verified preparation **only at idle safe point**: no live authorized Core/game session, controller confirms stop, no pending login/start command. START and new update admission blocked during quiesce/probation; download may occur while busy. After failed mandatory update, old restoration/runnability takes priority; show safe failure, no tight retry loop and no dead-end block preventing repair. Full mandatory enforcement/UX beyond safe update state is deferred.

## 10. Process protocol and single flight

Helper owns one permanent open `state/control.lock` with real exclusive `LockFileEx` range0..1 for broker lifetime, share-delete denied. Acquisition <=10s; second invocation exits `LOCK_BUSY` (focus-existing UI optional later, no unspecified IPC). Locks are per install across sessions, not Local mutex names. Do not replace/delete lock inode. Helper remains alive for normal Launcher lifetime and supervises all its descendants in a kill-on-close job. No breakaway; nested existing Core jobs must preserve Launcher-owned exact handles. **Launcher retains Core spawn/permit/control responsibility**, updater sees process-family quiescence, never JWT or START payload. On approved idle handoff Launcher stops its own Core, waits child handles, shuts executors/Tk and exits; helper waits job empty, including PyInstaller parent and child. Timeout aborts before activation unless exact-owned cleanup finishes. Never kill game/unrelated processes or global-enumerate names.

Create stable helper directly via shortcut `NekoUpdater.exe --launch`; manual enrollment `--enroll`. No arbitrary roots, executables, args, URL or secret commandline. Helper fixed raw protocol args to Launcher `--update-managed` or `--update-probation`. Those switches alone confer nothing.

Duplex channel = two anonymous pipes assigned to STARTUPINFO standard input/output slots (thus child uses GetStdHandle; no numeric handle argument). PROC_THREAD_ATTRIBUTE_HANDLE_LIST contains only required pipe endpoints plus the read-only family lease in standard error; parent endpoints non-inheritable. Onefile bootloader must preserve endpoints to Python child and close surplus copies. This exact packaged chain is a release acceptance requirement; no fallback to trusting pipe name/PID. Early entry verifies parent broker image/root/current-user token via retained process handle; broker verifies actual child PID/creation/image and ancestry from **its job notifications** (no system-wide enumeration). Channel binds to helper-created job; protocol HELLO identifies exact child which must match retained child handle, not merely self-reported PID. Same-user malicious process is outside trust model but cannot be used to bypass root validation accidentally. Missing/incorrect inherited handles => fail closed before normal imports.

Frame uint32LE length + strict UTF8 JSON (max131072 bytes, read deadline5s, one outstanding request). Exact common keys `{protocol_version:1, type:MessageType, message_id:hex32, body:object}`. The initiating side generates a fresh message_id for each exchange; the response echoes it, and duplicates/stale IDs are rejected within the channel lifetime. Body request_id is distinct: generated only by broker BEGIN acceptance, identifies incoming root, and must match transaction on APPLY. It never serves as message correlation or authority outside the bound channel. All message bodies closed:

| Type/direction | Exact body |
|---|---|
| HELLO child→broker | `{mode:"managed"|"probation", pid:uint32 positive, creation_time:uint64, generation:Generation}` |
| CONTEXT broker→child | `{generation:Generation, transaction_id:hex32|null, mode:"managed"|"probation"}` |
| BEGIN child→broker | `{envelope_b64:canonical-base64 decoded<=65536}` |
| REQUEST_READY broker→child | `{request_id:hex32, transaction_id:hex32, changed:{launcher:boolean,core:boolean}, error:ErrorCode|null}` |
| APPLY child→broker | `{transaction_id:hex32, request_id:hex32}` |
| APPLY_RESULT broker→child | `{accepted:boolean, transaction_id:hex32|null, error:ErrorCode|null}` |
| QUIESCE broker→child | `{transaction_id:hex32, deadline_ms:15000}` |
| QUIESCED child→broker | `{transaction_id:hex32, core_stopped:true, operations_drained:true}` |
| SELF_TEST child→broker | `{transaction_id:hex32, generation:Generation, result:"PASS"|"FAIL", error:ErrorCode|null}` |
| LOCAL_CHECK child→broker | `{generation:Generation,result:"PASS"|"FAIL",error:ErrorCode|null}` |
| NORMAL_AUTH broker→child | `{generation:Generation, revision:uint63 positive}` |
| NORMAL_ACK child→broker | `{revision:uint63 positive}` |
| CANCEL child→broker | `{transaction_id:hex32}` |
| ERROR either direction | `{code:ErrorCode}` |

Successful APPLY_RESULT requires nonnull transaction id/null error; rejection inverse. SELF_TEST PASS requires null error, FAIL nonnull. No unsolicited message/state transition, duplicate request/result, wrong mode/generation/revision or stale transaction may mutate state. In probation only HELLO/CONTEXT/SELF_TEST/NORMAL_AUTH/NORMAL_ACK/ERROR legal; no APPLY, Core, network or credential actions.

Do not put raw envelope into generic logs/result DTOs. BEGIN is sole explicit bounded envelope-bearing transport exception; envelope is public signed metadata, not a Proxy secret. Broker retains exact envelope as generation authentication evidence and in the closed slot evidence map; operational fields otherwise store hashes/IDs only. Child argv/env/stdout otherwise cannot contain secrets; stdout reserved framed IPC, diagnostics use allowlisted separate sink.

Helper death closes noninherited sole job handle; its family is terminated asynchronously. After acquiring control.lock byte0, every new broker must open the pre-enrolled permanent `state/family.lease` with GENERIC_READ|GENERIC_WRITE and share mode zero, bounded30s. Success proves no prior family lease handles remain; retain this exclusive guard throughout recovery. Before spawning the next family, close it while still holding control.lock and open one GENERIC_READ lease handle with FILE_SHARE_READ only, explicitly inheritable to outer/inner Launcher and Core descendants. This denies the next broker a write-access probe until the last inherited file-object reference closes. **Do not use inherited LockFileEx byte locks as liveness:** Windows releases process locks at owner termination; inheritance does not grant the child those locks. Broker holds the shared-read lease during normal supervision and releases its copy only after its job is empty. Pass this third handle as STARTUPINFO standard-error handle, discovered via GetStdHandle(STD_ERROR_HANDLE); it is not an output stream and must never be written. stdin/stdout remain framed IPC. Explicit handle list includes these three only; each descendant creation propagates the read lease, no writable lease or sole job handle inherited. Core adaptation and onefile bootloader must preserve it before any executable work and close it only on exit. A process that cannot preserve the lease is incompatible and cannot be spawned. Recovery probe timeout => OLD_PROCESS_STOP_TIMEOUT, preserve state, no spawn/mutation or PID/name kill. Validate lease inode/owner/DACL like control.lock; never replace/delete it. Real Windows tests must cover outer/inner bootloader and all native descendants surviving broker death, share-mode denial until final exit, nested jobs and cross-session restart. Debug stderr is disabled in managed packaging; safe logging uses the explicit allowlisted sink, not standard streams.

### 10.1 Broker-created download handoff

Managed Launcher sends BEGIN with exact envelope before any artifact write. Broker authenticates and computes changed component identities from committed handles. It generates both IDs under existing IDLE authority, exclusively creates `incoming/<request-id>`, queries DirectoryIdentity, then flushes PREPARING/ADMITTED snapshot with evidence/observed and incoming identity BEFORE REQUEST_READY. Creation before durable identity is the defined quarantine gap; no network/download is allowed until READY. A rejected BEGIN returns ERROR only, no fabricated READY; successful READY has error=null, valid IDs and changed booleans. The broker retains incoming ancestor/dir handles denying delete/rename.

The child independently derives fixed incoming path from its validated helper root and request ID returned over its private channel; it never supplies paths. The only allowed files are `launcher.artifact` when changed.launcher=true and `core.artifact.zip` when changed.core=true. Launcher exclusively creates each fixed file, streams bounded verified bytes, flushes/closes it, then sends APPLY matching current transaction and request. Absent changed file, any extra file/directory, duplicate, unchanged-component file, mismatched transaction or APPLY before complete download => rejection/failure; no activation. Metadata-only has empty incoming directory and can APPLY immediately. Broker opens all inputs denying write/delete sharing, checks exact names/object IDs, sizes/hashes on retained handles, then builds while old Launcher may still run. No file handle is sent in the wire schema, no child-chosen destination is accepted. While broker reads, child cannot mutate verified bytes. Beginning a second request while PREPARING or busy returns LOCK_BUSY; a download failure uses CANCEL then durable failed/rollback policy. A stale child never creates a different transaction by replaying APPLY. Graceful broker exit and recovery clean only journaled identities; unknown incoming roots remain inert.

Source artifacts are retained until durable commit or rollback; cleanup uses saved identities. Whole-stage directory creation likewise records staging identity before its first child write; its INTENT precedes creation and DONE follows identity capture. If recording identity fails, leave directory inert and preserve old, no recursive name-only cleanup. PREPARING snapshot may carry staging=null until this point.

### 10.2 Ordinary cold-start protocol (IDLE or CLEANING)

Every --launch, including after helper death/reboot, acquires control lock then exclusive family-lease drain proof, selects state using §8.1, validates marker/helper/root and complete committed generation. No normal app_factory import is permitted merely because parent broker is valid. Every cold start runs the same mandatory local probation, including Core loader preflight, before credentials/network/START. This costs bounded startup time deliberately.

Broker retains committed EXE/inventory guards, creates job/lease/stdio and spawns `--update-managed` suspended. Early child remains restricted. It sends HELLO mode=managed bound to actual retained outer/inner handles and committed Generation; broker responds CONTEXT mode=managed, transaction_id=null. Introduce closed message LOCAL_CHECK child->broker: `{generation:Generation,result:"PASS"|"FAIL",error:ErrorCode|null}` for this no-transaction local probation. PASS requires null error, FAIL nonnull. No BEGIN/APPLY/CANCEL/normal actions before NORMAL_AUTH. Managed legal preauth sequence is HELLO->CONTEXT->LOCAL_CHECK->NORMAL_AUTH->NORMAL_ACK; unsolicited/wrong-generation messages fail closed. Update probation continues using SELF_TEST with its actual transaction ID; postcommit rollback uses broker-generated correlation-only transaction ID for probation even when state.transaction=null, equal to rollback record's `probation_id:hex32`. Add this field to Rollback, generated on entry and fixed across recovery; it is not a path or admission authority.

On LOCAL_CHECK PASS and child still healthy, broker rereads selected exact state; if generation still equals committed, send NORMAL_AUTH for that current durable revision (IDLE or CLEANING). Child validates generation/context/revision, sends NORMAL_ACK first, then—and only then—may import app_factory, credentials, network, regular UI and START. In update/rollback probation the same ACK-before-normal-import rule applies. Broker waits bounded10s ACK. Until ACK, no cleanup mutation/revision change; after ACK helper may process scratch queue concurrently with healthy normal family under control lock, never touching releases or family handles. New BEGIN stays blocked until CLEANING->IDLE. Ordinary successful cold start doesn't write authority slots or advance revision.

HELLO10s/whole local check60s/ACK10s apply. Exit, bad protocol, local failure or missing ACK: stop/drain only this job; if validated previous exists, perform explicit postcommit rollback; otherwise REPAIR_REQUIRED/RESTART_FAILED, never grant authority by parent proof. Any failure during rollback target probation/ACK => REPAIR_REQUIRED/ROLLBACK_FAILED instead of repeated oscillation. When a live PREPARING abort occurs before STOP_OLD, existing normal authorization remains valid for unchanged committed family; no cold-start/restricted restart is forced. Broker death is different: job kills family; next broker must prove lease drain and use this cold protocol. Network/login failures after authorized normal composition do not trigger rollback.

## 11. Transaction and commit state machine

```text
IDLE -> PREPARING [observed binding durable, old committed]
     -> BUILDING [write-ahead whole-stage INTENT]
     -> VERIFIED [publish full generation; rehash]
     -> QUIESCING [safe idle, stop old exact process family]
     -> PROBATION [candidate executes restricted self-test + real Tk local shell]
         failure -> ROLLING_BACK -> old restricted probation -> durable rollback selection
                 -> CLEANING/IDLE -> NORMAL_AUTH old (failed binding)
         success -> durable slot COMMITTED selection (phase CLEANING with scratch queue)
                 -> NORMAL_AUTH -> same candidate continues normal startup
```

Detailed ordering:

1. Signed metadata/network input validated by Launcher, then independently by helper. Determine changed identities from actual committed bytes, not UI claim. Check anti-replay, protocol, space and source handles. Persist candidate binding/observed and transaction before staging.
2. After the BEGIN/READY/APPLY download handoff, consume raw Launcher or strict Core package only for changed components. Copy unchanged verified bytes (no hardlinks). Persist whole-stage INTENT; create/write every file under stage; FlushFileBuffers each completed file. Interrupt any subcall => safe full stage rebuild or rollback old; no arbitrary partial-file resume.
3. Store exact envelope, validate full inventory/count/bytes, flush files; publish same-volume generation directory with destination-not-exists rename. If final already exists it must exactly match whole candidate or fail conflict. Validate final after rename. No selection yet; old remains active/committed.
4. Save VERIFIED state. Apply only at idle safe point; quiesce/drain old, wait exact job family and release generation guards only when exited. Cancellation before QUIESCING restores old; cancellation later means deterministic rollback, never partial activation.
5. Persist PROBATION intent; retain candidate guards; start packaged candidate suspended/job-bound. Candidate receives validated exact generation, executes local safe self-test below and real Tk event-loop readiness with auth/network/Core START disconnected. This is reversible activation: UI disabled and old still committed authority.
6. After SELF_TEST PASS and retained child still healthy, broker independently revalidates identities, writes next durable state with committed=candidate, previous=old, highwater=candidate.binding, observed unchanged, failed=null, transaction=null, rollback=null, phase CLEANING and cleanup populated by copying all known incoming/staging identities atomically from transaction. This **slot flush/reread** is sole success commit point. Child has no write authority over slots.
7. Only after durable commit send NORMAL_AUTH; candidate ACK then activates normal composition. No self-test child exit/relaunch race required. If helper dies before/after AUTH/ACK, kill-on-close stops family; recovery reads committed record and launches it, not rollback solely for missing ACK.
8. If candidate dies while broker alive after self-test but before commit, old restored. If candidate dies after commit before NORMAL_ACK/normal local event-loop continuation, broker may journal rollback preserving highwater; no remote fetch. If ACK recorded and normal mode began, later ordinary crash is not automatically blamed on update. Next startup still verifies committed integrity, rolls back only on concrete integrity/startup failure. Normal internet/login unavailability never triggers rollback.

There is an unavoidable crash observation race: when broker and candidate die together after durable commit, recovery lacks candidate-failure evidence and retries committed generation once under bounded local probation. Failure observed by new broker then rolls back. No unbounded retry loop across helper crashes is claimed; successive external process kills are outside availability completion until interruptions stop.

## 12. Local self-test and Core runtime adaptation

Early `update_entry` runs before main/app_factory imports, credential stores, Runtime Config, UI callbacks or normal named mutex. Direct generation invocation lacking broker proof exits. Source development retains ordinary source startup with update application disabled; packaged production must not have this bypass.

Probation verifies independently: packaged Launcher own EXE hash/version, signed payload sequence/id/exact digest, exact Core canonical bytes AND inventory, compatible set/protocol, embedded UI assets/importability, real local Tk creation and at least two serviced event-loop callbacks, mandatory Core loader/runtime preflight through the new safe preflight entry for EVERY release (including Launcher-only and metadata-only). Absence of that entry is incompatibility and fails probation. No network/login/proxy permit or secret restoration. Core preflight must dispatch before normal protected settings/authorization composition; exact argv is `--update-preflight`, no secret/path arguments. It receives one bounded strict JSON line on stdin, exact `{protocol_version:1, generation_id:generation-id}`, then EOF. Resource root derives from admitted EXE BaseDirectory; mutable root from KnownFolder plus generation ID validated against broker context. It validates resource/mutable roots, loads managed entry dependencies and required native libraries (without enabling drivers/interception), validates native dependency architecture/exports, and emits one stdout JSON line<=4096 bytes: `{protocol_version:1, result:"PASS"|"FAIL", code:null|ErrorCode}`, then exit0 only for PASS. Missing entry, unsupported protocol, unexpected output, write attempt to inventory, network/authorization action, timeout30s, nonzero exit or job not drained => SELFTEST_FAILED before commit. Launcher owns exact preflight process handle/job and verifies clean exit; no START. Full signed inventory is rehashed by broker after preflight; root guards remain held. Timeouts: HELLO10s, whole probation60s, child exit/job drain15s, normal ACK10s, rollback local start60s. Core inventory file hashing participates in bounded test (large actual bundle measurement required); no arbitrary timeout extension from remote data.

After approval, narrow Core change separates immutable resource root from mutable runtime-write root for `NetchRuntimeBootstrap`, log/data/temp consumers and native CWD assumptions. Preserve mode/protected payload resource paths, Runtime Config, permit contract and credential-in-memory restrictions. Mutable root derives from user KnownFolder and admitted generation, not signed remote path. Actual synthetic authorized START/STOP with all immutable guards held must prove zero inventory mutation and no credential persistence; no-START preflight alone cannot close that gate. Canonical a43 is tested read-only for strict inventory compatibility; updated Core runtime behavior is proven with a **newly admitted separate fixture**, never rebuild a43 in place.

## 13. Recovery table (after every mutation, not only named state)

Every recovery first obtains lock and family-quiescence proof, reads slots, authenticates embedded evidence, and separately assesses referenced generation inventories, then chooses following policy. Missing failed candidate bytes do not invalidate its signed observed/failed evidence or block an intact old generation. Slot transition is itself fault-injected at every write/flush/reread. Always run recovery twice after successful convergence; second must not mutate selected generation/authority (logging/lock acquisition allowed).

| Durable/latest observation | Recovery action / invariant |
|---|---|
| Partial incoming directory, no durable BEGIN admission | Old unchanged; identity-less object left inert/quarantined; never recursively delete or execute |
| ADMITTED/BUILDING and any directory/create/write/flush interrupted | Pre-quiesce abort preserves healthy live old; broker death first proves lease drain then aborts/restarts unchanged old via cold start. Persist failed binding, remove only identity-proven scratch; no old-session interruption for a live staging failure |
| File flush succeeded but DONE slot absent | Still uncommitted; same abort policy, no inference from filename/mtime |
| Final rename done, VERIFIED slot absent | Candidate may be complete but old still selected; validate/quarantine candidate, restore old; no mixed files |
| VERIFIED/QUIESCING at helper crash | Old was never uncommitted; restart old after previous family gone; record candidate failed and preserve prior committed/previous (no automatic repeated apply) |
| PROBATION at crash/reboot | No durable new commit => restore verified old; initial enrollment has no old, remain enrollment-incomplete and rerun only fixed authenticated bootstrap |
| New slot partly written/checksum invalid | Use other valid old record; old restored; newest unacknowledged transition may be lost, never guess success |
| New COMMITTED slot valid but parent namespace rename lost | If candidate complete, run it; if missing/invalid, revalidate retained previous and commit rollback preserving observed/highwater; if neither valid, repair required |
| Commit durable, helper died before NORMAL_AUTH/ACK | New stays committed; run new local probation; rollback only if fresh concrete failure |
| Live broker sees self-test/restart failure | Terminate/wait only its job; persist ROLLING_BACK; select intact old, preserve floors/suppress failed; normal old start |
| Rollback slot partially written | Highest valid slot guides idempotent recovery; never copy old component over new one; if pending failed candidate selected, retry rollback before any normal auth |
| Rollback committed, old start interrupted | Next helper reruns old local preflight/start; second failure => repair required, no oscillation |
| Active corruption with intact previous | Journal rollback retaining monotonic floors; validate whole old generation before spawn |
| Both slots invalid/conflicting | Repair required; no scan-to-highest-folder or dev-unpublished reset |
| Cleanup interrupted after any delete | Resume allowlisted transaction-root postorder deletion, never follow reparse/unknown object; absent child is success; selected generation unchanged |
| Disk full/write/flush/rename denied | Preserve old and evidence; no AUTH on unacknowledged state; recover actual slots, never assume failed call did nothing |
| Foreign file lock/AV prevents staging or publish | Abort before old exit where possible; no reboot-scheduled replace, no global kill |

Initial enrollment is explicit `--enroll` only under the marker and ordered provisioning rules in §13.1, using fixed signed bootstrap artifacts and both flushed state slots. Existing state absent/corrupt must not be treated as fresh install; marker loss on previously populated root => repair, not reset. Interrupted enrollment with no old cannot promise rollback to non-existent version: remain safely non-runnable until fixed bootstrap verified. This is outside the N→N+1 update guarantee.

### 13.1 Manual bootstrap / immutable enrollment marker

This is a NEW manually installed update-capable 5.1 root, not retrofit of v5.0.0/a2. The Owner-authenticated bootstrap handoff supplies helper binary SHA256, helper protocol1 and public-key-set SHA256 through a separate authenticated distribution record (not a checksum downloaded beside untrusted bytes). Before execution the manual installer/Owner verifies that helper SHA against the record. Initial public keys are compiled into that exact helper; key-set identity is SHA256 of UTF8 JSON sorted key_id->base64(public32), compact separators, ASCII only. Initial release envelope is verified with those embedded keys. Private release-signing keys never enter bootstrap.

Manual provisioning is allowed only when KnownFolder target is absent or an empty newly created correctly secured directory. Create root exclusively or verify empty with retained handles; any helper/state/release/unknown file in preexisting root forbids the fresh-install path. Copy and flush authenticated helper and fixed bootstrap artifacts, record root identity, create state directory and permanent control.lock/family.lease, then exclusive-create enrollment.bin. A crash before marker completion leaves a populated incomplete root: normal launch AND --enroll refuse it. Owner-authenticated manual bootstrap recovery may archive that exact incomplete root intact and install into a newly empty fixed root only after verifying no valid slots exist; if any previously committed state exists, no automatic archive/reset or helper migration. Preserve state for separately authorized recovery.

Marker is exactly16384 bytes, same frame layout/checksum algorithm as slots but magic `NEKOENR1`, format1, revision1, body<=16328 and zero padding. Closed body:
`{schema_version:1, installation_id:hex32, root:{volume_serial:hex16,file_id:hex32}, helper_sha256:hex64, helper_protocol:1, keyset_sha256:hex64, bootstrap_payload_sha256:hex64, enrollment_status:"PREPARED"}`.
It is immutable for this phase; PREPARED means trust root provisioned, NOT committed enrollment. Actual enrollment completion is authenticated slots with nonnull committed. Marker is local tear/reset guard, not a new signature trust source. Runtime compares helper's actual guarded hash, embedded keyset/protocol, root file/volume identity and installation ID. Marker is flushed/reread and never replaced by updater. A valid marker with mismatch/corruption => repair, never re-enroll. No slot/cleanup/apply path may write/delete helper, marker, bootstrap or key authority; fixed slot writes and permanent lease/lock opens are the only state mutation destinations.

With valid prepared marker and no slots yet, --enroll authenticates bootstrap envelope/artifacts, creates BOTH full-size slots by exclusive create (no overwrite) and writes/rereads identical revision1 ENROLLING snapshots containing only initial envelope in evidence, committed/previous/highwater/observed/failed/transaction/cleanup/rollback null. Enrollment candidate derives only from marker.bootstrap_payload_sha256+evidence, not transaction fields. After first valid snapshot exists, torn/absent second can be recreated/repaired only by --enroll under prepared marker with no committed state; once any committed state exists missing slot is a repair gate, not implicit enrollment. Normal --launch while ENROLLING reports enrollment incomplete and never mutates trust state.

Manual --enroll then constructs initial generation from fixed bootstrap using same path/hash/flush guards; initial generation ID is payload-derived. Interrupted enrollment can retry only this fixed candidate after validating marker/slot evidence; incomplete unknown directories are quarantined without name-only delete. Run required probation including mandatory Core preflight. On PASS write next slot IDLE with initial committed/highwater/observed together, previous=null. Then replicate via next revision to other slot before declaring bootstrap complete; selected generation/evidence remain unchanged. Mirror transition allowed only as enrollment finalization; if interrupted, the valid committed slot preserves identity and recovery repairs other slot without resetting floors. Both files must exist and validate before enabling remote BEGIN. Initial snapshot revisions1/1 with identical bytes are the sole equal-revision exception. Thereafter each acknowledged write increments by one.

For missing slot after commitment, fail closed to repair unless the existing slot explicitly proves enrollment finalization is pending. Encode `enrollment_complete:boolean` in all State records: false for ENROLLING and first committed slot, true in the final mirrored IDLE write. Only false->true allowed and only for initial fixed bootstrap identity. Remote BEGIN requires true. Manual --enroll may finish the mirror from first-committed false snapshot after revalidating initial generation; it must not rebuild or downgrade. Normal --launch may guide that manual step but cannot reset. After finalization marker remains PREPARED; mutable completion resides in slots only.

Future helper/public-key servicing and moving/restoring root to a different file/volume identity are unsupported automatic operations. They require a new reviewed manual migration that preserves floors and installs an authenticated trust root; Phase3 refuses mismatches instead of offering an unsigned repair switch.

## 14. Backup, cleanup, disk and transport

Backup = whole old committed generation plus durable previous descriptor; no zip of mutable user state. Old is not modified by candidate, no hardlinks/shared mutable files. Phase3 retains **all committed generations**; automatic pruning of committed backups deferred to separately reviewed maintenance. This is deliberate disk-cost tradeoff, not permission to grow indefinitely unnoticed: space gate rejects new update with clear code before download/quiesce. Failed/incomplete incoming/staging files cleaned after durable failed/rollback record; no committed generation delete. Cleanup journal target enum plus transaction-derived root only; validate ancestors/IDs/links for each delete; suspicious extras stop cleanup, never follow them.

Before download Launcher checks upper bound signed archive+new generation budget. Before build helper measures actual existing bytes and ZIP expanded bounds. Require new generation + outstanding artifact bytes + largest temp-file allowance +16MiB state reserve +max(256MiB,10% new-generation bytes), using checked arithmetic/GetDiskFreeSpaceEx. Existing backups not assumed reclaimable. Slots preallocated reduce but do not eliminate disk failure; rollback can still fail if filesystem unusable => repair-required, never mixed runnable.

Launcher network: manifest/grant existing endpoints 5s, max65536/16384 bytes. Artifact connect5s/read inactivity15s/total900s; enforce actual bytes<=signed size and schema max, TLS certificate validation, HTTPS only, no redirects/userinfo/fragment, no cookies/auth/Proxy secrets or inherited proxy-credential transport. Grant expiry checked before opening; grant URL/query only memory. No retries per invocation; interrupted file never resumed as trusted, new invocation re-fetches fresh grant and bytes. Download only changed components; helper independently verifies unchanged content. Offline recovery never needs grants or credentials. Admin provider/storage access control decisions remain gated; public route abstraction cannot override licensed Core controlled-distribution policy.

### 14.1 Controlled Core grant authorization (proposed, not deployed)

Core must remain access-controlled; a public artifact ID or public grant response is not authorization. Adopt a dedicated **distribution capability**, separate from Supabase login, Runtime Config, issue_launch_permit and Proxy authority. No new Backend authorization migration is required for this phase. Owner distributes a cryptographically random256-bit opaque capability through the team's existing authenticated licensed-delivery channel during manual bootstrap. Installer receives it through masked in-memory input and stores it only in Windows Credential Manager scoped to current user, target `NEKO-FAMILY/SoftwareUpdateDistribution/v1`. No credential file, project artifact, argv, environment, report or clipboard automation. Local sandbox generates it in memory and uses an in-memory store. Rotation/revocation/provisioning in production is Owner Gate2, never routine architecture work.

Admin server's protected server-only configuration holds a bounded distribution authorization registry. Exact record `{credential_sha256:hex64, expires_at:UTC-RFC3339-seconds, enabled:boolean, channel:"beta", artifact_ids:[artifact-id unique1..64]}`; array<=1024 records. No raw capability server-side, compare SHA256 with constant-time equality; digest is credential-derived sensitive configuration, never print/export into docs/Git. Scope is explicitly allocated immutable Core artifact IDs (including future releases only when separately admitted/published), not wildcard "all files". Expired/revoked/disabled/scope-mismatch => deny. No new signing key. Server validates active-release mapping and requested component in addition to registry. Hash registry read/rotation is Owner-managed server configuration; missing registry fails closed.

Extend existing `POST /api/software-update/artifact-grant` with exact closed request `{artifact_id:artifact-id}` unchanged; Core requests require `Authorization: NekoDistribution <canonical-base64url32-no-padding>` over TLS only. Manifest stays public. Launcher-only artifacts MAY retain anonymous access. Server must decode signed active payload enough to determine the component mapping from trusted active release record, require explicit `distribution:"controlled-core"` on immutable Core object registry, and never fall back to anonymous when classification is missing. An artifact ID reused across components or content identities is publication-invalid. Provider errors are bounded safe codes, no reflected auth/header/URL data. Return `{url:https-url, expires_at:UTC-RFC3339-seconds}` only after capability auth. Use 401 for missing/invalid capability, 403 for valid but out-of-scope/expired capability, 404 only for unknown active artifact; diagnostics reveal no capability values.

Core storage object MUST be private, with no alternate anonymous origin/CDN access. Storage-issued read-only signed URL expires<=120s, bound to exact immutable artifact ID/SHA/object version and GET only. Issuing endpoint validates registry on every request; revocation blocks new grants immediately, existing URL may remain usable until <=120s expiry. URLs are intentionally replayable only for that one object until expiry, not one-time tokens. Capability itself is reusable until its explicit expiry/revocation; bearer theft risk remains within stated same-user/device compromise limitation. No expiry-only cosmetic wrapper around a static public URL (current Phase2 provider behavior) qualifies. Production activation requires provider enforcement tests for anonymous origin denial, expired URL, wrong object, revoked capability and alternate URL paths. No new Core grant may be issued without exact scoped credential even if its artifact ID is public.

Launcher reads distribution capability into memory only when changed Core download is required. Header goes ONLY to fixed trusted Admin grant origin, not artifact URL or redirects. After grant, drop header/capability references; artifact GET uses URL alone, no Authorization/cookies. Helper/IPC/slot/logs never receive capability or grant URL. Authentication absence/expiry/offline grant leaves old complete installation intact; no Launcher-half commit when release also changes Core. Launcher-only updates continue without capability; unchanged Core is verified/copied locally. Renewal is manual secure bootstrap credential servicing, does not alter trust keys/floors, and does not itself authorize Proxy execution. UI requests renewal safely; it never writes secrets into support logs. Signed release authenticity remains Ed25519 regardless of distribution authorization.

This is a real cross-repository Phase3 contract extension: Admin feature branch needs protected grant registry plus private-storage adapter and tests after architecture approval. It is not a claim that Phase2 already supports it, and architecture approval does not deploy/configure capabilities or storage. The exact provider credentials/private object namespace remain server custody, never client/public documentation. Failure to supply an enforced controlled-storage adapter blocks production, not permission for public Core delivery.

## 15. Diagnostics and error taxonomy

Closed logs: UTC time, transaction ID, phase, component, sequence, exact safe code, byte count, elapsed time, Win32 numeric error. No free exception/trace, environment/commandline dump, URLs, grants, signatures/envelope payloads, JWT/permit/Runtime Config/credential/key bytes, usernames/full local paths. Envelope on disk is explicit signed authentication evidence, never support-log payload. Log max2KiB/line,4MiB/file,two rotations in mutable log root; logging failures do not authorize unsafe continuation. Include URL/token-like synthetic sentinels in negative tests; report counts only.

ErrorCode closed set (extend only via reviewed contract):
`SIGNATURE_INVALID`, `UNKNOWN_KEY`, `SCHEMA_INVALID`, `PROTOCOL_UNSUPPORTED`, `DOWNGRADE_REJECTED`, `SAME_SEQUENCE_CONFLICT`, `CANDIDATE_SUPPRESSED`, `ARTIFACT_MISSING`, `SIZE_MISMATCH`, `HASH_MISMATCH`, `CORE_INVENTORY_INVALID`, `PACKAGE_INVALID`, `PATH_REJECTED`, `REPARSE_REJECTED`, `LINK_OR_ADS_REJECTED`, `ROOT_UNSUPPORTED`, `ELEVATION_UNSUPPORTED`, `LOCK_BUSY`, `BUSY_SESSION`, `INSUFFICIENT_SPACE`, `IO_FAILED`, `FLUSH_FAILED`, `PUBLISH_FAILED`, `STATE_CORRUPT`, `PROTOCOL_INVALID`, `TIMEOUT`, `OLD_PROCESS_STOP_TIMEOUT`, `SELFTEST_FAILED`, `RESTART_FAILED`, `ROLLBACK_FAILED`, `CANCELLED`, `TRANSPORT_UNAVAILABLE`, `GRANT_INVALID`, `REPAIR_REQUIRED`.

No raw upstream message mapped into these. UI shows safe update state and preserves active game before idle apply. Full UI restyling, rollout scheduling, force mandatory policy and unrelated refactors excluded.

## 16. Alternatives and consequences

- Selected: stable helper + full immutable generation + two-slot authority. More disk and one long-lived broker, but no mixed pair or running-EXE overwrite; rollback independent of network.
- Rejected: Launcher self-overwrite/batch delayed copy — locked onefile parent, broken recovery bootstrap and unsafe argument/process authority.
- Rejected: independent Launcher/Core in-place swaps — two filesystem commits permit mixed runnable pair; complex restore ordering.
- Rejected: junction/current symlink — reparse/TOCTOU attack surface, still needs authority journal.
- Rejected: service/elevated broker/Program Files — new privileged trust boundary unsupported by present source; manual bootstrap per-user selected.
- Rejected: mandatory directory fsync + ReplaceFileW write-through — unsupported guarantees. Fixed-slot file flush/validation is authority, directories may need rollback on lost namespace metadata.
- Deferred: helper auto-update/key rotation/committed-backup GC/delta patching; incompatible protocol requires manual servicing. Public signing key changes remain Owner gate.

## 17. Binary acceptance and release gates

Implementation plan only after Owner approves this exact written architecture; file-level vertical slices with tests-only commit → collected assertion-level RED → implementation → focused/full GREEN/lint/diff → independent security review → narrow commit/push. Import/collection failure is not RED. Current candidate a2 remains preserved; product changes use a3 or later actual identity, normal bump only two canonical declarations unless reviewed reason.

Required matrix, all observable with exact artifact/journal/process identities:

1. Genuine packaged N→N+1, separately Launcher-only/Core-only/both; changed downloads only, signed envelope, whole-generation activation, restart/probation, durable commit, correct identities. Metadata-only newer release also covered. Sequence regression: N→N+1 commit, N+2 precommit failure, then N+1 concrete corruption/start failure must still recover authorized N; precommit failure must not erase previous.
2. Genuine signed N+2 broken candidate: **both precommit self-test failure and activation/restart failure**; automatic prior N+1 restored/runnable, rollback floor unchanged, failed candidate not retried. A rejected download alone is not rollback proof.
3. Reject forged/signature/unknown key, downgrade/equal-sequence conflict, unknown schema/protocol/component, wrong SHA/size/installed identity, malformed ZIP/decompression/path/reparse/hardlink/ADS/alias, nonHTTPS/redirect/expired grant.
4. Network interruption, cancellation, disk write/flush/full/space denial, Launcher staging/publish file lock, Core extraction/publish failure, restart failure, self-test failure; old or new whole installation only.
5. Crash after **each actual filesystem mutation and each durable transition**, including partial slot write, post-flush before bookkeeping, rename metadata loss model, activation, NORMAL_AUTH/ACK, rollback, every cleanup delete. Recover twice; second no selected-state mutation. Real Windows API tests plus deterministic fault model; VM abrupt power-loss cases for storage durability, not just mocked renames.
6. Exact PyInstaller outer/inner handles, inherited IPC/liveness handles, helper death/job drain, nested Core jobs, unrelated same-name sentinel stays alive, PID reuse, second session/broker contention, no global enumerate/kill. Liveness lease feasibility must be proven with real Windows processes before integration.
7. Strict untouched a43 inventory reference compatibility plus new separately admitted adapted Core. Synthetic START/STOP no credential disk spill, generation remains immutable, Runtime Config/permit wire unchanged; no production mutation needed.
8. Fresh full Launcher/Admin/Core canonical suites as relevant, warning/error counts from authoritative summaries, privacy scan scope explicit. Architecture review Critical0/Important0; implementation independent review separately Critical0/Important0.

Local sandbox tests are authorized engineering work after architecture approval; no repeated Owner permission needed. Status after sandbox success = `ENGINEERING_PASS` / `READY_FOR_OWNER_AUTHORIZATION`, **not LIVE_UPDATE_AUTO_COMPLETE**.

Owner Gate2 before any PR5/PR3 release integration merge, Vercel production deploy, active-release env, production signing/public-key provisioning, real artifact publication, public sequence allocation, tags/releases. Prepare custody/signing/immutable promotion/revocation/deployment order/bootstrap/checklist/exact hashes first. No raw private key in docs/repo/client/logs.

Owner Gate3: authorized manual update-capable 5.1 bootstrap then real production N→N+1 auto update AND N+2 activation-failure rollback→N+1. Only both independently verified permit `LIVE_UPDATE_AUTO_COMPLETE`. v5.0.0/a43/a44/a2 historical artifacts remain preserved; no retroactive self-update claim.

## 18. Open implementation risks, not waived gates

Windows fixed-slot durability and namespace-loss recovery, onefile inherited IPC/liveness lease semantics, nested jobs, runtime write relocation and endpoint-independent preflight require executable proof. Same-user compromise and permanent disk loss explicitly outside availability/security claims. Controlled Core access is specified in §14.1; provider enforcement, real signing custody and production env absence remain production authority/evidence matters. No unknown privileged mechanism, hardcoded private endpoint requirement or universal no-secrets claim is assumed.

The spec is proposed. No product Phase3 code, migration, deployment, public release or signing operation is authorized until the corresponding Owner gate is crossed.

### References

- [Phase-2 approved design](2026-09-05-software-update-phase-2-design.md).
- [Existing runtime distribution policy](../../current/runtime-distribution.md).
- [Windows ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew).
- [Windows FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers).
- [Windows LockFileEx inheritance limits](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex).
