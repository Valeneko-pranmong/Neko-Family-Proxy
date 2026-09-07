import base64
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from neko_launcher.application.software_update_models import ComponentRelease
from neko_launcher.infrastructure.software_update_artifact import verify_artifact
from neko_launcher.updater.canonical_json import canonical_json_dumps
from neko_launcher.updater.ipc_channel import FramedIpcChannel
from neko_launcher.updater.manifest_v2 import ComponentV2, verify_release_envelope_v2

_DOWNLOAD_TIMEOUT_S = 15.0
_DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


_open_no_redirect = urllib.request.build_opener(_NoRedirectHandler()).open


def _component_release(component: ComponentV2) -> ComponentRelease:
    return ComponentRelease(
        name=component.name,
        version=component.version,
        artifact_id=component.artifact_id,
        artifact_sha256=component.artifact_sha256,
        artifact_size=component.artifact_size,
        installed_identity_sha256=component.installed_identity_sha256,
    )


def _validate_grant(grant: object) -> str:
    try:
        url = grant.url  # type: ignore[attr-defined]
        expires_at = grant.expires_at  # type: ignore[attr-defined]
    except Exception:
        raise SoftwareUpdateApplyError("GRANT_INVALID") from None

    if type(url) is not str or not isinstance(expires_at, datetime):
        raise SoftwareUpdateApplyError("GRANT_INVALID")
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        parsed.port
        aware = expires_at.tzinfo is not None and expires_at.utcoffset() is not None
        future = aware and expires_at > datetime.now(UTC)
    except (TypeError, ValueError, OverflowError):
        raise SoftwareUpdateApplyError("GRANT_INVALID") from None
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not future
    ):
        raise SoftwareUpdateApplyError("GRANT_INVALID")
    return url


def _download_and_verify(
    grant: object,
    component: ComponentV2,
    destination: Path,
) -> None:
    if not destination.parent.is_dir():
        raise SoftwareUpdateApplyError("DOWNLOAD_FAILED")
    url = _validate_grant(grant)
    request = urllib.request.Request(url, method="GET")
    try:
        with _open_no_redirect(request, timeout=_DOWNLOAD_TIMEOUT_S) as response:
            status = getattr(response, "status", None)
            if status is None and hasattr(response, "getcode"):
                status = response.getcode()
            if status != 200:
                raise SoftwareUpdateApplyError("DOWNLOAD_FAILED")
            with destination.open("xb") as output:
                remaining = component.artifact_size
                while remaining:
                    chunk = response.read(min(_DOWNLOAD_CHUNK_SIZE, remaining + 1))
                    if type(chunk) is not bytes or not chunk:
                        break
                    if len(chunk) > remaining:
                        raise SoftwareUpdateApplyError("DOWNLOAD_SIZE_MISMATCH")
                    output.write(chunk)
                    remaining -= len(chunk)
                if remaining:
                    raise SoftwareUpdateApplyError("DOWNLOAD_SIZE_MISMATCH")
                trailing = response.read(1)
                if type(trailing) is not bytes:
                    raise SoftwareUpdateApplyError("DOWNLOAD_FAILED")
                if trailing:
                    raise SoftwareUpdateApplyError("DOWNLOAD_SIZE_MISMATCH")
        verify_artifact(destination, _component_release(component))
    except SoftwareUpdateApplyError:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise SoftwareUpdateApplyError("DOWNLOAD_FAILED") from None



class SoftwareUpdateApplyError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

class PreparedUpdate:
    def __init__(self, channel: FramedIpcChannel, process: Any) -> None:
        self._channel = channel
        self._process = process

    def release(self) -> None:
        # Close IPC/channel/pipes to signal EOF, MUST NOT terminate helper
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

class DefaultDownloader:
    def download(self, component: str, destination: Path) -> None:
        raise SoftwareUpdateApplyError("DOWNLOAD_FAILED")

class SoftwareUpdateApplyService:
    def __init__(
        self,
        root_dir: Path,
        manifest_gateway: Any = None,
        key_registry: Mapping[str, bytes] | None = None,
        spawner: Any = None,
        channel_factory: Any = None,
        downloader: Any = None,
        grant_gateway: Any = None,
        distribution_capability_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.root_dir = root_dir
        self.manifest_gateway = manifest_gateway
        self.key_registry = dict(key_registry) if key_registry is not None else {}
        self.spawner = spawner
        self.channel_factory = channel_factory
        self.downloader = downloader
        self.grant_gateway = grant_gateway
        self.distribution_capability_provider = distribution_capability_provider

    def prepare(self) -> PreparedUpdate:
        if not self.key_registry:
            raise SoftwareUpdateApplyError("MISSING_KEY_REGISTRY")

        # Fetch manifest
        if not self.manifest_gateway:
            raise SoftwareUpdateApplyError("MISSING_MANIFEST_GATEWAY")

        try:
            document = self.manifest_gateway.fetch()
        except Exception:
            raise SoftwareUpdateApplyError("MANIFEST_FETCH_FAILED")

        # Verify V2 directly
        try:
            release_set_v2, _ = verify_release_envelope_v2(document, self.key_registry)
        except Exception:
            raise SoftwareUpdateApplyError("MANIFEST_VERIFY_FAILED")

        # canonical-json serialize outer envelope and base64 encode exact bytes for BEGIN
        try:
            # We canonicalize the whole document (envelope)
            envelope_bytes = canonical_json_dumps(document)
            envelope_b64 = base64.b64encode(envelope_bytes).decode("ascii")
        except Exception:
            raise SoftwareUpdateApplyError("ENVELOPE_SERIALIZE_FAILED")

        # Spawn helper
        exe_path = str(self.root_dir / "NekoUpdater.exe")
        cmd = [exe_path, "--session"]

        try:
            if self.spawner:
                process = self.spawner(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False)
            else:
                process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False)
        except Exception:
            raise SoftwareUpdateApplyError("SPAWN_FAILED")

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
                body={"envelope_b64": envelope_b64}
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
            if type(accepted) is not bool or (error is not None and type(error) is not str):
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

            # Downloads for changed components
            incoming_dir = self.root_dir / "incoming" / req_id
            for comp_name in ("launcher", "core"):
                if changed[comp_name]:
                    dest = incoming_dir / ("launcher.artifact" if comp_name == "launcher" else "core.artifact.zip")

                    if self.downloader:
                        try:
                            self.downloader.download(comp_name, dest)
                        except Exception:
                            raise SoftwareUpdateApplyError("DOWNLOAD_FAILED")
                    else:
                        if self.grant_gateway is None:
                            raise SoftwareUpdateApplyError("MISSING_GRANT_GATEWAY")
                        component_v2 = release_set_v2.components[comp_name]
                        try:
                            if comp_name == "core":
                                if self.distribution_capability_provider is None:
                                    raise SoftwareUpdateApplyError("GRANT_FAILED")
                                capability = self.distribution_capability_provider()
                                if capability is None:
                                    raise SoftwareUpdateApplyError("GRANT_FAILED")
                                grant = self.grant_gateway.grant_core(
                                    component_v2.artifact_id, capability
                                )
                                del capability
                            else:
                                grant = self.grant_gateway.grant(
                                    component_v2.artifact_id
                                )
                        except SoftwareUpdateApplyError:
                            raise
                        except Exception:
                            raise SoftwareUpdateApplyError("GRANT_FAILED") from None
                        _download_and_verify(grant, component_v2, dest)

            # Send APPLY
            apply_msg_id = channel.send_message(
                "APPLY",
                body={"transaction_id": tx_id, "request_id": req_id}
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
            raise SoftwareUpdateApplyError("PREPARE_FAILED")
