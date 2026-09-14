from __future__ import annotations

import base64
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neko_launcher.application.software_update_models import (
    AuthenticatedReleaseBinding,
)
from neko_launcher.updater.ipc_channel import FramedIpcChannel

VALID_ADMISSION_ERRORS = {
    "SIGNATURE_INVALID",
    "SCHEMA_INVALID",
    "PROTOCOL_UNSUPPORTED",
    "LOCK_BUSY",
    "DOWNGRADE_REJECTED",
    "SAME_SEQUENCE_CONFLICT",
    "CANDIDATE_SUPPRESSED",
    "STATE_CORRUPT",
    "IO_FAILED",
}


@dataclass(frozen=True)
class AuthorityAdmissionResult:
    accepted: bool
    binding: AuthenticatedReleaseBinding | None
    changed: bool
    error: str | None


class SoftwareUpdateAuthorityAdmissionService:
    def __init__(
        self,
        root_dir: Path,
        *,
        spawner: Callable[..., Any] | None = None,
        channel_factory: Callable[[], FramedIpcChannel] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.spawner = spawner
        self.channel_factory = channel_factory

    def _spawn_helper(self) -> tuple[Any, FramedIpcChannel]:
        exe_path = str(self.root_dir / "NekoUpdater.exe")
        cmd = [exe_path, "--session"]

        if self.spawner:
            process = self.spawner(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        else:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
            )

        if self.channel_factory:
            channel = self.channel_factory()
        else:
            stdout = getattr(process, "stdout", None)
            stdin = getattr(process, "stdin", None)
            if stdout is None or stdin is None:
                raise RuntimeError("INVALID_PROCESS_STREAMS")
            read_handle = stdout.fileno()
            write_handle = stdin.fileno()
            if type(read_handle) is not int or type(write_handle) is not int:
                raise RuntimeError("INVALID_PROCESS_STREAMS")
            channel = FramedIpcChannel(
                read_handle=read_handle,
                write_handle=write_handle,
            )

        return process, channel

    def admit(self, envelope_bytes: bytes) -> AuthorityAdmissionResult:
        if not isinstance(envelope_bytes, (bytes, bytearray)):
            return AuthorityAdmissionResult(
                accepted=False,
                binding=None,
                changed=False,
                error="SCHEMA_INVALID",
            )

        envelope_b64 = base64.b64encode(envelope_bytes).decode("ascii")

        process = None
        channel = None
        try:
            process, channel = self._spawn_helper()
            msg_id = channel.send_message(
                "ADMIT_AUTHORITY",
                body={"envelope_b64": envelope_b64},
            )

            resp = channel.receive_message(timeout_s=5.0)
            if resp.type != "AUTHORITY_ADMITTED":
                return AuthorityAdmissionResult(
                    accepted=False,
                    binding=None,
                    changed=False,
                    error="PROTOCOL_INVALID",
                )
            if resp.message_id != msg_id:
                return AuthorityAdmissionResult(
                    accepted=False,
                    binding=None,
                    changed=False,
                    error="MESSAGE_ID_MISMATCH",
                )

            body = resp.body
            if not isinstance(body, dict) or set(body.keys()) != {
                "accepted",
                "release_sequence",
                "release_id",
                "payload_sha256",
                "changed",
                "error",
            }:
                return AuthorityAdmissionResult(
                    accepted=False,
                    binding=None,
                    changed=False,
                    error="SCHEMA_INVALID",
                )

            accepted = body["accepted"]
            rel_seq = body["release_sequence"]
            rel_id = body["release_id"]
            payload_sha = body["payload_sha256"]
            changed = body["changed"]
            err = body["error"]

            if not isinstance(accepted, bool) or not isinstance(changed, bool):
                return AuthorityAdmissionResult(
                    accepted=False,
                    binding=None,
                    changed=False,
                    error="SCHEMA_INVALID",
                )

            if accepted:
                if (
                    not isinstance(rel_seq, int)
                    or rel_seq < 1
                    or not isinstance(rel_id, str)
                    or not rel_id
                    or not isinstance(payload_sha, str)
                    or len(payload_sha) != 64
                    or err is not None
                ):
                    return AuthorityAdmissionResult(
                        accepted=False,
                        binding=None,
                        changed=False,
                        error="SCHEMA_INVALID",
                    )
                binding = AuthenticatedReleaseBinding(
                    release_sequence=rel_seq,
                    release_id=rel_id,
                    payload_sha256=payload_sha,
                )
            else:
                if (
                    rel_seq is not None
                    or rel_id is not None
                    or payload_sha is not None
                    or changed is not False
                    or err not in VALID_ADMISSION_ERRORS
                ):
                    return AuthorityAdmissionResult(
                        accepted=False,
                        binding=None,
                        changed=False,
                        error="SCHEMA_INVALID",
                    )
                binding = None

            # Close both channel/streams before waiting for process exit
            try:
                channel.close()
            except Exception:
                pass
            if hasattr(process, "stdin") and process.stdin:
                try:
                    process.stdin.close()
                except Exception:
                    pass
            if hasattr(process, "stdout") and process.stdout:
                try:
                    process.stdout.close()
                except Exception:
                    pass

            exit_code = process.wait(timeout=5.0)
            if exit_code != 0:
                return AuthorityAdmissionResult(
                    accepted=False,
                    binding=None,
                    changed=False,
                    error=err or "HELPER_EXIT_NONZERO",
                )

            return AuthorityAdmissionResult(
                accepted=accepted,
                binding=binding,
                changed=changed,
                error=err,
            )

        except subprocess.TimeoutExpired:
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    process.kill()
                except Exception:
                    pass
            return AuthorityAdmissionResult(
                accepted=False,
                binding=None,
                changed=False,
                error="PROCESS_TIMEOUT",
            )
        except Exception as exc:
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    process.kill()
                except Exception:
                    pass
            return AuthorityAdmissionResult(
                accepted=False,
                binding=None,
                changed=False,
                error=str(exc) or "ADMISSION_FAILED",
            )
        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
