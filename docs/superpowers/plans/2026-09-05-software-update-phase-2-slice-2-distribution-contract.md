# Software Update Phase 2 — Slice 2 Distribution Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add public non-secret Control Room manifest/artifact-grant routes plus strict Launcher HTTP clients, while keeping storage provider choice replaceable and production release publication disabled.

**Architecture:** Control Room serves an immutable per-deployment active release record from a strict server-side provider; default production behavior with no configured record is typed no-release. The first provider accepts only public immutable HTTPS artifact URLs from server configuration; future signed-URL providers implement the same server interface. Launcher clients reject redirects, bound response sizes/time, and return parsed data without logging URLs.

**Tech Stack:** Node 24 ESM/`node:test`, Vercel API handler, Python 3.11 urllib, pytest/Ruff.

**Spec:** `docs/superpowers/specs/2026-09-05-software-update-phase-2-design.md`

## Global Constraints

- Worktree: `E:\Github\worktrees\Neko-Family-Proxy-5.1` on `release/5.1`; do not touch the dirty legacy `stabilize/a42-owner-verified` worktree.
- Current source version is `5.1.0a1`; do not build a materially changed Owner-test binary under that same version.
- Runtime Config v1, production Runtime Config v2, and `issue_launch_permit` v4 are separate and must not change.
- Phase 2 detects/authenticates updates and verifies artifact bytes only. No install, activation, `NekoUpdater.exe`, backup, rollback, or post-update self-test.
- Remote signed manifests use `release_sequence >= 1`; unpublished development uses local sequence `0` / `dev-unpublished`.
- Signed envelope: exact payload bytes, Ed25519, 64 KiB HTTP body, decoded payload <= 49,152 bytes, 64-byte signature, 32-byte public key.
- Key IDs: test `neko-update-test-1`; production reserved `neko-update-prod-1`. The production private key never enters the repo/client/logs.
- Manifest HTTP: HTTPS only, no redirects, 5.0 s timeout. Grant response: HTTPS only, no redirects, 5.0 s timeout, <= 16,384 bytes.
- Launcher artifact maximum 128 MiB; Core artifact maximum 1 GiB.
- Use TDD: a genuine failing assertion/missing-symbol RED before each product implementation. Collection/import errors do not count as RED.
- Launcher focused/final tests run with `PYTHONPATH` pointing at this worktree and `TCL_LIBRARY`/`TK_LIBRARY` removed process-locally. Full Launcher integration uses canonical Core artifact `E:\Github\worktrees\NekoProxyCore-live-update\TestResults\task12\a43-core`.
- Product-code implementation is delegated through Hermes; coordinator performs independent verification before every completion claim.

---

### Task 1: Create isolated Admin Phase-2 worktree before code

**Files:** none.

- [ ] **Step 1:** In `E:\Github\Neko-Family-Proxy-admin-tool`, fetch `origin/main` and verify it resolves to the current public Admin baseline (`ac2d713e05b46cf14915cf2c51140441bf797cf8` at plan time). Stop and re-audit if it changed.
- [ ] **Step 2:** Create `E:\Github\worktrees\Neko-Family-Proxy-admin-tool-software-update` on branch `feature/software-update-phase2-control-plane` from freshly fetched `origin/main`.
- [ ] **Step 3:** Run the existing direct Node 24 standalone build + full test suite; baseline must pass before modifications.

### Task 2: Strict server-side active release provider

**Files:**
- Create: `server/software-update.mjs`
- Create: `tests/software-update.test.mjs`

**Interfaces:**
- `getSoftwareUpdateManifest(channel, env = process.env) -> object | null`
- `getArtifactGrant(artifactId, env = process.env, now = new Date()) -> { url, expires_at }`
- Environment input: `SOFTWARE_UPDATE_ACTIVE_RELEASE_JSON`, strict JSON object with keys `channel`, `envelope`, `artifacts`; each artifact value is a public immutable HTTPS URL string with no username/password/query/fragment.
- If env is absent/blank, manifest returns `null`; artifact grant returns safe 404.

- [ ] **Step 1: RED tests** for absent record, exact beta record, malformed/extra fields, channel mismatch, invalid artifact id, unknown artifact id, non-HTTPS URL, URL credentials/query/fragment, and no runtime secret fields.

```js
test("active release provider returns only signed envelope", () => {
  const env = { SOFTWARE_UPDATE_ACTIVE_RELEASE_JSON: JSON.stringify(validRecord()) };
  assert.deepEqual(getSoftwareUpdateManifest("beta", env), validRecord().envelope);
});
```

Use sentinel `SENTINEL_PROXY_SECRET_42` in an invalid record and assert it never appears in returned metadata/errors.

- [ ] **Step 2: Run `node --test tests/software-update.test.mjs` and capture RED**

- [ ] **Step 3: Implement strict provider**

Artifact id regex `[A-Za-z0-9._-]{1,96}`; active record size <= 131072 characters; envelope is treated opaque here because Launcher Ed25519 is integrity authority. `expires_at` is `now + 10 minutes` UTC RFC3339; it is a client grant-refresh deadline even when the URL itself is public.

- [ ] **Step 4: Run focused Node tests**

