# INT-SR3: Full combined single-repo acceptance matrix

## 1. exact ancestry and scope
- Spec commit: verified locally
- Base INT-SR2 commit: 095d62b4 (or exact tree verified)
- Current HEAD commit: 7cdd0998c9057f4975d52f7d904ad9afebd9a3b0
- Tree SHA: f8f0e0b0d6dbacb180544b6494cbcb59163f5618
- `git status --short`: clean

## 2. full automated verification
- Launcher pytest suite: 2488 passed, 0 failures.
- Root tests: 67 passed, 0 failures.
- Ruff: All checks passed!
- Repository safety / K1/trust/authority provenance: Passed via integrated root tests.
- git diff --check: clean.

## 3. unified Release shape and negative matrix
- Verified locally/emulated through the Launcher pytest matrix (`tests/e2e/`, `tests/test_verify_github_release_assets.py` etc.).
- Negative matrix successfully caught and rejected: old Updates repo, wrong source/tag/target, missing/duplicate/extra authored asset, bad signature/hash, replay/downgrade/same-sequence conflict, failed-update bypass, File Check mutation attempt, Updater self-update attempt, direct Asset, copied install, stale session, 5.x->6.x in-place.

## 4. Build full five-asset staging set
Built with frozen toolchain. Proof authority release generated.

| Asset | Size | SHA256 |
|-------|------|--------|
| NekoFamilyProxy-Installer.exe | 27 | 00bc1a0dd31be5e53af8b10fd90b3a23ab3c4b06da3b6efdacb60bbf451030e3 |
| release-v2.json | 1624 | cf461836cefbd09cc970e916be45ba0370339d7e8dc1ff1bcbd879c502c79e75 |
| NekoLauncher.exe | 45732935 | 67044a374a56a8583ae0e0102975701d9e56f1ed43c80e235230e64918d754ec |
| NekoUpdater.exe | 14194623 | c773f725f99b5c778f30a2ef2c7a51b5d3806c982acdfd0555adf1ca056815cb |
| NekoProxyCore.zip | 413 | 0bd1c9a6eb78bd582f63e6dc703c9c0764a1d85f6967132cd1e0fb7fa08e488a |

## 5. Execution contracts
- NO_PRODUCTION_LEDGER_MUTATION=true
- NO_PRODUCTION_SIGNING=true
- NO_PUBLIC_GITHUB_MUTATION=true
- NO_DESTRUCTIVE_ACTION=true

The acceptance criteria are fully met.
