"""R2 tests-only contract for Phase 3 Slice K Unit 2 generation_builder."""

from __future__ import annotations

import base64
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
import ctypes
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile

import pytest

from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.state_models import Binding, Generation, Mutation, State, Transaction
from neko_launcher.updater.win32_directory import (
    create_incoming_container,
    get_directory_identity,
    open_directory_guarded,
)
from tests.software_update_helpers import (
    TEST_KEY_ID,
    TEST_PUBLIC_KEY,
    signed_envelope,
    valid_release_document,
)

CORE = {
    "NekoProxyCore.exe": b"exe",
    "NekoProxyCore.dll": b"dll",
    "runtime-settings.nkps": b"nkps",
    "bin/Redirector.bin": b"bin",
    "bin/nfapi.dll": b"nfapi",
    "bin/v2ray-sn.exe": b"v2ray",
}
CORE_FILES = {"canonical-core-manifest.json", *CORE}
FILES = {"release-envelope.json", "NekoLauncher.exe", *(f"ProxyCore/{p}" for p in CORE_FILES)}
DIRS = {"ProxyCore", "ProxyCore/bin"}


def _bundle(root: Path, *, salt: bytes = b"") -> str:
    hashes = {}
    total = 0
    for name, original in CORE.items():
        data = original + salt
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
        total += len(data)
    manifest = {
        "source_commit": "1234567",
        "candidate": "5.1.0",
        "authority": "test",
        "file_count": len(CORE),
        "total_bytes": total,
        "neko_proxy_core_exe_hash": hashes["NekoProxyCore.exe"],
        "neko_proxy_core_dll_hash": hashes["NekoProxyCore.dll"],
        "protected_settings_payload_hash": hashes["runtime-settings.nkps"],
        "redirector_bin_hash": hashes["bin/Redirector.bin"],
        "nfapi_dll_hash": hashes["bin/nfapi.dll"],
        "v2ray_sn_exe_hash": hashes["bin/v2ray-sn.exe"],
        "security": {
            "runtime_settings_key_files": 0,
            "plaintext_settings_files": 0,
            "plaintext_secret_marker_hits": 0,
            "external_dotnet_dependency": False,
        },
        "files": hashes,
    }
    raw = canonical_json_dumps(manifest)
    (root / "canonical-core-manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _archive(tmp: Path) -> tuple[Path, str, str]:
    source = tmp / "new-core-source"
    source.mkdir()
    identity = _bundle(source, salt=b"-new")
    path = tmp / "new-core.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(source.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(source).as_posix())
    raw = path.read_bytes()
    return path, hashlib.sha256(raw).hexdigest(), identity


class Env:
    def __init__(
        self, tmp: Path, *, launcher_changed: bool = True, core_changed: bool = True
    ) -> None:
        self.root, self.keys = tmp, {TEST_KEY_ID: TEST_PUBLIC_KEY}
        self.request_id, self.tx_id = "a" * 32, "b" * 32
        self.old_launcher, self.new_launcher = b"old-launcher", b"new-launcher"
        self.old_launcher_sha = hashlib.sha256(self.old_launcher).hexdigest()
        self.new_launcher_sha = hashlib.sha256(self.new_launcher).hexdigest()
        old_source = tmp / "old-core-source"
        old_source.mkdir()
        self.old_core_sha = _bundle(old_source)
        self.core_zip, self.core_zip_sha, self.new_core_sha = _archive(tmp)
        old_payload, self.old_envelope = self.sign(
            1, self.old_launcher_sha, len(self.old_launcher), "d" * 64, 1, self.old_core_sha
        )
        self.old_envelope_b64 = base64.b64encode(self.old_envelope).decode("ascii")
        self.old = Generation(
            Binding(1, "rel-1", hashlib.sha256(old_payload).hexdigest()),
            self.old_launcher_sha,
            self.old_core_sha,
        )
        self.old_dir = tmp / "releases" / self.gen_id(self.old)
        (self.old_dir / "ProxyCore").mkdir(parents=True)
        (self.old_dir / "NekoLauncher.exe").write_bytes(self.old_launcher)
        for source in old_source.rglob("*"):
            if source.is_file():
                target = self.old_dir / "ProxyCore" / source.relative_to(old_source)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        (self.old_dir / "release-envelope.json").write_bytes(self.old_envelope)
        launcher_sha = self.new_launcher_sha if launcher_changed else self.old_launcher_sha
        core_sha = self.core_zip_sha if core_changed else "d" * 64
        core_size = self.core_zip.stat().st_size if core_changed else 1
        core_identity = self.new_core_sha if core_changed else self.old_core_sha
        self.payload, self.envelope = self.sign(
            2,
            launcher_sha,
            len(self.new_launcher if launcher_changed else self.old_launcher),
            core_sha,
            core_size,
            core_identity,
        )
        self.payload_sha = hashlib.sha256(self.payload).hexdigest()
        self.envelope_b64 = base64.b64encode(self.envelope).decode("ascii")
        self.candidate = Generation(
            Binding(2, "rel-2", self.payload_sha), launcher_sha, core_identity
        )
        self.in_handle, incoming_identity, self.incoming = create_incoming_container(
            tmp, self.request_id
        )
        (tmp / "staging").mkdir()
        self.staging = tmp / "staging" / self.tx_id
        self.staging.mkdir()
        self.stg_handle = open_directory_guarded(self.staging)
        staging_identity = get_directory_identity(self.stg_handle)
        if launcher_changed:
            (self.incoming / "launcher.artifact").write_bytes(self.new_launcher)
        if core_changed:
            (self.incoming / "core.artifact.zip").write_bytes(self.core_zip.read_bytes())
        tx = Transaction(
            self.tx_id,
            self.request_id,
            self.candidate,
            self.old,
            incoming_identity,
            staging_identity,
            "BUILDING",
            Mutation("WRITE_CANDIDATE", "stage", "INTENT"),
        )
        self.state = State(
            1,
            2,
            "1" * 32,
            1,
            True,
            "PREPARING",
            self.old,
            None,
            self.old.binding,
            self.candidate.binding,
            None,
            tx,
            None,
            None,
            None,
            {
                self.old.binding.payload_sha256: self.old_envelope_b64,
                self.payload_sha: self.envelope_b64,
            },
        )

    def sign(
        self,
        seq: int,
        launcher_sha: str,
        launcher_size: int,
        core_sha: str,
        core_size: int,
        core_identity: str,
        *,
        pmin: int = 1,
        pmax: int = 1,
        key_id: str = TEST_KEY_ID,
    ) -> tuple[bytes, bytes]:
        doc = valid_release_document()
        doc.update(
            schema_version=2,
            release_sequence=seq,
            release_id=f"rel-{seq}",
            updater_protocol={"minimum": pmin, "maximum": pmax},
        )
        doc["components"]["launcher"].update(
            artifact_format="raw-pe-v1",
            artifact_sha256=launcher_sha,
            installed_identity_sha256=launcher_sha,
            artifact_size=launcher_size,
        )
        doc["components"]["core"].update(
            artifact_format="zip-core-v1",
            artifact_sha256=core_sha,
            installed_identity_sha256=core_identity,
            artifact_size=core_size,
        )
        envelope = canonical_json_dumps(signed_envelope(doc, key_id=key_id))
        payload = base64.b64decode(json.loads(envelope)["payload_b64"], validate=True)
        return payload, envelope

    def resign(
        self,
        *,
        artifact: bytes | None = None,
        identity: str | None = None,
        pmin: int = 1,
        pmax: int = 1,
        key_id: str = TEST_KEY_ID,
    ) -> None:
        raw = self.core_zip.read_bytes() if artifact is None else artifact
        installed = self.new_core_sha if identity is None else identity
        payload, envelope = self.sign(
            2,
            self.new_launcher_sha,
            len(self.new_launcher),
            hashlib.sha256(raw).hexdigest(),
            len(raw),
            installed,
            pmin=pmin,
            pmax=pmax,
            key_id=key_id,
        )
        digest = hashlib.sha256(payload).hexdigest()
        candidate = Generation(Binding(2, "rel-2", digest), self.new_launcher_sha, installed)
        evidence = {
            self.old.binding.payload_sha256: self.old_envelope_b64,
            digest: base64.b64encode(envelope).decode("ascii"),
        }
        (self.incoming / "core.artifact.zip").write_bytes(raw)
        self.payload, self.envelope, self.payload_sha = payload, envelope, digest
        self.envelope_b64, self.candidate = evidence[digest], candidate
        self.state = replace(
            self.state,
            observed=candidate.binding,
            evidence=evidence,
            transaction=replace(self.state.transaction, candidate=candidate),
        )

    @staticmethod
    def gen_id(generation: Generation) -> str:
        return f"g-{generation.binding.release_sequence:020d}-{generation.binding.payload_sha256}"

    def close_handle(self, which: str) -> None:
        name = "in_handle" if which == "incoming" else "stg_handle"
        handle = getattr(self, name)
        if handle != -1:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
            setattr(self, name, -1)

    def close(self) -> None:
        self.close_handle("incoming")
        self.close_handle("staging")


def _safe_error(
    env: Env,
    builder: object,
    code: str,
    caplog: pytest.LogCaptureFixture,
    details: tuple[str, ...] = (),
    capsys: pytest.CaptureFixture[str] | None = None,
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    error_type, build = (
        getattr(builder, "GenerationBuildError"),
        getattr(builder, "build_generation"),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr), pytest.raises(error_type) as raised:
        build(env.root, env.state, env.keys)
    error = raised.value
    assert error.code == code and str(error) == code and error.args == (code,)
    assert error.__cause__ is None
    if error.__context__ is not None:
        assert error.__suppress_context__
    captured = capsys.readouterr() if capsys is not None else None
    rendered = str(error) + caplog.text + stdout.getvalue() + stderr.getvalue()
    if captured is not None:
        rendered += captured.out + captured.err
    evidence_secrets: list[str] = []
    for encoded in env.state.evidence.values():
        evidence_secrets.append(encoded)
        try:
            raw = base64.b64decode(encoded, validate=True)
            evidence_secrets.append(raw.decode("utf-8", "replace"))
            document = json.loads(raw)
            if isinstance(document, dict):
                for key in ("payload_b64", "signature_b64"):
                    value = document.get(key)
                    if isinstance(value, str):
                        evidence_secrets.append(value)
        except (ValueError, UnicodeError, json.JSONDecodeError):
            pass
    forbidden = (
        str(env.root),
        str(env.incoming),
        str(env.staging),
        str(env.old_dir),
        env.envelope.decode("utf-8", "replace"),
        env.envelope_b64,
        *evidence_secrets,
        env.old_envelope.decode("utf-8"),
        env.old_envelope_b64,
        "payload_b64",
        "signature_b64",
        "{",
        *details,
    )
    assert all(value not in rendered for value in forbidden)


def _tree(root: Path) -> tuple[set[str], set[str]]:
    files, dirs = set(), set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        info = path.stat(follow_symlinks=False)
        assert not path.is_symlink() and not (
            info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
        assert stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
        (files if stat.S_ISREG(info.st_mode) else dirs).add(relative)
    return files, dirs


def _snapshot(root: Path) -> dict[str, tuple[str, bool, bytes | None]]:
    snapshot = {}
    for path in [root, *root.rglob("*")]:
        info = path.stat(follow_symlinks=False)
        kind = (
            "file"
            if stat.S_ISREG(info.st_mode)
            else "directory"
            if stat.S_ISDIR(info.st_mode)
            else "other"
        )
        reparse = bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        content = path.read_bytes() if kind == "file" else None
        snapshot[path.relative_to(root).as_posix()] = (kind, reparse, content)
    return snapshot


def _actual_bad_zip_message(raw: bytes) -> str:
    """Obtain the platform/runtime's real upstream ZIP parser detail."""
    with pytest.raises(zipfile.BadZipFile) as raised:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            archive.infolist()
    detail = str(raised.value)
    assert detail
    return detail


@pytest.mark.parametrize(("lc", "cc"), [(True, False), (False, True), (True, True), (False, False)])
def test_exact_whole_fresh_generation(tmp_path: Path, lc: bool, cc: bool) -> None:
    from neko_launcher.updater.generation_builder import build_generation

    env = Env(tmp_path, launcher_changed=lc, core_changed=cc)
    try:
        assert env.old_core_sha != env.new_core_sha
        before = {root: _snapshot(root) for root in (env.old_dir, env.incoming)}
        result = build_generation(env.root, env.state, env.keys)
        assert result.changed == {"launcher": lc, "core": cc}
        assert result.generation_id == env.gen_id(env.candidate)
        assert (
            result.generation_dir == env.staging / "generation"
            and result.generation == env.candidate
        )
        assert _tree(result.generation_dir) == (FILES, DIRS)
        assert (result.generation_dir / "release-envelope.json").read_bytes() == env.envelope
        assert (result.generation_dir / "NekoLauncher.exe").read_bytes() == (
            env.new_launcher if lc else env.old_launcher
        )
        expected_core = env.root / ("new-core-source" if cc else "old-core-source")
        for relative in CORE_FILES:
            assert (result.generation_dir / "ProxyCore" / relative).read_bytes() == (
                expected_core / relative
            ).read_bytes()
        manifest = result.generation_dir / "ProxyCore" / "canonical-core-manifest.json"
        assert (
            hashlib.sha256(manifest.read_bytes()).hexdigest() == env.candidate.core_identity_sha256
        )
        assert all(_snapshot(root) == snapshot for root, snapshot in before.items())
        output_stats = [p.stat() for p in result.generation_dir.rglob("*") if p.is_file()]
        assert all(item.st_nlink == 1 for item in output_stats)
        assert len({(s.st_dev, s.st_ino) for s in output_stats}) == len(output_stats)
        sources = []
        if lc:
            sources.append(env.incoming / "launcher.artifact")
        else:
            sources.append(env.old_dir / "NekoLauncher.exe")
        if not cc:
            sources.extend(env.old_dir / "ProxyCore" / p for p in CORE_FILES)
        source_ids = {(p.stat().st_dev, p.stat().st_ino) for p in sources}
        assert not source_ids & {(s.st_dev, s.st_ino) for s in output_stats}
        generation_info = result.generation_dir.stat(follow_symlinks=False)
        assert not (generation_info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        generation_identity = (generation_info.st_dev, generation_info.st_ino)
        authority_identities = {
            (path.stat().st_dev, path.stat().st_ino)
            for path in (env.incoming, env.staging, env.old_dir)
        }
        assert generation_identity not in authority_identities
    finally:
        env.close()


def test_flushes_every_completed_file_at_least_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env, calls = Env(tmp_path), []
    real = builder._flush_file  # Narrow OS-boundary seam, not business API.
    generation = env.staging / "generation"

    def validating_flush(path: Path) -> None:
        relative = path.relative_to(generation).as_posix()
        if relative == "release-envelope.json":
            expected = env.envelope
        elif relative == "NekoLauncher.exe":
            expected = env.new_launcher
        else:
            expected = (
                env.root / "new-core-source" / relative.removeprefix("ProxyCore/")
            ).read_bytes()
        assert path.read_bytes() == expected
        real(path)
        calls.append(path)

    monkeypatch.setattr(builder, "_flush_file", validating_flush)
    try:
        result = builder.build_generation(env.root, env.state, env.keys)
        counts = Counter(p.relative_to(result.generation_dir).as_posix() for p in calls)
        assert set(counts) == FILES and all(count >= 1 for count in counts.values())
    finally:
        env.close()


def test_flush_failure_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    monkeypatch.setattr(
        builder, "_flush_file", lambda _path: (_ for _ in ()).throw(OSError("FLUSH_DETAIL"))
    )
    try:
        _safe_error(env, builder, "FLUSH_FAILED", caplog, ("FLUSH_DETAIL",))
    finally:
        env.close()


@pytest.mark.parametrize(("entry", "directory"), [("extra.bin", False), ("extra", True)])
def test_unexpected_entry_is_package_invalid(
    tmp_path: Path, entry: str, directory: bool, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        path = env.incoming / entry
        path.mkdir() if directory else path.write_bytes(b"extra")
        _safe_error(env, builder, "PACKAGE_INVALID", caplog)
    finally:
        env.close()


@pytest.mark.parametrize("component", ["launcher", "core"])
def test_size_mismatch(tmp_path: Path, component: str, caplog: pytest.LogCaptureFixture) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        name = "launcher.artifact" if component == "launcher" else "core.artifact.zip"
        path = env.incoming / name
        path.write_bytes(path.read_bytes() + b"x")
        _safe_error(env, builder, "SIZE_MISMATCH", caplog)
    finally:
        env.close()


@pytest.mark.parametrize("component", ["launcher", "core"])
def test_missing_changed_artifact(
    tmp_path: Path, component: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        (
            env.incoming / ("launcher.artifact" if component == "launcher" else "core.artifact.zip")
        ).unlink()
        _safe_error(env, builder, "ARTIFACT_MISSING", caplog)
    finally:
        env.close()


@pytest.mark.parametrize("component", ["launcher", "core"])
def test_same_size_hash_mismatch(
    tmp_path: Path, component: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        path = env.incoming / (
            "launcher.artifact" if component == "launcher" else "core.artifact.zip"
        )
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        _safe_error(env, builder, "HASH_MISMATCH", caplog)
    finally:
        env.close()


@pytest.mark.parametrize("field", ["volume_serial", "file_id", "parent_file_id"])
@pytest.mark.parametrize("which", ["incoming", "staging"])
def test_directory_identity_mismatch(
    tmp_path: Path, which: str, field: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        tx = env.state.transaction
        identity = getattr(tx, which)
        value = "f" * (16 if field == "volume_serial" else 32)
        env.state = replace(
            env.state, transaction=replace(tx, **{which: replace(identity, **{field: value})})
        )
        _safe_error(env, builder, "PATH_REJECTED", caplog)
    finally:
        env.close()


@pytest.mark.parametrize("field", ["id", "request_id"])
def test_derived_directory_name_mismatch_is_path_rejected(
    tmp_path: Path, field: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        env.state = replace(
            env.state, transaction=replace(env.state.transaction, **{field: "c" * 32})
        )
        _safe_error(env, builder, "PATH_REJECTED", caplog)
    finally:
        env.close()


@pytest.mark.parametrize("which", ["incoming", "staging"])
def test_actual_root_junction_is_reparse_rejected(
    tmp_path: Path, which: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    path = env.incoming if which == "incoming" else env.staging
    try:
        env.close_handle(which)
        backing = path.with_name(path.name + "-real")
        path.rename(backing)
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(path), str(backing)], capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"junction construction failed: {result.stdout} {result.stderr}"
        )
        _safe_error(env, builder, "REPARSE_REJECTED", caplog)
    finally:
        env.close()


def test_changed_artifact_hardlink_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        artifact = env.incoming / "launcher.artifact"
        source = tmp_path / "linked-launcher"
        source.write_bytes(artifact.read_bytes())
        artifact.unlink()
        os.link(source, artifact)
        assert artifact.stat().st_nlink > 1
        _safe_error(env, builder, "LINK_OR_ADS_REJECTED", caplog)
    finally:
        env.close()


@pytest.mark.parametrize(
    "target",
    ["changed_identity", "changed_inventory", "old_manifest", "old_inventory", "old_identity"],
)
def test_core_inventory_failures(
    tmp_path: Path, target: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path, core_changed=target.startswith("changed"))
    detail = "CORE_VERIFIER_DETAIL"
    try:
        if target == "changed_identity":
            env.resign(identity="e" * 64)
        elif target == "changed_inventory":
            from neko_launcher.updater.core_manifest_verifier import CoreVerificationResult

            monkeypatch.setattr(
                builder,
                "verify_canonical_core_bundle",
                lambda _p: CoreVerificationResult(False, error=detail),
            )
        elif target in {"old_manifest", "old_inventory"}:
            rel = (
                "canonical-core-manifest.json" if target == "old_manifest" else "NekoProxyCore.exe"
            )
            path = env.old_dir / "ProxyCore" / rel
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        else:
            replacement = tmp_path / "replacement-core"
            replacement.mkdir()
            _bundle(replacement, salt=b"2")
            for old in (env.old_dir / "ProxyCore").rglob("*"):
                if old.is_file():
                    old.unlink()
            for source in replacement.rglob("*"):
                if source.is_file():
                    dest = env.old_dir / "ProxyCore" / source.relative_to(replacement)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(source.read_bytes())
        _safe_error(env, builder, "CORE_INVENTORY_INVALID", caplog, (detail,))
    finally:
        env.close()


def test_corrupt_old_launcher_is_hash_mismatch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path, launcher_changed=False)
    try:
        path = env.old_dir / "NekoLauncher.exe"
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        _safe_error(env, builder, "HASH_MISMATCH", caplog)
    finally:
        env.close()


@pytest.mark.parametrize(
    "case", ["candidate_observed", "highwater", "old_evidence", "extra_evidence", "old_committed"]
)
def test_semantic_durable_state_violation_is_state_corrupt(
    tmp_path: Path, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        if case == "candidate_observed":
            env.state = replace(env.state, observed=env.old.binding)
        elif case == "highwater":
            env.state = replace(env.state, highwater=env.candidate.binding)
        elif case == "old_evidence":
            env.state = replace(env.state, evidence={env.payload_sha: env.envelope_b64})
        elif case == "extra_evidence":
            env.state = replace(
                env.state, evidence={**env.state.evidence, "e" * 64: env.envelope_b64}
            )
        else:
            env.state = replace(
                env.state,
                transaction=replace(
                    env.state.transaction, old=replace(env.old, launcher_identity_sha256="e" * 64)
                ),
            )
        _safe_error(env, builder, "STATE_CORRUPT", caplog)
    finally:
        env.close()


@pytest.mark.parametrize(
    "case",
    ["phase", "transaction", "stage", "mutation_none", "kind", "target", "status", "staging"],
)
def test_wrong_execution_edge_is_protocol_invalid(
    tmp_path: Path, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        tx = env.state.transaction
        if case == "phase":
            env.state = replace(env.state, phase="IDLE")
        elif case == "transaction":
            env.state = replace(env.state, transaction=None)
        elif case == "stage":
            env.state = replace(env.state, transaction=replace(tx, stage="ADMITTED"))
        elif case == "mutation_none":
            env.state = replace(env.state, transaction=replace(tx, mutation=None))
        elif case == "staging":
            env.state = replace(env.state, transaction=replace(tx, staging=None))
        else:
            field, value = {
                "kind": ("kind", "CREATE_STAGE"),
                "target": ("target", "generation"),
                "status": ("status", "DONE"),
            }[case]
            env.state = replace(
                env.state, transaction=replace(tx, mutation=replace(tx.mutation, **{field: value}))
            )
        _safe_error(env, builder, "PROTOCOL_INVALID", caplog)
    finally:
        env.close()


def test_protocol_exclusion(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        env.resign(pmin=2, pmax=3)
        _safe_error(env, builder, "PROTOCOL_UNSUPPORTED", caplog)
    finally:
        env.close()


@pytest.mark.parametrize("case", ["signature", "unknown_key", "malformed", "noncanonical"])
def test_evidence_crypto_taxonomy(
    tmp_path: Path, case: str, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        evidence = dict(env.state.evidence)
        if case == "signature":
            doc = json.loads(env.envelope)
            sig = base64.b64decode(doc["signature_b64"])
            doc["signature_b64"] = base64.b64encode(bytes([sig[0] ^ 1]) + sig[1:]).decode()
            evidence[env.payload_sha] = base64.b64encode(canonical_json_dumps(doc)).decode()
            code = "SIGNATURE_INVALID"
        elif case == "unknown_key":
            env.resign(key_id="unknown")
            evidence = env.state.evidence
            code = "UNKNOWN_KEY"
        elif case == "malformed":
            evidence[env.payload_sha] = base64.b64encode(b"not-json").decode()
            code = "SCHEMA_INVALID"
        else:
            evidence[env.payload_sha] = base64.b64encode(env.envelope + b" ").decode()
            code = "SCHEMA_INVALID"
        env.state = replace(env.state, evidence=evidence)
        _safe_error(env, builder, code, caplog)
    finally:
        env.close()


@pytest.mark.parametrize("case", ["signature", "unknown_key", "malformed", "noncanonical"])
def test_old_evidence_is_independently_authenticated(
    tmp_path: Path,
    case: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        evidence = dict(env.state.evidence)
        if case == "signature":
            document = json.loads(env.old_envelope)
            signature = base64.b64decode(document["signature_b64"])
            document["signature_b64"] = base64.b64encode(
                bytes([signature[0] ^ 1]) + signature[1:]
            ).decode()
            raw = canonical_json_dumps(document)
            code = "SIGNATURE_INVALID"
        elif case == "unknown_key":
            document = json.loads(env.old_envelope)
            document["key_id"] = "unknown"
            raw = canonical_json_dumps(document)
            code = "UNKNOWN_KEY"
        elif case == "malformed":
            raw = b"not-json"
            code = "SCHEMA_INVALID"
        else:
            raw = env.old_envelope + b" "
            code = "SCHEMA_INVALID"
        evidence[env.old.binding.payload_sha256] = base64.b64encode(raw).decode()
        env.state = replace(env.state, evidence=evidence)
        _safe_error(env, builder, code, caplog)
    finally:
        env.close()


@pytest.mark.parametrize(
    "field",
    ["release_sequence", "release_id", "payload_sha256", "launcher", "core"],
)
def test_authenticated_old_descriptor_conflict_is_state_corrupt(
    tmp_path: Path,
    field: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        old = env.old
        if field == "release_sequence":
            old = replace(old, binding=replace(old.binding, release_sequence=3))
        elif field == "release_id":
            old = replace(old, binding=replace(old.binding, release_id="other-old"))
        elif field == "payload_sha256":
            old = replace(old, binding=replace(old.binding, payload_sha256="e" * 64))
        elif field == "launcher":
            old = replace(old, launcher_identity_sha256="e" * 64)
        else:
            old = replace(old, core_identity_sha256="e" * 64)
        env.state = replace(
            env.state,
            committed=old,
            highwater=old.binding,
            transaction=replace(env.state.transaction, old=old),
        )
        _safe_error(env, builder, "STATE_CORRUPT", caplog)
    finally:
        env.close()


@pytest.mark.parametrize(
    "field",
    ["release_sequence", "release_id", "payload_sha256", "launcher", "core"],
)
def test_authenticated_candidate_conflict_is_state_corrupt(
    tmp_path: Path,
    field: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        candidate = env.candidate
        if field == "release_sequence":
            candidate = replace(candidate, binding=replace(candidate.binding, release_sequence=3))
        elif field == "release_id":
            candidate = replace(candidate, binding=replace(candidate.binding, release_id="other"))
        elif field == "payload_sha256":
            candidate = replace(
                candidate, binding=replace(candidate.binding, payload_sha256="e" * 64)
            )
        elif field == "launcher":
            candidate = replace(candidate, launcher_identity_sha256="e" * 64)
        else:
            candidate = replace(candidate, core_identity_sha256="e" * 64)
        env.state = replace(
            env.state,
            observed=candidate.binding,
            transaction=replace(env.state.transaction, candidate=candidate),
        )
        _safe_error(env, builder, "STATE_CORRUPT", caplog)
    finally:
        env.close()


def test_explicit_empty_core_bytes_do_not_fall_back(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        env.resign(artifact=b"")
        assert (env.incoming / "core.artifact.zip").read_bytes() == b""
        _safe_error(env, builder, "SCHEMA_INVALID", caplog)
    finally:
        env.close()


def test_changed_core_verifier_is_bound_to_candidate_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import neko_launcher.updater.generation_builder as builder
    from neko_launcher.updater.core_manifest_verifier import (
        CoreVerificationResult,
        verify_canonical_core_bundle as real_verify,
    )

    env = Env(tmp_path)
    calls: list[Path] = []

    def reject(path: Path) -> CoreVerificationResult:
        calls.append(path)
        candidate_path = env.staging / "generation" / "ProxyCore"
        if path == candidate_path:
            return CoreVerificationResult(False, error="BOUND_PATH_DETAIL")
        return real_verify(path)

    monkeypatch.setattr(builder, "verify_canonical_core_bundle", reject)
    try:
        _safe_error(
            env,
            builder,
            "CORE_INVENTORY_INVALID",
            caplog,
            ("BOUND_PATH_DETAIL",),
        )
        candidate_path = env.staging / "generation" / "ProxyCore"
        assert candidate_path in calls
    finally:
        env.close()


@pytest.mark.parametrize(
    "failure",
    ["zip", "core", "identity", "old", "flush"],
)
def test_failures_do_not_leak_to_logs_or_stdio(
    tmp_path: Path,
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import neko_launcher.updater.generation_builder as builder
    from neko_launcher.updater.core_manifest_verifier import CoreVerificationResult

    env = Env(tmp_path, launcher_changed=failure != "old")
    detail = f"R3_{failure.upper()}_DETAIL"
    forbidden_details = (detail,)
    try:
        if failure == "zip":
            malformed = b"not-a-zip"
            env.resign(artifact=malformed)
            code = "PACKAGE_INVALID"
            forbidden_details += (
                malformed.decode(),
                "BadZipFile",
                _actual_bad_zip_message(malformed),
            )
        elif failure == "core":
            monkeypatch.setattr(
                builder,
                "verify_canonical_core_bundle",
                lambda _path: CoreVerificationResult(False, error=detail),
            )
            code = "CORE_INVENTORY_INVALID"
        elif failure == "identity":
            identity = env.state.transaction.incoming
            env.state = replace(
                env.state,
                transaction=replace(
                    env.state.transaction,
                    incoming=replace(identity, file_id="f" * 32),
                ),
            )
            code = "PATH_REJECTED"
        elif failure == "old":
            path = env.old_dir / "NekoLauncher.exe"
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            code = "HASH_MISMATCH"
        else:
            monkeypatch.setattr(
                builder,
                "_flush_file",
                lambda _path: (_ for _ in ()).throw(OSError(detail)),
            )
            code = "FLUSH_FAILED"
        _safe_error(env, builder, code, caplog, forbidden_details, capsys)
    finally:
        env.close()


def test_preexisting_generation_is_io_failed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    try:
        (env.staging / "generation").mkdir()
        _safe_error(env, builder, "IO_FAILED", caplog)
    finally:
        env.close()


def test_malformed_zip_is_safe_package_invalid(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import neko_launcher.updater.generation_builder as builder

    env = Env(tmp_path)
    detail = b"authenticated-not-a-zip"
    try:
        env.resign(artifact=detail)
        _safe_error(
            env,
            builder,
            "PACKAGE_INVALID",
            caplog,
            ("BadZipFile", detail.decode(), _actual_bad_zip_message(detail)),
        )
    finally:
        env.close()

