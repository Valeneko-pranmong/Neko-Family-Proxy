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

import glob
import hashlib
import json
import os
import subprocess
import sys

REPO = r"E:\Github\Neko-Family-Proxy"
STAGE = r"E:\Github\NekoBetaInstaller"
PAYLOAD = os.path.join(STAGE, "payload")
CORE_BUNDLE = os.path.join(PAYLOAD, "CoreBundle")
OUT_DIR = os.path.join(STAGE, "out")
ISS_PATH = os.path.join(REPO, "installer", "beta.iss")
SETUP_NAME = "NekoFamilyProxy-Beta-Setup.exe"

APPROVED_LAUNCHER_SHA256 = (
    "0a24b1945d6c390b760d37940eee929100121d88a25ad27d6874f234a8ca0ebb"
)
CORE_AUTHORITY_COMMIT = "33f97ae0110075089f39b1e123890f931417d907"
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


def fail(message: str) -> "None":
    print(f"PREBUILD_GATE=FAIL: {message}")
    sys.exit(2)


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


def main() -> int:
    # ---- gate 1: approved Launcher -----------------------------------------
    launcher = os.path.join(PAYLOAD, "NekoLauncher.exe")
    if not os.path.isfile(launcher):
        fail(f"missing staged launcher: {launcher}")
    got = sha256_file(launcher)
    if got != APPROVED_LAUNCHER_SHA256:
        fail(f"launcher sha mismatch: {got}")
    print("GATE launcher-sha256=PASS")

    # ---- gate 2: Core manifest authority + every declared file -------------
    manifest_path = os.path.join(CORE_BUNDLE, "core-manifest.json")
    if not os.path.isfile(manifest_path):
        fail(f"missing {manifest_path}")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("source_commit") != CORE_AUTHORITY_COMMIT:
        fail(f"source_commit mismatch: {manifest.get('source_commit')}")
    bad: list[str] = []
    for rel, want in manifest["files"].items():
        p = os.path.join(CORE_BUNDLE, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            bad.append(f"MISSING {rel}")
        elif sha256_file(p) != want:
            bad.append(f"HASH {rel}")
    if bad:
        fail(f"{len(bad)} core files bad; first: {bad[0]}")
    print(f"GATE core-manifest=PASS ({len(manifest['files'])} files)")

    # ---- gate 3: v2ray-sn.exe approved hash --------------------------------
    v2ray = os.path.join(CORE_BUNDLE, "bin", "v2ray-sn.exe")
    if not os.path.isfile(v2ray):
        fail("missing bin/v2ray-sn.exe in staged bundle")
    got = sha256_file(v2ray)
    if got != APPROVED_V2RAY_SHA256 or got != manifest.get(
        "v2ray_sn_exe_hash", APPROVED_V2RAY_SHA256
    ):
        fail(f"v2ray-sn.exe sha mismatch: {got}")
    print("GATE v2ray-sn-sha256=PASS")

    # ---- gate 4: pinned .NET Desktop Runtime 6 x64 bootstrapper -------------
    prereq_dir = os.path.join(PAYLOAD, "Prereqs")
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
    if os.path.exists(os.path.join(CORE_BUNDLE, "runtime-settings.key")):
        fail("plaintext runtime-settings.key present in payload")
    nkps = [
        os.path.relpath(os.path.join(r, f), PAYLOAD)
        for r, _, fs in os.walk(PAYLOAD)
        for f in fs
        if f.endswith(".nkps")
    ]
    if nkps != os.path.join("CoreBundle", "runtime-settings.nkps") and not nkps:
        fail("runtime-settings.nkps missing from payload")
    hits = []
    for root, _, files in os.walk(CORE_BUNDLE):
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
                        hits.append((token, os.path.relpath(p, CORE_BUNDLE)))
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
    iscc = find_iscc()
    os.makedirs(OUT_DIR, exist_ok=True)
    proc = subprocess.run(
        [
            iscc,
            f"/DPayloadDir={PAYLOAD}",
            f"/DBuildOutDir={OUT_DIR}",
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

    setup_path = os.path.join(OUT_DIR, SETUP_NAME)
    if not os.path.isfile(setup_path):
        fail("Setup EXE not produced")
    size = os.path.getsize(setup_path)
    digest = sha256_file(setup_path)

    record = {
        "installer_version": "1.0.0.1 (1.0.0-beta.1)",
        "installer_file": SETUP_NAME,
        "installer_size_bytes": size,
        "installer_sha256": digest,
        "launcher_sha256": APPROVED_LAUNCHER_SHA256,
        "core_authority": CORE_AUTHORITY_COMMIT,
        "v2ray_sha256": APPROVED_V2RAY_SHA256,
        "dotnet_desktop_runtime": {
            "version": DOTNET_RUNTIME_VERSION_PIN,
            "sha256": DOTNET_RUNTIME_SHA256_PIN,
        },
    }
    record_path = os.path.join(OUT_DIR, "build-record.json")
    with open(record_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)

    print("BUILD=PASS")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
