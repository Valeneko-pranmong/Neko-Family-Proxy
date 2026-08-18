# NEKO FAMILY PROXY — LAUNCHER TELEMETRY CONSUMER HANDOFF
# T3 Launcher Local Telemetry Consumer & UI Integration

```text
DOCUMENT:               docs/current/launcher-telemetry-consumer-handoff.md
STATUS:                 T3_VALIDATED_AND_CLOSED
CURRENT_PHASE:          T3_LAUNCHER_LOCAL_CONSUMER
CURRENT_OWNER:          TEAM_LAUNCHER (Supported by TEAM_COORDINATION)
TELEMETRY_PIPE:         \\.\pipe\NekoProxyCoreTelemetry
SCHEMA_VERSION:         1
PRE_T3_LAUNCHER_HEAD:   7b55a3cb2d7e494734c197003669062e533f4bee
CORE_AUTHORITY:         f269627351fc6a2c13b07c90f0e43ff69d17f058
T3_DEBUG_EXE_SHA256:    41DA2D49F82BFB4A5D9B06749E7CF380E66247AFD908849DE72F851E64EDA9A6
FRESH_MEI_ROOT:         C:\Users\ADVICE\AppData\Local\Temp\_MEI210842
FRESH_MEI_CORE_MATCH:   PASS (100% SHA256 Match across all staged Core binaries)
STALE_THRESHOLD:        4.0s
REAL_PSO2_VALIDATION:   PASS (Ship List & Ship Selection Verified)
DATE:                   2026-08-18
```

---

## 1. Executive Summary & Objective

Phase T3 (**Launcher Local Telemetry Consumer**) connects the customer-facing desktop Launcher (`NekoLauncher`) directly to the local internal Core Telemetry Named Pipe (`\\.\pipe\NekoProxyCoreTelemetry`).

Key capabilities delivered and verified in live PSO2 runtime:
- **Asynchronous Local Telemetry Client**: Dedicated background worker thread continuously streaming snapshot frames from Core without blocking UI or proxy data planes.
- **Fail-Safe & Optional**: Core absence, pipe unavailability, or mid-session consumer disconnection does not disrupt Launcher authentication, game detection, or proxy routing.
- **Strict Privacy Invariant**: Internal client metrics (RX/TX bytes, TCP connection count, DNS counts, subsystem health) are consumed and displayed **strictly locally**. Zero client telemetry is sent to Backend, Supabase, Admin Web, or external endpoints.
- **Monotonic Rate Calculation**: Instantaneous download (RX) and upload (TX) speeds derived with exact timestamp deltas, sequence tracking, and counter-reset protection (negative speed impossible).
- **Human-Friendly UI Meters**: Clear presentation of real-time speeds, cumulative session transfers, proxy uptime, and subsystem health indicators inside the Launcher dashboard.

---

## 2. Architecture & Data Flow

```text
+-------------------------------------------------------------------------+
|                              NekoProxyCore                              |
|                                                                         |
|  [ NetFilter / Redirector / V2Ray / Shadowsocks Data Plane ]           |
|                                 │                                       |
|                       (Lock-Free Atomics)                               |
|                                 ▼                                       |
|                    CoreTelemetryAggregator                              |
|                                 │                                       |
|                 (Periodic Health Snapshot ~1000ms)                      |
|                                 ▼                                       |
|              Named Pipe: \\.\pipe\NekoProxyCoreTelemetry               |
+--------------------------------─┬---------------------------------------+
                                  │ (Local Windows Named Pipe - Read Only)
                                  ▼
+-------------------------------------------------------------------------+
|                        NekoLauncher (Client)                            |
|                                                                         |
|  [ NamedPipeCoreTelemetryClient ] (Daemon Worker Thread)                |
|     - Bounded frame reading (UTF-8 newline-delimited JSON)              |
|     - Lenient deserialization (schema_version = 1)                      |
|     - TelemetryRateCalculator (Delta/Elapsed, Reset Detection)          |
|     - Staleness Tracker (Threshold: 4.0s)                               |
|                                 │                                       |
|                   (TelemetryUpdated Event)                              |
|                                 ▼                                       |
|  [ EventBus ] ──────────────────────────────────────────────────┐       |
|                                                                 │       |
|  [ AppWindow / DashboardView ] ◄────────────────────────────────┘       |
|     - Thread-safe UI update on Tkinter/CTk main loop                    |
|     - Live Speed: ▼ <rx_speed> | ▲ <tx_speed>                           |
|     - Local Transfer: รับข้อมูล (RX): <rx> | ส่งข้อมูล (TX): <tx>       |
|     - Session & Network: เวลา: <hh:mm:ss> | TCP: <n> | DNS: <n>         |
|     - Subsystem Health: Core • V2Ray • SOCKS • Upstream                 |
+-------------------------------------------------------------------------+
```