- [ ] **Step 5: Commit** `feat: add software update release provider`.

### Task 3: Public manifest and artifact-grant API routes

**Files:**
- Modify: `api/index.mjs`
- Modify: `tests/vercel-api.test.mjs`

**Interfaces:**
- `GET /api/software-update/manifest?channel=beta` -> `200 {"envelope_version":1,"key_id":"neko-update-test-1","payload_b64":"cGF5bG9hZA==","signature_b64":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="}` in tests, or `404 {"ok":false,"error":"No active software release"}`. Production uses `neko-update-prod-1` only after the Owner public key is provisioned.
- `POST /api/software-update/artifact-grant` with exact body `{"artifact_id":"launcher-win-x64-beta-0002"}` -> `200 {"url":"https://objects.example.invalid/launcher-win-x64-beta-0002","expires_at":"2026-09-05T08:10:00.000Z"}`.
- Routes are public, no admin cookie required, and remain before `/api/admin` auth dispatch.

- [ ] **Step 1: RED Vercel route tests** for exact success/no-release, missing/wrong/duplicate query params, GET/POST method restrictions, extra body fields, oversized body already handled by global body bound, and artifact unknown -> 404. Assert no `Set-Cookie`, no Runtime Config fields, no service-role material.

- [ ] **Step 2: Run focused Vercel test and capture RED**

- [ ] **Step 3: Wire routes**

```js
if (url.pathname === "/api/software-update/manifest") {
  if (request.method !== "GET") return sendError(response, 405, "Method not allowed");
  if (url.searchParams.size !== 1 || url.searchParams.getAll("channel").length !== 1
      || url.searchParams.get("channel") !== "beta") {
    return sendError(response, 400, "Invalid software update channel");
  }
  const envelope = getSoftwareUpdateManifest("beta");
  if (envelope === null) return sendError(response, 404, "No active software release");
  return sendJson(response, 200, envelope);
}
if (url.pathname === "/api/software-update/artifact-grant") {
  if (request.method !== "POST") return sendError(response, 405, "Method not allowed");
  const body = await bodyJson(request);
  if (Object.keys(body).length !== 1 || typeof body.artifact_id !== "string") {
    return sendError(response, 400, "Invalid artifact grant request");
  }
  const grant = getArtifactGrant(body.artifact_id);
  return sendJson(response, 200, grant);
}
```

Do not reuse `runtime-config.mjs` or admin session authorization.

- [ ] **Step 4: Run `tests/software-update.test.mjs`, `tests/vercel-api.test.mjs`, then full Admin suite/build**

- [ ] **Step 5: Commit** `feat: expose software update distribution routes`.

### Task 4: Launcher bounded HTTP manifest/grant clients

**Files:**
- Create: `launcher/src/neko_launcher/infrastructure/software_update_client.py`
- Create: `launcher/tests/test_software_update_client.py`

**Interfaces:**
- `HttpUpdateManifestGateway(base_url: str, timeout: float = 5.0).fetch(channel: str = "beta") -> object | None`.
- `HttpArtifactGrantGateway(base_url: str, timeout: float = 5.0).grant(artifact_id: str) -> ArtifactGrant`.
- `ArtifactGrant(url: str, expires_at: datetime)` contains HTTPS URL only in memory; its `repr` must redact query if future providers return one.

- [ ] **Step 1: RED tests** use local HTTP servers/monkeypatched opener to prove exact route/method/body, no redirects, 5 s timeout injection, manifest body >65536 rejected, grant body >16384 rejected, HTTP 404 manifest -> `None`, other status -> closed typed error, invalid JSON/fields rejected, non-HTTPS grant URL rejected.

- [ ] **Step 2: Run focused test and capture RED**

- [ ] **Step 3: Implement with a `_NoRedirectHandler` pattern matching account recovery**

Never include grant URL in exception text. Error codes: `MANIFEST_UNAVAILABLE`, `MANIFEST_RESPONSE_INVALID`, `GRANT_UNAVAILABLE`, `GRANT_RESPONSE_INVALID`.

- [ ] **Step 4: Run focused test + Ruff**

- [ ] **Step 5: Commit** `feat: add bounded software update clients`.

### Task 5: Cross-channel secret-separation and Slice-2 checkpoint

**Files:**
- Modify: `launcher/tests/test_support_logging.py` or create `launcher/tests/test_software_update_privacy.py`
- Modify: Admin `tests/software-update.test.mjs` to add sentinel privacy cases.

- [ ] **Step 1: Add sentinel tests** that place proxy credential, permit/JWT-like text, and signed-URL query token into failing fake inputs/exceptions and assert retained Launcher diagnostics/results and Admin responses never contain those values.
- [ ] **Step 2: Run Launcher Slice-1+2 tests, full Ruff, Admin full tests/build**
- [ ] **Step 3: Do not deploy Admin production and do not configure `SOFTWARE_UPDATE_ACTIVE_RELEASE_JSON`.** Push the Admin feature branch and open a **Draft PR** only; merging Admin main may auto-deploy Vercel and therefore waits for a separate production-deployment authorization.
- [ ] **Step 4: Record exact test totals/commits in Project Manager.**
