from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

from neko_launcher.domain.events import TelemetryUpdated
from neko_launcher.domain.telemetry import (
    CoreHealthSnapshot,
    TelemetryConnectionState,
    TelemetryRateCalculator,
    TelemetryState,
)
from neko_launcher.application.ports import EventPublisher

logger = logging.getLogger(__name__)

DEFAULT_TELEMETRY_PIPE_NAME = "NekoProxyCoreTelemetry"
DEFAULT_TELEMETRY_PIPE_PATH = rf"\\.\pipe\{DEFAULT_TELEMETRY_PIPE_NAME}"
MAX_FRAME_BYTES = 65536
STALE_THRESHOLD_SECONDS = 4.0
SUPPORTED_SCHEMA_VERSION = 1


class NamedPipeCoreTelemetryClient:
    """Local, read-only consumer for \\\\.\\pipe\\NekoProxyCoreTelemetry.

    This consumer runs in a background thread and publishes TelemetryUpdated
    events to the EventBus without blocking the UI or proxy data planes.
    """

    def __init__(
        self,
        event_publisher: EventPublisher,
        pipe_path: str = DEFAULT_TELEMETRY_PIPE_PATH,
        stale_threshold: float = STALE_THRESHOLD_SECONDS,
    ) -> None:
        self._event_publisher = event_publisher
        self._pipe_path = pipe_path
        self._stale_threshold = stale_threshold

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._rate_calculator = TelemetryRateCalculator()
        self._state = TelemetryState()

    @property
    def state(self) -> TelemetryState:
        with self._lock:
            return self._state

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="neko-telemetry-consumer",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        thread = None
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def _update_state(self, **changes: Any) -> None:
        with self._lock:
            from dataclasses import replace

            self._state = replace(self._state, **changes)
            state = self._state
        self._event_publisher.publish(TelemetryUpdated(state))

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._connect_and_stream()
            except Exception as exc:
                logger.debug("Telemetry stream exception: %s", exc)
                self._rate_calculator.reset()
                self._update_state(
                    connection_state=TelemetryConnectionState.DISCONNECTED,
                    rx_rate_bps=0.0,
                    tx_rate_bps=0.0,
                    is_stale=False,
                )
                self._stop_event.wait(0.5)

    def _connect_and_stream(self) -> None:
        # Check if pipe exists or can be opened
        try:
            handle = open(self._pipe_path, "rb", buffering=0)  # noqa: SIM115
        except OSError:
            # Core not running or pipe not ready yet
            if self.state.connection_state != TelemetryConnectionState.DISCONNECTED:
                self._rate_calculator.reset()
                self._update_state(
                    connection_state=TelemetryConnectionState.DISCONNECTED,
                    rx_rate_bps=0.0,
                    tx_rate_bps=0.0,
                    is_stale=False,
                )
            self._stop_event.wait(0.5)
            return

        with handle:
            self._rate_calculator.reset()
            self._update_state(
                connection_state=TelemetryConnectionState.CONNECTED,
                is_stale=False,
            )

            buffer = bytearray()
            last_received_time = time.monotonic()

            # Set non-blocking mode if on Windows
            self._configure_pipe_handle(handle)

            while not self._stop_event.is_set():
                now = time.monotonic()
                if (
                    now - last_received_time > self._stale_threshold
                    and not self.state.is_stale
                ):
                    self._update_state(
                        is_stale=True,
                        rx_rate_bps=0.0,
                        tx_rate_bps=0.0,
                    )

                try:
                    chunk = handle.read(4096)
                except BlockingIOError:
                    self._stop_event.wait(0.05)
                    continue
                except OSError:
                    # Pipe disconnected or broken
                    break

                if not chunk:
                    # On Windows PIPE_NOWAIT, empty read means no data ready yet
                    if os.name == "nt":
                        self._stop_event.wait(0.05)
                        continue
                    else:
                        break

                last_received_time = time.monotonic()
                buffer.extend(chunk)

                if len(buffer) > MAX_FRAME_BYTES * 2:
                    # Overflow protection: clear corrupted buffer
                    buffer.clear()
                    self._update_state(
                        parse_error_count=self.state.parse_error_count + 1
                    )
                    continue

                while b"\n" in buffer:
                    line, _, remaining = buffer.partition(b"\n")
                    buffer = bytearray(remaining)
                    line_str = line.strip().decode("utf-8", errors="replace")
                    if not line_str:
                        continue
                    self._handle_frame(line_str, last_received_time)

        self._rate_calculator.reset()
        self._update_state(
            connection_state=TelemetryConnectionState.DISCONNECTED,
            rx_rate_bps=0.0,
            tx_rate_bps=0.0,
            is_stale=False,
        )

    def _handle_frame(self, line: str, timestamp: float) -> None:
        try:
            doc = json.loads(line)
        except Exception:
            self._update_state(parse_error_count=self.state.parse_error_count + 1)
            return

        if not isinstance(doc, dict):
            self._update_state(parse_error_count=self.state.parse_error_count + 1)
            return

        schema_version = doc.get("schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            self._update_state(schema_incompatible=True)
            return

        message_type = doc.get("message_type")
        sequence = doc.get("sequence")
        if isinstance(sequence, int):
            seq_val = sequence
        else:
            seq_val = None

        if message_type == "core.health.snapshot":
            payload = doc.get("payload")
            if isinstance(payload, dict):
                snapshot = CoreHealthSnapshot.from_dict(payload)
                rx_rate, tx_rate = self._rate_calculator.calculate_rates(
                    rx_bytes=snapshot.rx_bytes,
                    tx_bytes=snapshot.tx_bytes,
                    timestamp=timestamp,
                    sequence=seq_val,
                )
                self._update_state(
                    snapshot=snapshot,
                    rx_rate_bps=rx_rate,
                    tx_rate_bps=tx_rate,
                    last_sequence=seq_val,
                    last_snapshot_timestamp=timestamp,
                    is_stale=False,
                    schema_incompatible=False,
                )

    @staticmethod
    def _configure_pipe_handle(handle: Any) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            import msvcrt

            pipe_nowait = ctypes.c_uint32(0x00000001)
            native_handle = msvcrt.get_osfhandle(handle.fileno())
            ctypes.windll.kernel32.SetNamedPipeHandleState(
                ctypes.c_void_p(native_handle),
                ctypes.byref(pipe_nowait),
                None,
                None,
            )
        except Exception as exc:
            logger.debug("Failed to set non-blocking pipe state: %s", exc)
