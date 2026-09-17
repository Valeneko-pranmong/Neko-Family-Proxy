#!/usr/bin/env python3
"""Build the NEKO FAMILY PROXY Closed Beta single-EXE installer.

Fail-closed orchestrator:
  1. Verifies the staged payload against the approved authorities
     (Launcher SHA-256, Core manifest source_commit, per-file hashes,
     v2ray-sn.exe SHA-256). Any disagreement aborts BEFORE compiling.
  2. Compiles installer/beta.iss with Inno Setup (ISCC.exe).
  3. Records output size + SHA-256 next to the built Setup EXE.

The staging directory lives OUTSIDE the repository; this script only reads
approved inputs and writes build outputs there.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPO = str(Path(__file__).resolve().parents[2])
LAUNCHER_SRC = os.path.join(REPO, "launcher", "src")
if LAUNCHER_SRC not in sys.path:
    sys.path.insert(0, LAUNCHER_SRC)

from neko_launcher.updater.canonical_json import canonical_json_loads  # noqa: E402
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2  # noqa: E402
from neko_launcher.updater.trust import PROFILE_AUTHORITY_PUBLIC_KEYS  # noqa: E402
from neko_launcher.updater.trust_profile import verify_update_trust_profile  # noqa: E402

STAGE = r"E:\Github\NekoBetaInstaller"
ISS_PATH = os.path.join(REPO, "installer", "beta.iss")
INSTALLER_NAME = "NekoFamilyProxy-Installer.exe"
SETUP_NAME = INSTALLER_NAME

APPROVED_V2RAY_SHA256 = (
    "a219f435671fb214c0c530084c65e576fdc1404f40b187b5586e869d2a3e4dff"
)

# ---- .NET Desktop Runtime 6 x64 bootstrapper pin ---------------------------
# The approved bootstrapper EXE is NOT yet available to this repository, so
# the pins stay UNSET and the prebuild gate below intentionally FAILS CLOSED.
# To release: stage payload\\Prereqs\\windowsdesktop-runtime-<ver>-win-x64.exe
# from an operator-approved copy, then record its version and the OFFICIAL
# vendor SHA-256 here. Never download at build time; never weaken or bypass
# this gate to ship an unverified binary.
DOTNET_BOOTSTRAPPER_GLOB = "windowsdesktop-runtime-*-win-x64.exe"
DOTNET_RUNTIME_VERSION_PIN: str | None = "6.0.36"
DOTNET_RUNTIME_SHA256_PIN: str | None = "0d20debb26fc8b2bc84f25fbd9d4596a6364af8517ebf012e8b871127b798941"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class PrebuildGateError(ValueError):
    """Raised when a candidate fails a prebuild authority or payload gate."""


def fail(message: str) -> "None":
    raise PrebuildGateError(message)


def find_iscc() -> str:
    candidates = [
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Programs", "Inno Setup 6", "ISCC.exe",
        ),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    fail("ISCC.exe not found (per-user or machine-wide)")


def canonical_sha256(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("SHA-256 must be exactly 64 lowercase hexadecimal characters")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--launcher-sha256", required=True, type=canonical_sha256)
    parser.add_argument("--updater-sha256", required=True, type=canonical_sha256)
    parser.add_argument("--core-authority", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--baseline-envelope", required=True)
    parser.add_argument("--trust-profile", required=True)
    args = parser.parse_args(argv)
    if not re.match(r"^5\.1\.\d+$", args.release_version):
        parser.error("--release-version must be stable 5.1.x format (e.g., 5.1.3)")
    if not args.core_authority.strip():
        parser.error("--core-authority must not be empty")
    return args


def build_candidate(args: argparse.Namespace) -> int:
    stage = os.path.abspath(args.candidate_dir)
    payload = os.path.join(stage, "payload")
    core_bundle = os.path.join(payload, "CoreBundle")
    out_dir = os.path.join(stage, "out")

    if not os.path.isfile(ISS_PATH):
        fail(f"missing {ISS_PATH}")

    # ---- gate 1: approved Launcher -----------------------------------------
    launcher = os.path.join(payload, "NekoLauncher.exe")
    if not os.path.isfile(launcher):
        fail(f"missing staged launcher: {launcher}")
    got = sha256_file(launcher)
    if got != args.launcher_sha256:
        raise ValueError(f"launcher sha mismatch: {got}")
    print("GATE launcher-sha256=PASS")

    # ---- gate 2: staged Updater presence, digest, and local self-check -------
    updater = os.path.join(payload, "NekoUpdater.exe")
    if not os.path.isfile(updater):
        fail(f"missing staged updater: {updater}")
    updater_sha256 = sha256_file(updater)
    if updater_sha256 != args.updater_sha256:
        raise ValueError(f"updater sha mismatch: {updater_sha256}")
    print("GATE updater-sha256=PASS")
    try:
        updater_check = subprocess.run(
            [updater, "--self-check"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        fail("staged updater self-check timed out")
    except OSError as exc:
        fail(f"could not execute staged updater self-check: {exc}")
    if updater_check.returncode != 0:
        fail(f"staged updater self-check exited {updater_check.returncode}")
    print("GATE updater-self-check=PASS")

    # ---- gate 3: Core manifest authority + every declared file -------------
    manifest_path = os.path.join(core_bundle, "core-manifest.json")
    if not os.path.isfile(manifest_path):
        fail(f"missing {manifest_path}")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("source_commit") != args.core_authority:
        fail(f"source_commit mismatch: {manifest.get('source_commit')}")
    bad: list[str] = []
    files_obj = manifest["files"]
    items = [(item["path"], item["sha256"]) for item in files_obj] if isinstance(files_obj, list) else files_obj.items()
    for rel, want in items:
        p = os.path.join(core_bundle, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            bad.append(f"MISSING {rel}")
        elif sha256_file(p) != want:
            bad.append(f"HASH {rel}")
    if bad:
        fail(f"{len(bad)} core files bad; first: {bad[0]}")
    print(f"GATE core-manifest=PASS ({len(manifest['files'])} files)")

    # ---- gate: trust profile & baseline envelope authority & staging --------
    if not os.path.isfile(args.trust_profile):
        fail(f"missing trust profile: {args.trust_profile}")
    if not os.path.isfile(args.baseline_envelope):
        fail(f"missing baseline envelope: {args.baseline_envelope}")

    with open(args.trust_profile, "rb") as fh:
        raw_trust_profile = fh.read()
    with open(args.baseline_envelope, "rb") as fh:
        raw_baseline_envelope = fh.read()

    try:
        verified_profile = verify_update_trust_profile(
            raw_trust_profile,
            profile_authority_public_keys=PROFILE_AUTHORITY_PUBLIC_KEYS,
        )
    except Exception as exc:
        fail(f"trust profile verification failed: {exc}")

    try:
        envelope_doc = canonical_json_loads(raw_baseline_envelope.strip())
    except Exception as exc:
        fail(f"baseline envelope JSON parsing failed: {exc}")

    try:
        release_set, payload_sha256 = verify_release_envelope_v2(
            envelope_doc,
            dict(verified_profile.release_public_keys),
        )
    except Exception as exc:
        fail(f"baseline envelope verification failed: {exc}")

    key_id = envelope_doc.get("key_id")
    if not key_id:
        fail("missing key_id in baseline envelope")

    if release_set.channel != verified_profile.channel:
        fail(
            f"baseline envelope channel mismatch: {release_set.channel} != {verified_profile.channel}"
        )

    # Component identity verification against staged bytes
    components = release_set.components
    for req_comp in ("launcher", "updater", "core"):
        if req_comp not in components:
            fail(f"baseline envelope missing required component: {req_comp}")

    launcher_comp = components["launcher"]
    if launcher_comp.installed_identity_sha256 != got:
        fail(
            f"baseline envelope launcher installed identity mismatch: "
            f"{launcher_comp.installed_identity_sha256} != {got}"
        )

    updater_comp = components["updater"]
    if updater_comp.installed_identity_sha256 != updater_sha256:
        fail(
            f"baseline envelope updater installed identity mismatch: "
            f"{updater_comp.installed_identity_sha256} != {updater_sha256}"
        )

    core_comp = components["core"]
    staged_core_installed_identity = sha256_file(manifest_path)
    if core_comp.installed_identity_sha256 != staged_core_installed_identity:
        fail(
            f"baseline envelope core installed identity mismatch: "
            f"{core_comp.installed_identity_sha256} != {staged_core_installed_identity}"
        )

    # Stage exact bytes at baseline\release-v2.json and trust\update-profile-v1.json
    baseline_dir = os.path.join(payload, "baseline")
    trust_dir = os.path.join(payload, "trust")
    os.makedirs(baseline_dir, exist_ok=True)
    os.makedirs(trust_dir, exist_ok=True)

    staged_envelope_path = os.path.join(baseline_dir, "release-v2.json")
    staged_profile_path = os.path.join(trust_dir, "update-profile-v1.json")

    with open(staged_envelope_path, "wb") as fh:
        fh.write(raw_baseline_envelope)
    with open(staged_profile_path, "wb") as fh:
        fh.write(raw_trust_profile)

    # Hash after copy and require input/staged byte equality
    input_envelope_sha256 = hashlib.sha256(raw_baseline_envelope).hexdigest()
    staged_envelope_sha256 = sha256_file(staged_envelope_path)
    if staged_envelope_sha256 != input_envelope_sha256:
        fail("staged baseline envelope hash mismatch after copy")
    with open(staged_envelope_path, "rb") as fh:
        staged_envelope_bytes = fh.read()
        if staged_envelope_bytes != raw_baseline_envelope:
            fail("staged baseline envelope bytes mismatch after copy")

    input_profile_sha256 = hashlib.sha256(raw_trust_profile).hexdigest()
    staged_profile_sha256 = sha256_file(staged_profile_path)
    if staged_profile_sha256 != input_profile_sha256:
        fail("staged trust profile hash mismatch after copy")
    with open(staged_profile_path, "rb") as fh:
        staged_profile_bytes = fh.read()
        if staged_profile_bytes != raw_trust_profile:
            fail("staged trust profile bytes mismatch after copy")

    # Re-verify the staged embedded envelope
    try:
        staged_doc = canonical_json_loads(staged_envelope_bytes.strip())
        staged_set, staged_payload_sha = verify_release_envelope_v2(
            staged_doc,
            dict(verified_profile.release_public_keys),
        )
    except Exception as exc:
        fail(f"staged baseline envelope re-verification failed: {exc}")
    if staged_doc.get("key_id") != key_id:
        fail(f"staged baseline envelope key_id mismatch: {staged_doc.get('key_id')} != {key_id}")
    if staged_set.release_sequence != release_set.release_sequence:
        fail("staged baseline envelope sequence mismatch")
    if staged_set.release_id != release_set.release_id:
        fail("staged baseline envelope release_id mismatch")
    if staged_payload_sha != payload_sha256:
        fail("staged baseline envelope payload sha mismatch")

    print("GATE trust-profile=PASS")
    print("GATE baseline-envelope=PASS")

    # Resolve the compiler only after all operator-supplied candidate authorities
    # have passed. Payload gates below still run before ISCC is invoked.
    iscc = find_iscc()

    # ---- gate 3: v2ray-sn.exe approved hash --------------------------------
    v2ray = os.path.join(core_bundle, "bin", "v2ray-sn.exe")
    if not os.path.isfile(v2ray):
        fail("missing bin/v2ray-sn.exe in staged bundle")
    got = sha256_file(v2ray)
    if got != APPROVED_V2RAY_SHA256 or got != manifest.get(
        "v2ray_sn_exe_hash", APPROVED_V2RAY_SHA256
    ):
        fail(f"v2ray-sn.exe sha mismatch: {got}")
    print("GATE v2ray-sn-sha256=PASS")

    # ---- gate 4: pinned .NET Desktop Runtime 6 x64 bootstrapper -------------
    prereq_dir = os.path.join(payload, "Prereqs")
    bootstrappers = sorted(
        glob.glob(os.path.join(prereq_dir, DOTNET_BOOTSTRAPPER_GLOB))
    )
    if len(bootstrappers) != 1:
        fail(
            "ยังไม่มีไฟล์ .NET Desktop Runtime x64 bootstrapper ที่อนุมัติ — "
            "missing approved .NET Desktop Runtime x64 bootstrapper: "
            f"expected exactly one {DOTNET_BOOTSTRAPPER_GLOB} under {prereq_dir}, "
            f"found {len(bootstrappers)}. Stage the approved EXE at that path, then "
            "set DOTNET_RUNTIME_VERSION_PIN and DOTNET_RUNTIME_SHA256_PIN in this "
            "script. Build refuses to continue without a verified binary."
        )
    if DOTNET_RUNTIME_VERSION_PIN is None or DOTNET_RUNTIME_SHA256_PIN is None:
        fail(
            ".NET Desktop Runtime pin ยังไม่ถูกบันทึก — .NET Runtime pin not "
            "recorded: the staged bootstrapper exists but DOTNET_RUNTIME_VERSION_PIN / "
            "DOTNET_RUNTIME_SHA256_PIN are unset. Record the approved version and its "
            "official vendor SHA-256 before building; refusing to ship an unverified "
            "binary."
        )
    bootstrapper = bootstrappers[0]
    expected_name = (
        f"windowsdesktop-runtime-{DOTNET_RUNTIME_VERSION_PIN}-win-x64.exe"
    )
    if os.path.basename(bootstrapper) != expected_name:
        fail(
            f"bootstrapper filename mismatch: staged "
            f"{os.path.basename(bootstrapper)}, pinned {expected_name}"
        )
    got = sha256_file(bootstrapper)
    if got != DOTNET_RUNTIME_SHA256_PIN.lower():
        fail(f"dotnet-bootstrapper sha mismatch: {got}")
    print("GATE dotnet-bootstrapper-sha256=PASS")

    # ---- gate 5: secret hygiene on the payload ------------------------------
    if os.path.exists(os.path.join(core_bundle, "runtime-settings.key")):
        fail("plaintext runtime-settings.key present in payload")
    nkps = [
        os.path.relpath(os.path.join(r, f), payload)
        for r, _, fs in os.walk(payload)
        for f in fs
        if f.endswith(".nkps")
    ]
    if nkps != os.path.join("CoreBundle", "runtime-settings.nkps") and not nkps:
        fail("runtime-settings.nkps missing from payload")
    hits = []
    for root, _, files in os.walk(core_bundle):
        for name in files:
            if name.lower().endswith((".json", ".txt", ".xml", ".ini", ".conf")):
                p = os.path.join(root, name)
                try:
                    text = open(p, encoding="utf-8", errors="ignore").read()
                except OSError:
                    continue
                for token in ("sb_secret_", "service_role",
                              "BEGIN PRIVATE KEY", "BEGIN RSA"):
                    if token in text:
                        hits.append((token, os.path.relpath(p, core_bundle)))
    if hits:
        fail(f"secret-like tokens in payload: {hits[:3]}")
    print("GATE secret-hygiene=PASS")

    # ---- gate 6: installer helper scripts present ---------------------------
    scripts_dir = os.path.join(REPO, "installer", "scripts")
    for s in ("verify-core-install.ps1", "ensure-netfilter2.ps1"):
        if not os.path.isfile(os.path.join(scripts_dir, s)):
            fail(f"missing helper script {s}")
    if not os.path.isfile(ISS_PATH):
        fail(f"missing {ISS_PATH}")
    print("GATE installer-source=PASS")

    # ---- compile -------------------------------------------------------------
    os.makedirs(out_dir, exist_ok=True)
    proc = subprocess.run(
        [
            iscc,
            f"/DPayloadDir={payload}",
            f"/DBuildOutDir={out_dir}",
            f"/DMyAppVersion={args.release_version}",
            f"/DMyAppDisplayVersion={args.release_version}",
            f"/DCoreAuthority={args.core_authority}",
            "/Qp",
            ISS_PATH,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        fail(f"ISCC exited {proc.returncode}")

    setup_path = os.path.join(out_dir, SETUP_NAME)
    if not os.path.isfile(setup_path):
        fail("Setup EXE not produced")
    size = os.path.getsize(setup_path)
    digest = sha256_file(setup_path)

    record = {
        "release_version": args.release_version,
        "installer_file": SETUP_NAME,
        "installer_size_bytes": size,
        "installer_sha256": digest,
        "launcher_sha256": args.launcher_sha256,
        "updater_sha256": args.updater_sha256,
        "core_authority": args.core_authority,
        "core_installed_identity": sha256_file(manifest_path),
        "v2ray_sha256": APPROVED_V2RAY_SHA256,
        "dotnet_desktop_runtime": {
            "version": DOTNET_RUNTIME_VERSION_PIN,
            "sha256": DOTNET_RUNTIME_SHA256_PIN,
        },
        "sequence": release_set.release_sequence,
        "release_id": release_set.release_id,
        "key_id": key_id,
        "payload_sha256": payload_sha256,
        "envelope_sha256": staged_envelope_sha256,
        "embedded_envelope_sha256": staged_envelope_sha256,
        "embedded_trust_profile_sha256": staged_profile_sha256,
        "profile_id": verified_profile.profile_id,
        "keyset_sha256": verified_profile.keyset_sha256,
    }
    record_path = os.path.join(out_dir, "build-record.json")
    with open(record_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)

    print("BUILD=PASS")
    print(json.dumps(record, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return build_candidate(parse_args(argv))
    except PrebuildGateError as exc:
        print(f"PREBUILD_GATE=FAIL: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