---

## 3. Rate Calculation & Staleness Semantics

### Rate Calculation Policy
- **Formula**:
  $$\text{rx\_rate} = \max\left(0, \frac{\text{current\_rx\_bytes} - \text{prev\_rx\_bytes}}{\text{current\_timestamp} - \text{prev\_timestamp}}\right)$$
  $$\text{tx\_rate} = \max\left(0, \frac{\text{current\_tx\_bytes} - \text{prev\_tx\_bytes}}{\text{current\_timestamp} - \text{prev\_timestamp}}\right)$$
- **Reset Detection**: If $\text{current\_rx} < \text{prev\_rx}$, $\text{current\_tx} < \text{prev\_tx}$, or $\text{sequence} < \text{prev\_sequence}$, baseline resets immediately and returns `(0.0, 0.0)`.
- **Zero-Elapsed Guard**: If $\text{elapsed} \le 0$, returns `(0.0, 0.0)`.
- **Invariant**: `NEGATIVE_RATE_OBSERVED = NO`.

### Staleness Policy
- **Snapshot Cadence**: Core produces snapshots every ~1000ms.
- **Stale Threshold**: `4.0 seconds`.
- If no snapshot is received within 4.0 seconds while pipe is connected, state transitions to `is_stale = True`, and instantaneous rates fall to `0 B/s (stale)`.

---

## 4. Implemented Source Inventory

### Files Added:
- `launcher/src/neko_launcher/domain/telemetry.py` (CoreHealthSnapshot dataclass, TelemetryState, TelemetryRateCalculator, human-friendly formatters)
- `launcher/src/neko_launcher/infrastructure/core/core_telemetry_client.py` (NamedPipeCoreTelemetryClient with async worker, reconnection, and non-blocking I/O)
- `launcher/tests/test_core_telemetry_domain.py` (Unit tests for domain models, rate calculation, resets, 64-bit bounds, and formatters)
- `launcher/tests/test_core_telemetry_client.py` (Unit tests for schema validation, lenient envelope parsing, malformed JSON, and lifecycle)
- `launcher/tests/test_telemetry_privacy.py` (Privacy boundary tests verifying zero network/cloud transport)

### Files Modified:
- `launcher/src/neko_launcher/domain/events.py` (Added `TelemetryUpdated(Event)`)
- `launcher/src/neko_launcher/ui/views/dashboard_view.py` (Added local observability UI labels and bindings)
- `launcher/src/neko_launcher/ui/app_window.py` (Wired telemetry StringVars, event rendering, and clean shutdown)
- `launcher/src/neko_launcher/bootstrap/app_factory.py` (Instantiated and passed `NamedPipeCoreTelemetryClient` to `AppWindow`)
- `launcher/tests/ui/test_app_window.py` (Added UI unit tests for telemetry rendering and client shutdown)

---

## 5. Automated Test Matrix

