# Runtime Step 12: Packaged K1 Conformance and Feasibility Evidence

- **Task**: `RT1-K1` (Runtime Step 12)
- **Status**: `CONFORMANCE_VERIFIED`
- **Evaluated Commit (RT1_CODE_HEAD)**: `45c28c3f42e1117dc810617480894dd21d9c7a75`
- **Custody Chain Reference**: `E:\Github\artifacts\v512-k1-proof-fixtures\k1b-custody-v1.json`
- **K1B_CUSTODY_SHA256**: `4edb816634bf6fc24a9a28f42b10dd4599c1338f39defeda64acfce283c8c3a9`

---

## 1. Authority Custody Identifiers and Digests

### 1.1 K1A Profile Authority Public Custody
- **Custody File Path**: `E:\Github\authority\v512-update-profile-authority\public-v1.json`
- **Custody File SHA-256**: `0c0c602f54ac53503447e3461a24bbd118759c7af85973231960431262ba55ea`
- **Key ID**: `neko-update-profile-v512-1`
- **Public Key SHA-256**: `a81f4b684500bd6c8089bbd5954d50684276745999d10ba26c929ce51ef5651f`

### 1.2 K1A Proof Release Authority Public Custody
- **Custody File Path**: `E:\Github\authority\v512-proof-release-authority\public-v1.json`
- **Custody File SHA-256**: `2ae0901f3ef6949f6f663072540f7869547e80e110638cb04181c4468e606929`
- **Key ID**: `neko-update-proof-v512-1`
- **Public Key SHA-256**: `fc5a3ecb30951fb9ff0dc28e67ae322901a4a311b3c4c747ed820d290f80f316`

### 1.3 Authenticated Production Release Registry
- **Key ID**: `neko-update-prod-1`
- **Public Key SHA-256**: `63f58cb26a02be41ab99c2bec4d30d8f28eac7018fe949caf2bd02657d46ef50`
- **Keyset Digest (keyset_sha256)**: `263740da84b4e12d7761a0585fbfa20d543900fd739f2533b22f3bb9b287b0c1`

---

## 2. Update Trust Profiles (K1B-A)

### 2.1 Production Trust Profile
- **Path**: `E:\Github\artifacts\v512-update-trust-profiles\production\update-profile-v1.json`
- **Profile ID**: `production`
- **Channel**: `stable`
- **Repository**: `Valeneko-pranmong/Neko-Family-Proxy-Updates`
- **Envelope SHA-256**: `e3c6e3f61c468db3f026dbca7ea93fb3e784f1f427268c912c79f960d6f63f5f`
- **Payload SHA-256**: `788781a6df021c52045a431ac6f530cf36fef242f5efd42aeb2303329640f395`
- **Keyset SHA-256**: `263740da84b4e12d7761a0585fbfa20d543900fd739f2533b22f3bb9b287b0c1`
- **Release Keys**: `neko-update-prod-1`

### 2.2 Proof Trust Profile
- **Path**: `E:\Github\artifacts\v512-update-trust-profiles\proof\update-profile-v1.json`
- **Profile ID**: `proof-v512`
- **Channel**: `stable`
- **Repository**: `Valeneko-pranmong/Neko-Family-Proxy-Updates-Proof`
- **Envelope SHA-256**: `129468d07e34d5fcf6355e9123a8f860ffb8436ffce791360154123862c553c6`
- **Payload SHA-256**: `cae71ae112a2b5fad19b6bffe944e057cc03933ea8a2562f9962de0b20258bad`
- **Keyset SHA-256**: `9506a3e2e6ca972e2792c6a2d3b55e25523a64344e1103e165b0288834068e89`
- **Release Keys**: `neko-update-proof-v512-1`

---

## 3. Proof Release Envelopes (K1B-B)

### 3.1 Baseline Proof Release Envelope (`proof-k1-0001`)
- **Path**: `E:\Github\artifacts\v512-k1-proof-fixtures\baseline\release-v2.json`
- **Release ID**: `proof-k1-0001`
- **Release Sequence**: `1`
- **Mandatory**: `false`
- **Minimum Supported Sequence**: `1`
- **Key ID**: `neko-update-proof-v512-1`
- **Envelope SHA-256**: `16e4456da9d5a0deec9df76ce1faadf543f2ba97485012f19f31e4616269be31`
- **Payload SHA-256**: `24e83ff35b0a0c3c60c1230ccf1b2ac906a6e5b419914148d98d7125dbc15832`

### 3.2 Candidate Proof Release Envelope (`proof-k1-0002`)
- **Path**: `E:\Github\artifacts\v512-k1-proof-fixtures\candidate\release-v2.json`
- **Release ID**: `proof-k1-0002`
- **Release Sequence**: `2`
- **Mandatory**: `true`
- **Minimum Supported Sequence**: `2`
- **Key ID**: `neko-update-proof-v512-1`
- **Envelope SHA-256**: `e99e40d2a3219a456900a51a583ee83e4af95b96c779758220745a7f8e712993`
- **Payload SHA-256**: `b1b1959997f0b132e90f6f60dda630d034c529b98aab80dc834e06ee7b224b2d`

