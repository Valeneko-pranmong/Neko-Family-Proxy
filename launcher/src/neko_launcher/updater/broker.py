import base64
import ctypes
import ctypes.wintypes
import dataclasses
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from neko_launcher.updater.canonical_json import canonical_json_loads
from neko_launcher.updater.core_manifest_verifier import verify_canonical_core_bundle
from neko_launcher.updater.generation_builder import GenerationBuildError, build_generation
from neko_launcher.updater.generation_publisher import GenerationPublisher
from neko_launcher.updater.manifest_v2 import verify_release_envelope_v2
from neko_launcher.updater.precommit_abort import execute_precommit_abort
from neko_launcher.updater.slot_selector import SelectionStatus
from neko_launcher.updater.staging_handoff import (
    RequestReadyResult,
    handle_apply_request,
    handle_begin_request,
)
from neko_launcher.updater.state_machine import validate_transition
from neko_launcher.updater.state_models import Generation, Mutation, State


@dataclass(frozen=True)
class ApplyResult:
    accepted: bool
    transaction_id: str | None = None
    error: str | None = None

def _CloseHandle(handle: int) -> None:
    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.wintypes.HANDLE(handle))
    except Exception:  # noqa: BLE001, S110
        pass

class BrokerCoordinator:
    def __init__(
        self,
        root_dir: Path,
        slot_store,
        public_keys: Mapping[str, bytes],
        published_verifier: Callable[[Path, Generation, bytes], None] | None = None
    ) -> None:
        self.root_dir = root_dir
        self.slot_store = slot_store
        self.public_keys = public_keys
        self.published_verifier = published_verifier or self._default_verifier

    def _default_verifier(self, published_path: Path, candidate: Generation, envelope_bytes: bytes) -> None:
        doc = canonical_json_loads(envelope_bytes)
        release_set, payload_sha = verify_release_envelope_v2(doc, self.public_keys)
        
        if payload_sha != candidate.binding.payload_sha256:
            raise ValueError("PACKAGE_INVALID")
            
        if release_set.release_sequence != candidate.binding.release_sequence or release_set.release_id != candidate.binding.release_id:
            raise ValueError("PACKAGE_INVALID")

        if release_set.components["launcher"].installed_identity_sha256 != candidate.launcher_identity_sha256:
            raise ValueError("PACKAGE_INVALID")
            
        if release_set.components["core"].installed_identity_sha256 != candidate.core_identity_sha256:
            raise ValueError("PACKAGE_INVALID")
            
        launcher_path = published_path / "NekoLauncher.exe"
        if not launcher_path.is_file():
            raise ValueError("PACKAGE_INVALID")
        l_bytes = launcher_path.read_bytes()
        if hashlib.sha256(l_bytes).hexdigest() != candidate.launcher_identity_sha256:
            raise ValueError("PACKAGE_INVALID")
            
        core_res = verify_canonical_core_bundle(published_path / "ProxyCore")
        if not core_res.valid:
            raise ValueError("CORE_INVENTORY_INVALID")
            
        core_manifest = published_path / "ProxyCore" / "core-manifest.json"
        if not core_manifest.is_file():
            core_manifest = published_path / "ProxyCore" / "canonical-core-manifest.json"
        if not core_manifest.is_file():
            raise ValueError("CORE_INVENTORY_INVALID")
        if hashlib.sha256(core_manifest.read_bytes()).hexdigest() != candidate.core_identity_sha256:
            raise ValueError("CORE_INVENTORY_INVALID")

    def _abort(self, current_state: State, error: str) -> ApplyResult:
        try:
            aborted = execute_precommit_abort(current_state, error)
            write_res = self.slot_store.write_state(aborted)
            if write_res.status != SelectionStatus.SELECTED or write_res.state != aborted:
                return ApplyResult(False, None, "STATE_CORRUPT")
        except Exception:  # noqa: BLE001
            return ApplyResult(False, None, "STATE_CORRUPT")
        return ApplyResult(False, None, error)

    def begin(self, envelope_b64: str) -> RequestReadyResult:
        selection = self.slot_store.load()
        if selection.status != SelectionStatus.SELECTED or selection.state is None:
            return RequestReadyResult(accepted=False, error="STATE_CORRUPT")
            
        if selection.state.phase != "IDLE":
            return RequestReadyResult(accepted=False, error="LOCK_BUSY")
            
        result, next_state = handle_begin_request(self.root_dir, selection.state, envelope_b64, self.public_keys)
        if not result.accepted or next_state is None:
            return result
            
        write_res = self.slot_store.write_state(next_state)
        if write_res.status != SelectionStatus.SELECTED or write_res.state != next_state:
            return RequestReadyResult(accepted=False, error="STATE_CORRUPT")
            
        return result

    def apply(self, transaction_id: str, request_id: str) -> ApplyResult:
        selection = self.slot_store.load()
        if (selection.status != SelectionStatus.SELECTED or 
            selection.state is None or 
            selection.state.phase != "PREPARING" or 
            selection.state.transaction is None or 
            selection.state.transaction.id != transaction_id or 
            selection.state.transaction.request_id != request_id):
            return ApplyResult(False, None, "PROTOCOL_INVALID")
            
        current_state = selection.state
        tx = current_state.transaction
        
        expected_files = set()
        if tx.old is None or tx.old.launcher_identity_sha256 != tx.candidate.launcher_identity_sha256:
            expected_files.add("launcher.artifact")
        if tx.old is None or tx.old.core_identity_sha256 != tx.candidate.core_identity_sha256:
            expected_files.add("core.artifact.zip")
            
        incoming_dir = self.root_dir / "incoming" / request_id
        if not incoming_dir.exists():
            return self._abort(current_state, "ARTIFACT_MISSING")
            
        try:
            actual_entries = list(incoming_dir.iterdir())
        except OSError:
            return self._abort(current_state, "ARTIFACT_MISSING")
            
        actual_names = {e.name for e in actual_entries}
        
        if actual_names - expected_files:
            return self._abort(current_state, "PACKAGE_INVALID")
            
        for expected in expected_files:
            if expected not in actual_names:
                return self._abort(current_state, "ARTIFACT_MISSING")
            path = incoming_dir / expected
            if not path.is_file():
                return self._abort(current_state, "PACKAGE_INVALID")
                
        staging_handoff_res = handle_apply_request(self.root_dir, current_state, transaction_id, request_id, self.public_keys)
        if not staging_handoff_res.accepted:
            return self._abort(current_state, staging_handoff_res.error or "PROTOCOL_INVALID")
            
        publisher = GenerationPublisher(self.root_dir)
        try:
            handle, identity, _stage_path = publisher.create_staging_area(tx.id)
            _CloseHandle(handle)
        except OSError:
            return self._abort(current_state, "IO_FAILED")
            
        new_tx = dataclasses.replace(
            tx, staging=identity, stage="BUILDING", mutation=Mutation("WRITE_CANDIDATE", "stage", "INTENT")
        )
        building_state = dataclasses.replace(current_state, transaction=new_tx, revision=current_state.revision + 1)
        try:
            validate_transition(current_state, building_state)
            write_res = self.slot_store.write_state(building_state)
            if write_res.status != SelectionStatus.SELECTED or write_res.state != building_state:
                raise ValueError("STATE_CORRUPT")
        except Exception:  # noqa: BLE001
            return self._abort(current_state, "STATE_CORRUPT")
            
        try:
            build_result = build_generation(self.root_dir, building_state, self.public_keys)
            if build_result.generation != tx.candidate:
                return self._abort(building_state, "PACKAGE_INVALID")
            published_path = publisher.publish_generation(build_result.generation_dir, build_result.generation_id)
            
            envelope_b64 = current_state.evidence[tx.candidate.binding.payload_sha256]
            envelope_bytes = base64.b64decode(envelope_b64, validate=True)
            self.published_verifier(published_path, build_result.generation, envelope_bytes)
            
        except GenerationBuildError as e:
            return self._abort(building_state, str(e.code))
        except OSError:
            return self._abort(building_state, "IO_FAILED")
        except ValueError as e:
            err = str(e)
            if err == "CORE_INVENTORY_INVALID":
                return self._abort(building_state, "CORE_INVENTORY_INVALID")
            else:
                return self._abort(building_state, "PACKAGE_INVALID")
        except Exception:  # noqa: BLE001
            return self._abort(building_state, "PACKAGE_INVALID")
            
        verified_tx = dataclasses.replace(new_tx, stage="VERIFIED", mutation=None)
        verified_state = dataclasses.replace(building_state, transaction=verified_tx, revision=building_state.revision + 1)
        try:
            validate_transition(building_state, verified_state)
            write_res = self.slot_store.write_state(verified_state)
            if write_res.status != SelectionStatus.SELECTED or write_res.state != verified_state:
                raise ValueError("STATE_CORRUPT")
        except Exception:  # noqa: BLE001
            return self._abort(building_state, "STATE_CORRUPT")
            
        return ApplyResult(True, verified_tx.id, None)