- `test_core_telemetry_domain.py`: 12 passed
- `test_core_telemetry_client.py`: 7 passed
- `test_telemetry_privacy.py`: 3 passed
- `test_app_window.py` (UI suite): 27 passed
- **Full Launcher Test Suite**: **474 passed / 474 total** (0 failed, 5 integration deselected)

---

## 6. Packaged Binary & Fresh `_MEI` Proof

```text
============================================================
T3 PACKAGING VERIFICATION
============================================================
T3_DEBUG_EXE_PATH:    D:\Github\Neko-Family-Proxy\launcher\dist\NekoLauncher-Debug.exe
T3_DEBUG_EXE_SHA256:  41DA2D49F82BFB4A5D9B06749E7CF380E66247AFD908849DE72F851E64EDA9A6
FRESH_MEI_ROOT:       C:\Users\ADVICE\AppData\Local\Temp\_MEI210842

PACKAGED BINARY MATCH:
- Redirector.bin:          374A760BFE58F61AF5FE1B6E0A508CAF58BEDE716304DAFCB06763FB4F9F2B27 (PASS)
- NekoProxyCore.exe:       1B9B0BA313AC1F8C879F07F678A2F01E5B334C29FC17323533017AED2CBFFCFE (PASS)
- NekoProxyCore.Core.dll:  DE05FC05594AED8FB09200B1EF9B57642706132DD18E7DEBC06F41CE81A25E02 (PASS)
============================================================
```

---

## 7. Real Runtime PSO2 Validation & Live Telemetry Proof

```text
============================================================
T3 REAL RUNTIME VALIDATION EVIDENCE
============================================================
VALIDATION_SESSION:     2026-08-18 (Live Customer Account & Real PSO2 Session)
ACCOUNT:                zalovenext (Authenticated, 72 days remaining)
PSO2_PROCESS_PID:       11052
CORE_PROCESS_PID:       21624
PSO2_SCREEN_STATE:      Ship Selection (Ship 01-10 List Accessible & Responsive)
REAL_PROXY_ROUTING:     PROVEN (PSO2 Game traffic successfully redirected through Core)

LIVE TELEMETRY READINGS (Sample Session Progression):
- Frame T1 (00:00:50):
    * RX Total: 14.5 KB
    * TX Total: 2.1 KB
    * Active TCP: 3
    * DNS Total: 3
    * Subsystem Status: Core Normal • V2Ray Running • SOCKS Ready • Upstream Connected
- Frame T2 (00:02:15):
    * RX Total: 45.7 KB
    * TX Total: 6.4 KB
    * Active TCP: 10
    * DNS Total: 10
    * Subsystem Status: Core Normal • V2Ray Running • SOCKS Ready • Upstream Connected

OBSERVATIONS:
- Monotonic RX/TX bytes growth: PASS
- Non-negative speed bounds: PASS (▼ 0 B/s | ▲ 0 B/s during idle periods)
- Core status synchronization: PASS (ProxyCore: ทำงานแล้ว)
- Telemetry isolation: PASS (No impact on proxy data plane)
============================================================
```

---

## 8. Privacy Boundary Compliance

- **No Remote Telemetry API**: Zero new endpoints in Backend / Web.
- **No Supabase Telemetry Writes**: Supabase tables and RPCs remain untouched.
- **Strict Data Minimization**: Client telemetry is never attached to heartbeat requests or uploaded to servers.
- `CLIENT_DEEP_TELEMETRY_SENT_TO_BACKEND = NO`

---

## 9. Performance & Known Limitations

### Performance Observations:
- **CPU Regression**: NO
- **Memory Regression**: NO
- **UI Responsiveness**: Smooth, non-blocking UI update ticks on Tkinter main loop.

### Known Limitations & Next Phase:
- T3 scope is limited to local on-client presentation.
- Server-side monitoring, aggregate health checks, and fleet-wide status dashboards belong to **T4 (Server Monitoring & Metrics)**.