---

## 4. Component Identities and Package Evidence

### 4.1 Baseline Component Identities (`proof-k1-0001`)
- **Launcher**:
  - Version: `5.1.2`
  - Artifact ID: `NekoLauncher.exe`
  - Artifact Format: `raw-pe-v1`
  - Artifact Size: `30010456` bytes
  - Artifact SHA-256: `0974208b5622d8589236a60702b308a98c3b9e24704886f41bc8df3be836aefc`
  - Installed Identity SHA-256: `0974208b5622d8589236a60702b308a98c3b9e24704886f41bc8df3be836aefc`
- **Updater**:
  - Version: `5.1.2`
  - Artifact ID: `NekoUpdater.exe`
  - Artifact Format: `raw-pe-v1`
  - Artifact Size: `14357160` bytes
  - Artifact SHA-256: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
  - Installed Identity SHA-256: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
- **Core**:
  - Version: `5.1.2`
  - Artifact ID: `NekoProxyCore.zip`
  - Artifact Format: `zip-core-v1`
  - Artifact Size: `156001298` bytes
  - Artifact SHA-256: `4593d6b1bb201179df14412b4033815fa53b1e63b3b4593cf1d1e41d8721de71`
  - Installed Identity SHA-256 (core-manifest.json): `0e0cd94c0a56eb2e20897035f6445d60be9cbcfcdd21f2d0fa48c94e883a3972`
- **Baseline Components Digest**: `d3333e333d7c4d5d9d651cc4a29036d007ff984e39f687ea133a4699d32f888f`

### 4.2 Candidate Component Identities (`proof-k1-0002`)
- **Launcher**:
  - Version: `5.1.3-proof`
  - Artifact ID: `NekoLauncher.exe`
  - Artifact Format: `raw-pe-v1`
  - Artifact Size: `21` bytes
  - Artifact SHA-256: `d3c0124959c0248f9727f944eeb324199711eecc4ae0533ff6712d54f7119aff`
  - Installed Identity SHA-256: `d3c0124959c0248f9727f944eeb324199711eecc4ae0533ff6712d54f7119aff`
- **Updater**:
  - Version: `5.1.2`
  - Artifact ID: `NekoUpdater.exe`
  - Artifact Format: `raw-pe-v1`
  - Artifact Size: `14357160` bytes
  - Artifact SHA-256: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
  - Installed Identity SHA-256: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
- **Core**:
  - Version: `5.1.3-proof`
  - Artifact ID: `NekoProxyCore.zip`
  - Artifact Format: `zip-core-v1`
  - Artifact Size: `1738` bytes
  - Artifact SHA-256: `759678ee2312b950964d91e20533355b15dc17516e7e283c7302de854c4a4aca`
  - Installed Identity SHA-256 (core-manifest.json): `da1ff57d85e3e3f1de38f3a811c8717a752af5dd854a37c17f64b2ffdd52ca5a`
- **Candidate Components Digest**: `94ec76d5ce0ab1e5de8253c76fdc27a6c576a3616f7270cb4302e5e6a629241e`

### 4.3 Updater Binary Equality and Immutability
- **Production Updater SHA-256**: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
- **Proof Baseline Updater SHA-256**: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
- **Proof Candidate Updater SHA-256**: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
- **Post-Apply Installed Updater SHA-256**: `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`
- **updater_byte_identical**: `true`
- **Post-Apply Updater Byte Equality**: `PASS` (byte-for-byte identical, hash unchanged across install, staging, handoff, apply, and activation)

---

## 5. Fixed Installed Profile Path

The fixed installed profile path is:
- **Relative to install root**: `trust/update-profile-v1.json`
- **Resolved at runtime**: `<install_root>/trust/update-profile-v1.json` (where `<install_root>` is retrieved via `get_expected_install_root()` under `FOLDERID_UserProgramFiles\NEKO FAMILY`, defaulting to `%LOCALAPPDATA%\Programs\NEKO FAMILY`).
- **No Path Override**: No CLI arguments, configuration files, registry values, or environment variables can override this path.

---

## 6. Packaged Helper Boundary Conformance Results

