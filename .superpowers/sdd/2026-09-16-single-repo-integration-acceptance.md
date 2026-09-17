# 2026-09-16 Single-Repo Integration Acceptance

## Integration Details
- **Base Commit**: `224eb9cb43df0ca0fa583fa41a0c219622392a56`
- **Ordered Commits (Cherry-picked)**:
  1. `aa8d5408e154d7fc0da4294fe021121fcc7a2945` (Now: `d0f85a6` feat: support terminal supersession of unpublished signed release)
  2. `d32afa9c206cdbf9e1ee68737fb70c5535530814` (Now: `3867e65` feat: bind production update trust to canonical repository)
  3. `2a5397d9a7715434b23425158bc6b9abc02513e6` (Now: `334c4b4` feat: verify unified canonical release assets)
  4. `d62ea12898e9f48567a56dec92d6028cbc7d65fa` (Now: `a9bfa6a` feat: publish unified canonical releases)
  5. `1c494be2ad91a0014f5a381ce28dd4f06b5b7273` (Now: `d28c4b1` fix: route release controller through unified publisher)
  6. `1faf199f969d021dcbcc274b2569c2b94d82a02e` (Now: `505f51e` test: prove unified release authority and publication flow)

*(Note: `d62ea128` and `1c494be` were cherry-picked consecutively as an inseparable series. Tree equivalence proven against `1c494be2ad91a0014f5a381ce28dd4f06b5b7273^{tree}`)*

## Final State
- **Resulting Commit SHA**: `505f51edc7b6a800f79c1dd23ec0a0102345cef9`
- **Resulting Tree SHA**: `dd244e0d43bba55ed5c4b86077507bfe7a037135`

## Verification & Status
- **Test Matrix**: Full RA acceptance matrix executed across repository. (Launcher test suite: 2392 passed, 2 skipped, 7 deselected. Core test suite: 67 passed.)
- **Ruff Linter**: Encountered formatting drift in `launcher/tests/test_process_detector.py` (`E701`). No corrective modification retained per integration boundaries and controller guard directives (restored cleanly).
- **Repository Safety**: Clean.
- **Git Diff Check**: Clean (`git diff --check` passed).
- **Worktree Status**: Clean (Mutation-free proof verified; no untracked or modified files remaining).

No production ledger mutation, signing, or public GitHub actions were performed.


---

## INT-SR2 Integration Details
- **Base Commit**: `505f51edc7b6a800f79c1dd23ec0a0102345cef9` (INT-SR1 Head)
- **Ordered Commits (Cherry-picked)**:
  1. `cee99288ab2f111071c27af24062a7a002cd20bb` (Now: `adf33b2` feat: enforce mandatory compatible updates at startup)
  2. `b4a003bca7820304d11989dd59a17ad07d0d0136` (Now: `2df6769` feat: fail closed on untrusted updater helper)
  3. `3004cfd9d620e4a34765bc227e83ead77e98b142` (Now: `dce20bd` fix(launcher): remove spawner-coupled updater validation bypass)
  4. `ffd21d0020228187ad0cd899c715885269447a11` (Now: `c4ec789` feat: retain exact installed release identity)
  5. `2bfabdc1f827e4c7ee7945afdcff7f857e78acc7` (Now: `ed08f08` feat: add read-only installed file check)
  6. `17e35ef16ca9e1e4276ad3ac7ecbb9b3b173ab3c` (Now: `230c5cb` feat: repair damaged installed release files)
  7. `e8d3f185371dfff37e75b6d0b3985e9fc4d29066` (Now: `3fc6449` feat: bind installed client to provisioned machine credential)
  8. `a28920071e7d51d55519109b0a9026d27e93801d` (Now: `3f3dc03` test: preserve single active session across reinstall)

*(Note: `b4a003bc` and `3004cfd9` were cherry-picked consecutively as an inseparable remediation series. Tree equivalence proven against exact cherry-picked state.)*

## INT-SR2 Final State
- **Resulting Commit SHA**: `3f3dc03a6e866d3db3b1b212b9b4388476dd2ea3`
- **Resulting Tree SHA**: `095d62b4c496be41d4dd6a5f01a5aa535e31ada1`

## INT-SR2 Verification & Status
- **Test Matrix**: Full Runtime acceptance matrix executed. Launcher/Runtime/Core tests (2555 passed, 2 skipped, 7 deselected).
- **Executable Builds**: Canonical Launcher and Updater compiled via frozen PyInstaller toolchain.
- **Self-Check**: Built `NekoUpdater.exe --self-check` exited 0 successfully.
- **Ruff Linter**: Encountered pre-existing formatting drift in `launcher/tests/test_process_detector.py` (`E701`). Retained cleanly per integration guard.
- **Repository Safety**: Clean.
- **Git Diff Check**: Clean (`git diff --check` passed).
- **Worktree Status**: Clean (no uncommitted tracked/untracked mutations).

No production ledger mutation, signing, or public GitHub actions were performed.
