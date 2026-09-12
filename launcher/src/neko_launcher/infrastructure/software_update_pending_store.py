from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path

from neko_launcher.application.software_update_models import LocalReleaseIdentity
from neko_launcher.application.software_update_pending import (
    UpdateLifecycleState,
    VerifiedPendingUpdate,
)
from neko_launcher.updater.canonical_json import canonical_json_dumps, canonical_json_loads
from neko_launcher.updater.manifest_v2 import ReleaseSetV2, verify_release_envelope_v2

ENVELOPE_FILENAME = "release-v2.json"
LAUNCHER_ARTIFACT_FILENAME = "launcher.artifact"
CORE_ARTIFACT_FILENAME = "core.artifact.zip"
METADATA_FILENAME = "metadata.json"
CURRENT_POINTER_FILENAME = "current.json"

_RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HEX64_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class PendingUpdateStore:
    def __init__(
        self,
        root_dir: Path,
        key_registry: Mapping[str, bytes],
        updater_protocol: int,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.base_dir = self.root_dir / "update-pending"
        self.generations_dir = self.base_dir / "generations"
        self.pointer_file = self.base_dir / CURRENT_POINTER_FILENAME
        self.key_registry = key_registry
        self.updater_protocol = updater_protocol

    def _read_active_pointer(self) -> dict[str, object] | None:
        if not self.pointer_file.is_file():
            return None
        try:
            raw = self.pointer_file.read_bytes()
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return None
            if data.get("schema_version") != 1:
                return None
            rel_id = data.get("release_id")
            if not isinstance(rel_id, str) or not _RELEASE_ID_PATTERN.fullmatch(rel_id):
                return None
            seq = data.get("release_sequence")
            if type(seq) is not int or seq < 1:
                return None
            gen_name = data.get("generation_name")
            if not isinstance(gen_name, str) or Path(gen_name).name != gen_name:
                return None
            if "/" in gen_name or "\\" in gen_name or ".." in gen_name:
                return None
            expected_gen = f"gen_{seq}_{rel_id}"
            if gen_name != expected_gen:
                return None
            return data
        except Exception:
            return None

    def promote(
        self,
        *,
        envelope_bytes: bytes,
        release: ReleaseSetV2,
        changed_components: tuple[str, ...],
        staged_files: Mapping[str, Path],
    ) -> VerifiedPendingUpdate:
        if release.channel != "stable":
            raise ValueError(f"Channel must be 'stable', got {release.channel!r}")

        if not (
            release.updater_protocol.minimum
            <= self.updater_protocol
            <= release.updater_protocol.maximum
        ):
            raise ValueError(
                f"Updater protocol incompatible: store protocol {self.updater_protocol} "
                f"not in [{release.updater_protocol.minimum}, {release.updater_protocol.maximum}]"
            )

        for comp in changed_components:
            if comp not in ("launcher", "core"):
                raise ValueError(f"Unsupported component for pending update: {comp!r}")
            if comp not in staged_files:
                raise ValueError(f"Missing staged file for component: {comp!r}")
            src = Path(staged_files[comp])
            if not src.is_file():
                raise ValueError(f"Staged file for {comp!r} does not exist: {src}")

        # Check against existing pending update
        active_pointer = self._read_active_pointer()
        if active_pointer is not None:
            curr_seq = active_pointer["release_sequence"]
            curr_id = active_pointer["release_id"]
            if release.release_sequence < curr_seq:
                raise ValueError(
                    f"Downgrade rejected: incoming sequence {release.release_sequence} "
                    f"< current pending sequence {curr_seq}"
                )
            if release.release_sequence == curr_seq:
                if release.release_id != curr_id:
                    raise ValueError(
                        f"Same-sequence identity conflict: sequence {release.release_sequence} "
                        f"has identity {release.release_id!r}, conflicting with {curr_id!r}"
                    )

        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.generations_dir.mkdir(parents=True, exist_ok=True)

        tmp_dir = self.base_dir / f"tmp_{uuid.uuid4().hex}"
        tmp_dir.mkdir(parents=True, exist_ok=False)

        try:
            # 1. Write envelope bytes
            envelope_path = tmp_dir / ENVELOPE_FILENAME
            with open(envelope_path, "wb") as f:
                f.write(envelope_bytes)
                f.flush()
                os.fsync(f.fileno())

            # 2. Re-verify envelope with production verifier
            envelope_obj = json.loads(envelope_bytes.decode("utf-8"))
            verified_release, _ = verify_release_envelope_v2(
                envelope_obj, self.key_registry
            )
            if verified_release.channel != "stable":
                raise ValueError(f"Channel must be 'stable', got {verified_release.channel!r}")
            if verified_release.release_id != release.release_id:
                raise ValueError("Release ID mismatch between argument and verified envelope")
            if verified_release.release_sequence != release.release_sequence:
                raise ValueError("Release sequence mismatch between argument and verified envelope")
            if not (
                verified_release.updater_protocol.minimum
                <= self.updater_protocol
                <= verified_release.updater_protocol.maximum
            ):
                raise ValueError("Updater protocol incompatible in verified envelope")

            # 3. Stage and verify changed artifacts
            for comp_name in changed_components:
                src_path = Path(staged_files[comp_name])
                target_filename = (
                    LAUNCHER_ARTIFACT_FILENAME
                    if comp_name == "launcher"
                    else CORE_ARTIFACT_FILENAME
                )
                dst_path = tmp_dir / target_filename

                hasher = hashlib.sha256()
                bytes_count = 0
                with open(src_path, "rb") as f_src, open(dst_path, "wb") as f_dst:
                    while chunk := f_src.read(65536):
                        hasher.update(chunk)
                        bytes_count += len(chunk)
                        f_dst.write(chunk)
                    f_dst.flush()
                    os.fsync(f_dst.fileno())

                expected_comp = release.components.get(comp_name)
                if expected_comp is None:
                    raise ValueError(f"Component {comp_name!r} not found in release set")
                if bytes_count != expected_comp.artifact_size:
                    raise ValueError(
                        f"Artifact size mismatch for {comp_name!r}: got {bytes_count}, "
                        f"expected {expected_comp.artifact_size}"
                    )
                digest = hasher.hexdigest()
                if digest != expected_comp.artifact_sha256:
                    raise ValueError(
                        f"Artifact sha256 mismatch for {comp_name!r}: got {digest}, "
                        f"expected {expected_comp.artifact_sha256}"
                    )

            # 4. Write canonical metadata JSON
            metadata = {
                "schema_version": 1,
                "release_id": release.release_id,
                "release_sequence": release.release_sequence,
                "changed_components": list(changed_components),
                "envelope_sha256": hashlib.sha256(envelope_bytes).hexdigest(),
            }
            meta_path = tmp_dir / METADATA_FILENAME
            with open(meta_path, "wb") as f:
                f.write(canonical_json_dumps(metadata))
                f.flush()
                os.fsync(f.fileno())

            # 5. Move temporary generation to destination generation directory
            gen_name = f"gen_{release.release_sequence}_{release.release_id}"
            dest_gen_dir = self.generations_dir / gen_name
            if dest_gen_dir.exists():
                shutil.rmtree(dest_gen_dir, ignore_errors=True)
            os.replace(tmp_dir, dest_gen_dir)

            # 6. Atomically switch active pointer file
            pointer_data = {
                "schema_version": 1,
                "release_id": release.release_id,
                "release_sequence": release.release_sequence,
                "generation_name": gen_name,
            }
            tmp_pointer = self.base_dir / f"current.json.tmp.{uuid.uuid4().hex}"
            with open(tmp_pointer, "wb") as f:
                f.write(canonical_json_dumps(pointer_data))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_pointer, self.pointer_file)

            # 7. Clean up superseded generations
            for entry in self.generations_dir.iterdir():
                if entry.is_dir() and entry.name != gen_name:
                    shutil.rmtree(entry, ignore_errors=True)

            launcher_artifact = (
                dest_gen_dir / LAUNCHER_ARTIFACT_FILENAME
                if "launcher" in changed_components
                else None
            )
            core_artifact = (
                dest_gen_dir / CORE_ARTIFACT_FILENAME
                if "core" in changed_components
                else None
            )

            return VerifiedPendingUpdate(
                release_id=release.release_id,
                release_sequence=release.release_sequence,
                changed_components=tuple(changed_components),
                envelope_bytes=envelope_bytes,
                generation_dir=dest_gen_dir,
                launcher_artifact=launcher_artifact,
                core_artifact=core_artifact,
            )
        except Exception:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def load_verified(
        self,
        local_identity: LocalReleaseIdentity,
    ) -> VerifiedPendingUpdate | None:
        pointer = self._read_active_pointer()
        if pointer is None:
            return None

        rel_id = pointer["release_id"]
        rel_seq = pointer["release_sequence"]
        gen_name = pointer["generation_name"]

        # Derive path strictly under generations_dir
        gen_dir = self.generations_dir / gen_name
        if not gen_dir.is_dir():
            return None

        # Verify gen_dir is strictly inside generations_dir
        try:
            if gen_dir.resolve().parent != self.generations_dir.resolve():
                return None
        except Exception:
            return None

        # Check metadata
        meta_path = gen_dir / METADATA_FILENAME
        if not meta_path.is_file():
            return None
        try:
            meta_obj = canonical_json_loads(meta_path.read_bytes())
            if not isinstance(meta_obj, dict):
                return None
            if meta_obj.get("schema_version") != 1:
                return None
            if meta_obj.get("release_id") != rel_id:
                return None
            if meta_obj.get("release_sequence") != rel_seq:
                return None
            changed_components_raw = meta_obj.get("changed_components")
            if not isinstance(changed_components_raw, list):
                return None
            for c in changed_components_raw:
                if c not in ("launcher", "core"):
                    return None
            changed_components = tuple(changed_components_raw)
            expected_env_sha = meta_obj.get("envelope_sha256")
            if not isinstance(expected_env_sha, str) or not _HEX64_PATTERN.fullmatch(expected_env_sha):
                return None
        except Exception:
            return None

        # Check envelope bytes and signature
        env_path = gen_dir / ENVELOPE_FILENAME
        if not env_path.is_file():
            return None
        try:
            envelope_bytes = env_path.read_bytes()
            if hashlib.sha256(envelope_bytes).hexdigest() != expected_env_sha:
                return None
            envelope_obj = json.loads(envelope_bytes.decode("utf-8"))
            release, _ = verify_release_envelope_v2(envelope_obj, self.key_registry)
        except Exception:
            return None

        if release.channel != "stable":
            return None
        if release.release_id != rel_id:
            return None
        if release.release_sequence != rel_seq:
            return None
        if not (
            release.updater_protocol.minimum
            <= self.updater_protocol
            <= release.updater_protocol.maximum
        ):
            return None

        # Anti-downgrade and same-sequence against local installation
        if release.release_sequence < local_identity.release_sequence:
            return None
        if release.release_sequence == local_identity.release_sequence:
            return None

        # Verify staged artifact bytes and sizes strictly against release definition
        launcher_artifact: Path | None = None
        core_artifact: Path | None = None

        if "launcher" in changed_components:
            l_path = gen_dir / LAUNCHER_ARTIFACT_FILENAME
            if not l_path.is_file():
                return None
            expected_comp = release.components.get("launcher")
            if expected_comp is None:
                return None
            try:
                if l_path.stat().st_size != expected_comp.artifact_size:
                    return None
                if hashlib.sha256(l_path.read_bytes()).hexdigest() != expected_comp.artifact_sha256:
                    return None
            except Exception:
                return None
            launcher_artifact = l_path

        if "core" in changed_components:
            c_path = gen_dir / CORE_ARTIFACT_FILENAME
            if not c_path.is_file():
                return None
            expected_comp = release.components.get("core")
            if expected_comp is None:
                return None
            try:
                if c_path.stat().st_size != expected_comp.artifact_size:
                    return None
                if hashlib.sha256(c_path.read_bytes()).hexdigest() != expected_comp.artifact_sha256:
                    return None
            except Exception:
                return None
            core_artifact = c_path

        return VerifiedPendingUpdate(
            release_id=release.release_id,
            release_sequence=release.release_sequence,
            changed_components=changed_components,
            envelope_bytes=envelope_bytes,
            generation_dir=gen_dir,
            launcher_artifact=launcher_artifact,
            core_artifact=core_artifact,
        )

    def state(self, local_identity: LocalReleaseIdentity) -> UpdateLifecycleState:
        if self.load_verified(local_identity) is not None:
            return UpdateLifecycleState.UPDATE_PENDING
        return UpdateLifecycleState.IDLE

    def clear(self, expected_release_id: str, expected_release_sequence: int) -> None:
        pointer = self._read_active_pointer()
        if pointer is None:
            return
        if (
            pointer.get("release_id") == expected_release_id
            and pointer.get("release_sequence") == expected_release_sequence
        ):
            gen_name = pointer.get("generation_name")
            try:
                self.pointer_file.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(gen_name, str):
                gen_dir = self.generations_dir / gen_name
                shutil.rmtree(gen_dir, ignore_errors=True)

    def cleanup_incomplete(self) -> None:
        if not self.base_dir.exists():
            return

        active_gen_name: str | None = None
        pointer = self._read_active_pointer()
        if pointer is not None:
            active_gen_name = str(pointer.get("generation_name"))

        for entry in self.base_dir.iterdir():
            if entry.name.startswith("tmp_") or entry.name.endswith(".tmp"):
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    try:
                        entry.unlink(missing_ok=True)
                    except OSError:
                        pass

        if self.generations_dir.exists():
            for gen_entry in self.generations_dir.iterdir():
                if gen_entry.is_dir():
                    if active_gen_name is None or gen_entry.name != active_gen_name:
                        shutil.rmtree(gen_entry, ignore_errors=True)