The packaged helper boundary conformance test exercised the real helper boundary (`load_installed_update_trust_profile`, `validate_enrollment_trust_binding`, `BrokerCoordinator.begin`, staging handoff, `BrokerCoordinator.apply`, and `activate_verified_generation`):
1. **Enrollment Verification**: Installed proof profile loaded and verified; `state/enrollment.bin` pins (`profile_id="proof-v512"`, `profile_envelope_sha256="129468d07e34d5fcf6355e9123a8f860ffb8436ffce791360154123862c553c6"`, `keyset_sha256="9506a3e2e6ca972e2792c6a2d3b55e25523a64344e1103e165b0288834068e89"`) validated successfully.
2. **Begin Request**: Candidate envelope (`proof-k1-0002`) authenticated under proof profile release key `neko-update-proof-v512-1`; `REQUEST_READY` accepted with `changed={"launcher": True, "core": True}`.
3. **Staging and Handoff**: Candidate launcher (`launcher.artifact`) and core bundle (`core.artifact.zip`) staged into incoming transaction container; candidate updater was not staged and remained unchanged.
4. **Apply and Generation Build**: Candidate artifacts verified and assembled into candidate generation `g-00000000000000000002-b1b1959997f0b132e90f6f60dda630d034c529b98aab80dc834e06ee7b224b2d`; core manifest and launcher hashes verified against signed release set.
5. **Activation**: Candidate generation committed to SlotStore; committed sequence updated from `1` to `2`; committed release ID updated to `proof-k1-0002`.
6. **Updater Invariance**: Installed `NekoUpdater.exe` verified post-apply; byte contents and SHA-256 remained exactly `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f`.

---

## 7. Negative Conformance and Isolation Results

| Test Description | Expected Behavior | Actual Result | Verdict |
| :--- | :--- | :--- | :--- |
| **Proof envelopes verified by production profile** | Rejected under `neko-update-prod-1` registry (`Unknown key_id: neko-update-proof-v512-1`) | Rejected: `Unknown key_id: neko-update-proof-v512-1` | `PASS` |
| **Production envelope verified by proof profile** | Rejected under `neko-update-proof-v512-1` registry (`Unknown key_id: neko-update-prod-1`) | Rejected: `Unknown key_id: neko-update-prod-1` | `PASS` |
| **Validly signed profile replacement** | Enrolled proof client rejects validly signed production profile replacement before state/evidence read | Rejected: `EnrollmentError: PROTOCOL_INVALID` | `PASS` |
| **Tampered profile payload/signature** | Profile Authority signature verification fails | Rejected: `ValueError: Profile envelope signature verification failed` | `PASS` |
| **User trust switch / override** | Helper refuses arbitrary trust profiles, key paths, or endpoints | Rejected: `main.py` accepts zero CLI trust arguments; `--session` takes no parameters | `PASS` |
| **Fallback registry** | Packaged binary falls back to default keys if profile missing | Rejected: `FileNotFoundError` / fail-closed, no fallback registry | `PASS` |

---

## 8. Required Invariants Verification (A–G)

| Invariant | Specification Requirement | Verification Evidence | Verdict |
| :---: | :--- | :--- | :---: |
| **A** | Proof release authority/key is separate from production release authority/key | Separate key IDs (`neko-update-proof-v512-1` vs `neko-update-prod-1`), distinct public key bytes, distinct authority custody records | `PASS` |
| **B** | Packaged production Updater contains neither proof release key nor a proof fallback registry | Production trust profile and runtime registry contain only `neko-update-prod-1`; helper resolves release keys strictly from verified profile | `PASS` |
| **C** | Baseline `NekoUpdater.exe` used by proof is byte-for-byte identical to production-candidate `NekoUpdater.exe` | SHA-256 `530778a87b4a65f6cd7e56b9d0f4511db92d87e1732c6b784a46958d3a1ae51f` verified byte-identical between baseline, candidate, and production package trees | `PASS` |
| **D** | No user-controlled CLI/env/registry/config/profile-path/runtime switch can change enrolled trust | `main.py` `--session` takes 0 arguments; strictly hardcodes fixed profile path `<install_root>/trust/update-profile-v1.json` and pins | `PASS` |
| **E** | The same packaged helper implementation can authenticate/apply a proof-signed N+1 release when installed with the separately signed proof profile | Real helper boundary successfully authenticated `proof-k1-0002`, staged candidate, applied, and committed sequence 2 under proof profile | `PASS` |
| **F** | Arbitrary unsigned/self-signed profile bytes are rejected before any release envelope/state evidence is trusted | Profile verification enforces strict Ed25519 signature verification against immutable Profile Authority root before release keys are returned | `PASS` |
| **G** | `profile_id`/profile SHA/keyset SHA are immutable for one enrollment; profile replacement is fail-closed, not an in-place profile transition | Enrollment marker pins `profile_id`, `profile_envelope_sha256`, and `keyset_sha256`; replacement fails closed with `PROTOCOL_INVALID` | `PASS` |

---

## 9. Security and Isolation Guardrails

- **Zero Private Key Material**: No private key, signing secret, seed, or unredacted credential exists in this evidence or the repository.
- **Zero Secret Paths**: No paths to controller private key stores or signing enclaves are recorded.
- **Fail-Closed Verification**: All negative tests fail closed before state modification or artifact execution.
- **Single-Purpose Scope**: Conformance executed strictly within Step 12 boundary; no production sequence consumed, no production signatures created, and no downstream RT2+/RA/RH tasks begun.
