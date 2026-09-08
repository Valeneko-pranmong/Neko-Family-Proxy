from __future__ import annotations

import base64
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from neko_launcher.updater.ipc_channel import FramedIpcChannel

if TYPE_CHECKING:
    from neko_launcher.infrastructure.github_asset_downloader import (
        GitHubAssetDownloader,
    )
    from neko_launcher.infrastructure.github_release_binding import (
        AuthenticatedReleaseGateway,
    )


class SoftwareUpdateApplyError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PreparedUpdate:
    def __init__(self, channel: FramedIpcChannel | None, process: Any) -> None:
        self._channel = channel
        self._process = process

    def release(self) -> None:
        # Close IPC/channel/pipes to signal EOF, MUST NOT terminate helper
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass
        if hasattr(self._process, "stdin") and self._process.stdin:
            try:
                self._process.stdin.close()
            except Exception:
                pass
        if hasattr(self._process, "stdout") and self._process.stdout:
            try:
                self._process.stdout.close()
            except Exception:
                pass

    def abort(self) -> None:
        self.release()
        try:
            self._process.terminate()
        except Exception:
            pass
        try:
            self._process.kill()
        except Exception:
            pass


class SoftwareUpdateApplyService:
    def __init__(
        self,
        root_dir: Path,
        release_gateway: AuthenticatedReleaseGateway,
        asset_downloader: GitHubAssetDownloader,
        spawner: Callable[..., subprocess.Popen[bytes]] | None = None,
        channel_factory: Callable[..., FramedIpcChannel] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.release_gateway = release_gateway
        self.asset_downloader = asset_downloader
        self.spawner = spawner
        self.channel_factory = channel_factory

    def prepare(self) -> PreparedUpdate:
        # Mandatory resolver refetch on apply; fails closed before helper starts
        try:
            resolved = self.release_gateway.resolve()
        except SoftwareUpdateApplyError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            if type(code) is str:
                raise SoftwareUpdateApplyError(code) from None
            raise SoftwareUpdateApplyError("MANIFEST_VERIFY_FAILED") from None

        if resolved is None:
            raise SoftwareUpdateApplyError("RELEASE_UNAVAILABLE")

        # Forward exact downloaded canonical envelope bytes unchanged to BEGIN
        try:
            envelope_b64 = base64.b64encode(resolved.envelope_bytes).decode("ascii")
        except Exception:
            raise SoftwareUpdateApplyError("ENVELOPE_SERIALIZE_FAILED") from None

        # Spawn helper
        exe_path = str(self.root_dir / "NekoUpdater.exe")
        cmd = [exe_path, "--session"]

        try:
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
        except Exception:
            raise SoftwareUpdateApplyError("SPAWN_FAILED") from None

        prepared = PreparedUpdate(None, process)

        try:
            # IPC Channel
            if self.channel_factory:
                channel = self.channel_factory()
            else:
                stdout = process.stdout
                stdin = process.stdin
                if stdout is None or stdin is None:
                    raise SoftwareUpdateApplyError("INVALID_PROCESS_STREAMS")
                read_handle = stdout.fileno()
                write_handle = stdin.fileno()
                if type(read_handle) is not int or type(write_handle) is not int:
                    raise SoftwareUpdateApplyError("INVALID_PROCESS_STREAMS")
                channel = FramedIpcChannel(
                    read_handle=read_handle,
                    write_handle=write_handle,
                )
            prepared._channel = channel

            # Send BEGIN
            msg_id = channel.send_message(
                "BEGIN",
                body={"envelope_b64": envelope_b64},
            )

            # Wait for REQUEST_READY
            resp = channel.receive_message(timeout_s=5.0)
            if resp.type != "REQUEST_READY":
                raise SoftwareUpdateApplyError("UNEXPECTED_RESPONSE")
            if resp.message_id != msg_id:
                raise SoftwareUpdateApplyError("MESSAGE_ID_MISMATCH")

            body = resp.body
            if type(body) is not dict or set(body) != {
                "accepted",
                "request_id",
                "transaction_id",
                "changed",
                "error",
            }:
                raise SoftwareUpdateApplyError("INVALID_REQUEST_READY")
            accepted = body["accepted"]
            req_id = body["request_id"]
            tx_id = body["transaction_id"]
            changed = body["changed"]
            error = body["error"]
            if type(accepted) is not bool or (
                error is not None and type(error) is not str
            ):
                raise SoftwareUpdateApplyError("INVALID_REQUEST_READY")
            if accepted:
                if type(req_id) is not str or not req_id:
                    raise SoftwareUpdateApplyError("INVALID_REQUEST_ID")
                if type(tx_id) is not str or not tx_id:
                    raise SoftwareUpdateApplyError("INVALID_TRANSACTION_ID")
                if (
                    type(changed) is not dict
                    or set(changed) != {"launcher", "core"}
                    or type(changed["launcher"]) is not bool
                    or type(changed["core"]) is not bool
                ):
                    raise SoftwareUpdateApplyError("INVALID_CHANGED_DICT")
            else:
                if (req_id is not None and type(req_id) is not str) or (
                    tx_id is not None and type(tx_id) is not str
                ):
                    raise SoftwareUpdateApplyError("INVALID_REQUEST_READY")
                if changed is not None and (
                    type(changed) is not dict
                    or set(changed) != {"launcher", "core"}
                    or type(changed["launcher"]) is not bool
                    or type(changed["core"]) is not bool
                ):
                    raise SoftwareUpdateApplyError("INVALID_REQUEST_READY")
                raise SoftwareUpdateApplyError("BEGIN_REJECTED")

            # Downloads for changed components (launcher and core only)
            incoming_dir = self.root_dir / "incoming" / req_id
            for comp_name in ("launcher", "core"):
                if changed[comp_name]:
                    dest = (
                        incoming_dir / "launcher.artifact"
                        if comp_name == "launcher"
                        else incoming_dir / "core.artifact.zip"
                    )
                    asset = (
                        resolved.launcher_asset
                        if comp_name == "launcher"
                        else resolved.core_asset
                    )
                    component_v2 = resolved.authenticated_release_v2.components[
                        comp_name
                    ]
                    try:
                        self.asset_downloader.download(
                            initial_url=asset.browser_download_url,
                            destination=dest,
                            expected_size=component_v2.artifact_size,
                            expected_sha256=component_v2.artifact_sha256,
                        )
                    except Exception:
                        raise SoftwareUpdateApplyError("DOWNLOAD_FAILED") from None

            # Send APPLY
            apply_msg_id = channel.send_message(
                "APPLY",
                body={"transaction_id": tx_id, "request_id": req_id},
            )

            apply_resp = channel.receive_message(timeout_s=5.0)
            if apply_resp.type != "APPLY_RESULT":
                raise SoftwareUpdateApplyError("UNEXPECTED_RESPONSE")
            if apply_resp.message_id != apply_msg_id:
                raise SoftwareUpdateApplyError("MESSAGE_ID_MISMATCH")

            apply_body = apply_resp.body
            if type(apply_body) is not dict or set(apply_body) != {
                "accepted",
                "transaction_id",
                "error",
            }:
                raise SoftwareUpdateApplyError("INVALID_APPLY_RESULT")
            apply_accepted = apply_body["accepted"]
            apply_tx_id = apply_body["transaction_id"]
            apply_error = apply_body["error"]
            if (
                type(apply_accepted) is not bool
                or (apply_tx_id is not None and type(apply_tx_id) is not str)
                or (apply_error is not None and type(apply_error) is not str)
            ):
                raise SoftwareUpdateApplyError("INVALID_APPLY_RESULT")
            if not apply_accepted:
                raise SoftwareUpdateApplyError("APPLY_REJECTED")
            if apply_tx_id != tx_id:
                raise SoftwareUpdateApplyError("INVALID_TRANSACTION_ID")

            return prepared

        except Exception as e:
            prepared.abort()
            if isinstance(e, SoftwareUpdateApplyError):
                raise
            raise SoftwareUpdateApplyError("PREPARE_FAILED") from None
