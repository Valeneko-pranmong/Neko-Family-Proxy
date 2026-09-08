# NekoProxyCore runtime distribution

**Status:** Current policy — updated September 2026 for GitHub Releases Software Update architecture.

`NekoProxyCore` is a separately licensed external runtime. It is never committed to this repository's source tree or embedded inside the `NekoLauncher.exe` PE binary.

Under the Owner's GitHub-only architecture decision, `NekoProxyCore.zip` is accepted as an exact fixed product asset published alongside `NekoLauncher.exe` and `NekoUpdater.exe` in fixed GitHub Releases, governed by signed `release-v2.json` authority (public Core accepted).

The historical Supabase private Storage / Admin grant / capability distribution path for Software Update is **SUPERSEDED BY OWNER GITHUB-ONLY ARCHITECTURE DECISION, NOT PASS**. Historical blocker evidence is preserved; unrelated Supabase/Admin/account/recovery/proxy services remain untouched.

## Delivery and update contract

1. **Fixed GitHub Releases only**: Current Software Update architecture uses fixed GitHub Releases with latest published stable release discovery.
2. **Four REQUIRED CLIENT ASSETS**: Each stable release must contain exactly one each of `release-v2.json` (signed envelope authority), `NekoLauncher.exe`, `NekoUpdater.exe`, and `NekoProxyCore.zip` (public Core accepted). Permitted human-facing extras may exist, but the client ignores them and never trusts them; this is not an exactly-four-total-assets restriction.
3. **Signed release-v2 authority**: The Ed25519-signed envelope authenticates the three product descriptors, including signed size, SHA-256, and identity as applicable, and binds the required client assets to the same release. Product bytes must match their authenticated descriptors. Extras and unsigned checksums such as `SHA256SUMS` confer no authority.
4. **No update fallback**: There is no fallback to Supabase private Storage, Admin distribution endpoints, or Vercel routes.
5. **Publish-last verification requirement (not execution evidence)**: Under separate release authority, release drafting, asset upload, and complete verification must precede publication; only fully verified drafts may be published. This documentation correction performs or claims no production signing, tag/draft creation, upload, publication, merge, push, deployment, or live auto-update completion.
6. **Local destination**: The Updater extracts the approved frozen Core bundle to the external runtime directory:

   `%LOCALAPPDATA%\NEKO FAMILY\ProxyCore\NekoProxyCore.exe`

7. **Secret hygiene**: Customer data, Supabase secret/service-role keys, and private signing keys are never placed in release archives or assets. Standalone keys and plaintext settings are not released.

Launcher resolves `NekoProxyCore.exe` only from the external runtime path above. It does not implement bundled-runtime or environment-variable path override. The Launcher EXE contains no Core runtime payload.

Embedding or installing the runtime does not bypass the fail-closed production authorization gateway. Gate #2 and Gate #3 remain NOT PASSED until replacement criteria are executed under separate authority.
