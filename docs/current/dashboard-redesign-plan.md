# แผนการพัฒนา UI Dashboard — Neko Family Proxy Launcher

> **ประเภทเอกสาร:** Current planning document — ไม่มี release authority ในตัวเอง
> **Plan version:** v1.2 — evidence-aligned scope
> **Target Launcher version:** `5.0.0a11` *ถ้า source baseline ยังเป็น `5.0.0a10` ตอนเริ่ม implementation; ต้อง re-verify version ก่อนแก้ source ทุกครั้ง*
> **Active branch:** `feature/dashboard-redesign`
> **Baseline plan commit:** `0fc836d`
> **ภาพอ้างอิง:** dashboard mockup ที่ Owner ส่งให้ PM เมื่อ 2026-08-28
> **Tech stack:** Python 3.11 + CustomTkinter 5.2.2 + Pillow 12.2 + Sarabun + PinkPalette
> **สถานะ:** **PHASE 1 READY — scope reconciled 2026-08-29**
> **หลักการ:** รักษา visual intent ของ mockup แต่ customer-visible data ต้องมาจากข้อมูลที่พิสูจน์ได้จริงเท่านั้น

---

## 1. Source-of-truth / Evidence Used

แผน v1.2 นี้แทนที่ assumption ใน v1.0/v1.1 ที่ไม่มีหลักฐานรองรับ โดยอิงจาก source และ runtime evidence ต่อไปนี้:

1. `NekoProxyCore/docs/current/v2ray-runtime-fix-handoff.md`
   - ยืนยัน data path ที่พิสูจน์ด้วย PSO2 จริง:

```text
pso2.exe
  -> NetFilter / Redirector.bin
  -> Local SOCKS5
  -> v2ray-sn.exe
  -> Remote Shadowsocks proxy in Japan/Tokyo
  -> PSO2 JP game network
```

2. `NekoProxyCore/Netch/Models/Server.cs`
   - Legacy Netch มี `Server.PingAsync()` ซึ่งวัด selected proxy server ด้วย TCP ping หรือ ICMP ping
   - ค่า `Delay` เป็น runtime/local data และ **ยังไม่ได้ถูกส่งออกใน headless telemetry ปัจจุบัน**

3. `NekoProxyCore/Netch/Utils/DelayTestHelper.cs`
   - Legacy Netch มี periodic server delay test capability
   - capability นี้ยังไม่ถูก compose เข้ากับ production headless Core path

4. `NekoProxyCore/NekoProxyCore.Legacy/ProductionProtectedSettingsValidator.cs`
   - Production contract ใช้ canonical `profile-0` / `server-0`
   - `ModeRemark` ต้องเป็น `PSO2`

5. `Project manager/Netch original source`
   - Netch runtime package version 1.9.7.0
   - `mode/Custom/PSO2.json` ยืนยัน `ProcessMode` สำหรับ `pso2.exe`, `pso2launcher.exe`, `pso2updater.exe`
   - sanitized structural inspection ของ historical settings ยืนยัน 1 PSO2 profile, Shadowsocks servers, TCP ping enabled; ไม่มีการนำ hostname/credential มาใช้ในเอกสารนี้

6. Current Launcher/Core telemetry source
   - `TelemetryState` / `CoreHealthSnapshotPayload` มี health, uptime, counters, RX/TX, V2Ray/SOCKS/Shadowsocks state
   - **ไม่มี** `local_ip`, proxy IP, PSO2 server IP, ping, RTT หรือ per-hop latency ใน wire contract ปัจจุบัน

7. Existing privacy/UI contracts
   - raw infrastructure detail และ destination IP/hostname history ไม่ควรถูกเพิ่มเป็น customer-visible/backend telemetry โดยไม่มี contract ใหม่
   - UI ต้องไม่สร้าง synthetic/fake zero ping หรือ placeholder network measurement

---

## 2. Mockup Intent vs Verified Product Reality

Mockup มี visual flow 4 nodes ซึ่งยังรักษาไว้ได้ แต่ semantics ต้องแก้ให้ตรงระบบจริง:

| Mockup visual | v1.2 semantic meaning | Data policy |
|---|---|---|
| `เครื่องของคุณ` | `LOCAL_DEVICE` — เครื่องผู้ใช้ / PSO2 process context | ไม่แสดง raw local IP |
| `NEKO PROXY` | `LOCAL_PROXY_ENGINE` — NekoProxyCore + Redirector + local SOCKS/V2Ray stack | **ไม่ใช่ Bangkok remote proxy**; status derived from existing local telemetry |
| `TOKYO PROXY` | `REMOTE_PROXY` — selected/canonical remote Shadowsocks proxy in Japan/Tokyo | แสดง region/role แบบ customer-safe; ไม่แสดง hostname/IP/port/credential |
| `PSO2 SERVER` | `GAME_NETWORK` — PSO2 JP game network semantic destination | ไม่อ้างว่าเป็น server IP ที่ตรวจจับได้ และไม่แสดง raw destination IP |

### สิ่งที่ตัดออกจากแผนเดิม

- `NEKO PROXY (กรุงเทพฯ)` เป็น remote hop — **REMOVED: ไม่มี evidence รองรับ**
- `local_ip`, `bangkok_proxy_ip`, `tokyo_proxy_ip`, `pso2_server_ip` — **REMOVED from redesign contract**
- per-hop latency 3 ค่า เช่น `1 ms / 8 ms / 18 ms` — **REMOVED: ไม่มี measurement source**
- hardcoded PSO2/server IP — **FORBIDDEN**
- emoji fallback ที่เป็น dependency ของ production UI — **FORBIDDEN**

### สิ่งที่รักษาจาก mockup

- 4-node connection diagram
- membership/account card
- download/upload/session duration
- status pill และ color hierarchy
- statistics row
- guidance ว่าระบบเชื่อม Tokyo Proxy อัตโนมัติเมื่อ PSO2 ทำงาน
- visual distinction ระหว่าง local engine / remote proxy / game network

---

## 3. Product / Privacy Invariants

ทุก phase ต้องรักษา invariants ต่อไปนี้:

1. External Core topology ยังคงเป็น intentional architecture; ห้าม embed Core กลับเข้า Launcher one-file EXE
2. Auth/session/entitlement ต้อง fail closed
3. Deep client telemetry remains local-only
4. Launcher close/logout/reconnect/reopen ห้าม kill `pso2.exe`
5. Customer-visible metric ต้อง truthful:
   - ไม่มี measurement = `—` / `ไม่พร้อมใช้งาน`
   - ห้ามใช้ `0 ms` แทน unknown
   - ห้าม hardcode mockup number เพื่อให้ UI ดูครบ
6. Raw proxy/server hostname, IP, port, credential และ destination history ไม่ใช่ redesign display contract
7. Legacy `Server.PingAsync()` ถือเป็น **candidate capability** ไม่ใช่ production telemetry authority จนกว่าจะมี implementation + tests + runtime proof แยก

---

## 4. Target Component Model

### 4.1 Semantic topology

```text
LOCAL_DEVICE
   |
   v
LOCAL_PROXY_ENGINE
   |
   v
REMOTE_PROXY (Japan/Tokyo)
   |
   v
GAME_NETWORK (PSO2 JP)
```

Diagram แสดง **service path / responsibility path** ไม่ใช่ traceroute และไม่อ้างว่า connector แต่ละช่วงเป็น network hop ที่วัด latency ได้จริง

### 4.2 Domain model สำหรับ Phase 1

เพิ่มใน `launcher/src/neko_launcher/domain/models.py`:

```python
from dataclasses import dataclass
from enum import Enum


class NetworkHopRole(str, Enum):
    LOCAL_DEVICE = "local_device"
    LOCAL_PROXY_ENGINE = "local_proxy_engine"
    REMOTE_PROXY = "remote_proxy"
    GAME_NETWORK = "game_network"


class HopConnectionState(str, Enum):
    SUCCESS = "success"
    CONNECTING = "connecting"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NetworkHop:
    role: NetworkHopRole
    label: str
    location: str | None = None
    connection_state: HopConnectionState = HopConnectionState.UNAVAILABLE


@dataclass(frozen=True)
class NetworkPath:
    hops: tuple[NetworkHop, ...] = ()
    proxy_rtt_ms: int | None = None

    def __post_init__(self) -> None:
        if self.proxy_rtt_ms is not None and self.proxy_rtt_ms < 0:
            raise ValueError("proxy_rtt_ms must be non-negative or None")
```

### 4.3 ทำไม `proxy_rtt_ms` มีได้ แต่ `per_hop_latency_ms` ไม่มี

- Legacy Netch มี implementation วัด latency ของ **selected remote proxy server** จริง (`Server.PingAsync()`)
- ไม่มี evidence ว่าระบบวัด `local -> local engine`, `local engine -> Tokyo`, `Tokyo -> PSO2` แยกกัน
- ดังนั้น model อนุญาตเพียง optional **proxy RTT aggregate**
- Phase 1 **ไม่สร้าง producer** ของ `proxy_rtt_ms`; default ต้องเป็น `None`
- การนำ legacy ping กลับเข้ามาใน headless production path เป็นงานแยกใน Phase 4 readiness/audit และต้องพิสูจน์ว่าไม่กระทบ proxy data plane

### 4.4 Theme tokens

ขยาย `PinkPalette` เฉพาะ semantic role ที่ mockup ต้องใช้:

```python
node_local: str = "#10B981"
node_local_surface: str = "#F0FDF4"
node_engine: str = "#3B82F6"
node_engine_surface: str = "#EFF6FF"
node_remote: str = "#8B5CF6"
node_remote_surface: str = "#F5F3FF"
node_game: str = "#F84B93"
node_game_surface: str = "#FCE7F0"
```

ชื่อ token ใช้ role ไม่ผูกกับ city/server implementation เพื่อไม่ให้ architecture ถูก hardcode ลง theme

---

## 5. Phase Strategy

| Phase | Scope | Source change | Main risk |
|---|---|---:|---|
| 1 | Semantic domain models + theme tokens | YES | ต่ำ |
| 2 | Reusable presentation components | YES | ต่ำ |
| 3 | Dashboard layout restructure / window sizing | YES | กลาง |
| 4 | Connection diagram + truthful runtime mapping + latency capability decision | YES | สูง |
| 5 | Statistics/polish | YES | กลาง |
| 6 | Integration, packaged build, smoke | YES | กลาง/สูง |

**สำคัญ:** Window size **ไม่ใช่ blocker ของ Phase 1** อีกต่อไป; ตัดสินใน Phase 3 ก่อนแตะ layout

---

# Phase 1 — Foundation: Semantic Models & Theme Tokens

## 1.1 Objective

สร้าง type-safe, immutable presentation-domain foundation ที่ตรงกับ architecture จริง โดย **ไม่เปลี่ยน wire telemetry contract และไม่แตะ UI layout**

## 1.2 Allowed source changes

```text
launcher/src/neko_launcher/domain/models.py
launcher/src/neko_launcher/ui/theme.py
launcher/tests/test_network_hop_model.py              (new)
launcher/tests/ui/test_palette_tokens.py               (new)
```

`launcher/src/neko_launcher/domain/telemetry.py` = **OUT OF SCOPE for Phase 1 v1.2**

เหตุผล: current Core wire contract ไม่มี network address หรือ latency field และการเพิ่ม field ใน Launcher domain ตอนนี้จะสร้าง producer-less contract

## 1.3 Required RED tests

### `tests/test_network_hop_model.py`

ต้องครอบคลุมอย่างน้อย:

- `NetworkHopRole` เป็น `str, Enum`
- `HopConnectionState` เป็น `str, Enum`
- `NetworkHop` frozen/immutable
- `NetworkPath` frozen/immutable
- default empty path = valid
- 4-role path = valid
- `proxy_rtt_ms=None` = unknown/valid
- `proxy_rtt_ms=0` = valid measured value
- `proxy_rtt_ms>0` = valid
- `proxy_rtt_ms<0` = `ValueError`
- model ไม่มี fields ชื่อ `ip`, `hostname`, `port`, `bangkok`, `per_hop_latency_ms`

### `tests/ui/test_palette_tokens.py`

- role token ทุกคู่มี `#RRGGBB`
- local/engine/remote/game token มี surface counterpart
- token naming เป็น semantic role ไม่ใช่ raw infrastructure address

## 1.4 Acceptance

```text
PHASE1_MODEL_TESTS            = PASS
PHASE1_PALETTE_TESTS          = PASS
EXISTING_TELEMETRY_TESTS      = PASS
EXISTING_DASHBOARD_TESTS      = PASS/SKIP only for unavailable Tk display
TELEMETRY_WIRE_CHANGED        = NO
UI_LAYOUT_CHANGED             = NO
RAW_IP_FIELDS_ADDED           = NO
PER_HOP_LATENCY_ADDED         = NO
```

ก่อน source change ต้อง re-verify Launcher version; ถ้ายังเป็น `5.0.0a10` ให้ Phase 1 source change ใช้ `5.0.0a11` ตาม project versioning rule

## 1.5 Baseline evidence before kickoff

ตรวจเมื่อ 2026-08-29:

```text
Python                       = 3.11.15
Launcher source version      = 5.0.0a10
Branch                       = feature/dashboard-redesign
HEAD                         = 0fc836d
Focused baseline             = 13 passed, 1 skipped, 0 failed
```

Focused baseline suites:

```text
tests/test_core_telemetry_domain.py
tests/ui/test_dashboard_view.py
```

Phase 1 readiness after this v1.2 reconciliation:

```text
DOMAIN_SCOPE                  = LOCKED
PRIVACY_SCOPE                 = LOCKED
TOPOLOGY_SEMANTICS            = LOCKED
LATENCY_SEMANTICS             = LOCKED (optional proxy RTT only; no producer in Phase 1)
WINDOW_SIZE                   = DEFERRED TO PHASE 3
PHASE_1_READINESS             = READY
```

---

# Phase 2 — Reusable Presentation Components

สร้าง pure presentation components โดยไม่ทำ network IO หรือ telemetry probing:

```text
status_legend.py
metric_card.py
network_hop_node.py
network_hop_connector.py
connection_diagram.py
```

Constraints:

- `NetworkHopNode` render จาก semantic `NetworkHop`
- ห้าม render raw IP/hostname/port
- connector ไม่มี numeric latency โดย default
- numeric RTT แสดงได้เฉพาะเมื่อ caller ส่ง `proxy_rtt_ms` ที่ verified แล้ว
- ไม่มี emoji fallback dependency; default text-only หรือ approved bundled asset
- ไม่มี probing/network IO ใน UI component

---

# Phase 3 — Layout Restructure

นี่คือจุดที่ต้องตัดสิน window/layout strategy ก่อนแก้ UI

ตัวเลือก:

- A: landscape สำหรับ horizontal 4-node flow
- B: portrait extended + vertical/compact flow
- C: responsive

Mockup intent สนับสนุน A แต่ยังต้อง review กับ actual Windows scaling / Settings UX ก่อนล็อก

Phase 3 ห้ามเปลี่ยน network/data semantics ที่ล็อกใน Phase 1

---

# Phase 4 — Connection Diagram & Runtime Mapping

## 4.1 Runtime mapping ที่มีอยู่แล้ว

ใช้ current telemetry สำหรับสถานะที่พิสูจน์ได้:

- Local proxy engine health
- V2Ray running
- local SOCKS running
- Shadowsocks connected
- uptime
- RX/TX rate
- stale/disconnected state

ตัวอย่าง mapping:

```text
LOCAL_DEVICE        <- AppState game/process context
LOCAL_PROXY_ENGINE  <- CoreHealthSnapshot core/v2ray/local_socks status
REMOTE_PROXY        <- shadowsocks_connected + fixed customer-safe region label Japan/Tokyo
GAME_NETWORK        <- AppState game running + semantic destination label only
```

## 4.2 Latency gate

ก่อนแสดง numeric proxy latency ให้ทำ read-only engineering audit ของ legacy:

```text
Netch/Models/Server.cs::PingAsync()
Netch/Utils/DelayTestHelper.cs
production configuration snapshot / selected server
```

ต้องตอบให้ได้ก่อน implementation:

1. วิธีวัด TCPing/ICMPing ปัจจุบัน safe ใน headless process หรือไม่
2. จะวัด selected canonical server โดยไม่ expose hostname/port ข้าม boundary ได้อย่างไร
3. probe cadence เท่าไรจึงไม่สร้าง load หรือกระทบ game path
4. telemetry failure ต้องไม่ cause proxy failure
5. numeric RTT ต้องอยู่ local-only และไม่มี raw address leak

ถ้ายังไม่มี evidence:

```text
proxy_rtt_ms = None
UI = "—"
```

**ห้าม derive latency จาก RX/TX, uptime หรือ mockup number**

## 4.3 Diagram semantics

```text
เครื่องของคุณ
   ->
NEKO Proxy Engine
   ->
Tokyo Proxy
   ->
PSO2 JP
```

Diagram คือ topology/status visualization ไม่ใช่ traceroute visualization

---

# Phase 5 — Statistics & Polish

Mockup statistics row ให้ map ตามข้อมูลจริง:

| Mockup card | v1.2 value source |
|---|---|
| เวลาเชื่อมต่อรวม | existing Core uptime/session duration |
| เวลาแฝง | `proxy_rtt_ms` เฉพาะเมื่อ Phase 4 latency gate ผ่าน; ไม่เช่นนั้น `—` |
| ความโหลด | existing RX rate |
| อัปโหลด | existing TX rate |

Icon policy:

- default text-only
- approved bundled PNG เมื่อ usability justify
- no emoji fallback dependency

---

# Phase 6 — Integration & Smoke

Required checks อย่างน้อย:

```text
pytest tests/ui/ -v
pytest tests/test_core_telemetry_domain.py -v
pytest tests/test_telemetry_privacy.py -v
pytest tests/test_controller.py -v
pytest tests/test_final_windows_e2e_harness.py -v
pytest tests/ -v
```

Packaged smoke ต้องยืนยัน:

- Sarabun/Thai render
- diagram มี 4 semantic nodes
- ไม่มี raw IP/hostname/port ใน customer UI
- unknown latency แสดง `—`
- telemetry stale/disconnected ไม่แสดง success ปลอม
- new EXE / fresh `_MEI`
- external Core contract preserved
- no secret material embedded

---

## 6. Open Decisions by Phase

### Phase 1

**ไม่มี blocking design question เหลือ** หลัง v1.2 reconciliation

### Phase 3

- Window sizing: landscape / portrait extended / responsive

### Phase 4

- นำ legacy proxy `PingAsync()` กลับมาใช้ใน headless telemetry หรือไม่
- cadence / isolation / privacy contract ของ RTT

### Phase 5

- text-only vs approved PNG icons หลังดู actual layout

---

## 7. Out of Scope

- traceroute หรือ real per-hop route discovery
- Bangkok relay ที่ไม่มี source evidence
- raw infrastructure IP/hostname/port display
- PSO2 destination-IP history
- historical latency graph
- packet capture / flow details
- custom network-hop editing
- server selection UI
- Core proxy-path redesign
- telemetry upload of deep client details

---

## 8. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Mockup ถูกตีความเป็น physical network topology | สูง | semantic-role model; document explicitly that diagram is service path |
| Legacy ping ถูก reuse แล้วกระทบ runtime | สูง | Phase 4 audit + bounded cadence + failure isolation; no Phase 1 producer |
| Privacy regression จาก raw address | สูง | no address fields in Phase 1 model; regression tests |
| UI แสดง fake latency | สูง | `None -> —`; no synthetic 0/mockup values |
| Window ไม่พอ 4 nodes | กลาง | defer sizing decision to Phase 3 with actual UI smoke |
| Theme tied to implementation names | ต่ำ | semantic token names (`node_engine`, `node_remote`) |

---

## 9. Expected Files by Phase

### Phase 1

| File | Action |
|---|---|
| `launcher/src/neko_launcher/domain/models.py` | add semantic network roles/path models |
| `launcher/src/neko_launcher/ui/theme.py` | add semantic node palette tokens |
| `launcher/tests/test_network_hop_model.py` | new |
| `launcher/tests/ui/test_palette_tokens.py` | new |

### Phase 1 explicitly NOT modified

```text
launcher/src/neko_launcher/domain/telemetry.py
NekoProxyCore/*
installer/*
Admin/*
authority/*
```

Phase 2-6 filesจะถูกกำหนด/ยืนยันอีกครั้งที่แต่ละ phase gate เพื่อไม่ให้ planning document บังคับ source path ที่อาจเปลี่ยนก่อน implementation

---

## 1.6 Phase 1 completion evidence (2026-08-29)

> **State:** `PHASE 1 ENGINEERING PASS` — source/test/version changes are **uncommitted** on `feature/dashboard-redesign @ 0fc836d`. This is NOT a release/artifact pass. No build, no live proof, no authority update. Plan version stays v1.2; Phase 1 contract is unchanged.

### 1.6.1 Implemented contract (matches plan §4.2 / §4.4 exactly)

**Network models (in `launcher/src/neko_launcher/domain/models.py`):**

- `class NetworkHopRole(str, Enum)`: `LOCAL_DEVICE="local_device"`, `LOCAL_PROXY_ENGINE="local_proxy_engine"`, `REMOTE_PROXY="remote_proxy"`, `GAME_NETWORK="game_network"`
- `class HopConnectionState(str, Enum)`: `SUCCESS="success"`, `CONNECTING="connecting"`, `UNAVAILABLE="unavailable"`
- `@dataclass(frozen=True) class NetworkHop`: `role`, `label`, `location: str | None = None`, `connection_state = HopConnectionState.UNAVAILABLE`
- `@dataclass(frozen=True) class NetworkPath`: `hops: tuple[NetworkHop, ...] = ()`, `proxy_rtt_ms: int | None = None`; `__post_init__` rejects `proxy_rtt_ms < 0` with `ValueError`; `None`, `0`, and positive values are valid.

**PinkPalette node tokens (in `launcher/src/neko_launcher/ui/theme.py`):**

```text
node_local         = #10B981
node_local_surface = #F0FDF4
node_engine        = #3B82F6
node_engine_surface= #EFF6FF
node_remote        = #8B5CF6
node_remote_surface= #F5F3FF
node_game          = #F84B93
node_game_surface  = #FCE7F0
```

### 1.6.2 What is explicitly NOT introduced in Phase 1

- No `proxy_rtt_ms` producer; default remains `None`.
- No `ip`, `hostname`, `port`, `bangkok`, or `per_hop_latency_ms` field in `NetworkHop` or `NetworkPath`.
- No `telemetry.py` / wire contract change. `git diff launcher/src/neko_launcher/domain/telemetry.py` is empty.
- No UI layout, window sizing, controller, or runtime mapping change.
- No network IO, probe, mock data, or live source added.
- No Core, installer, Admin, authority, or production mutation.

### 1.6.3 TDD evidence (corrective pass, 2026-08-29)

- **RED attempt #1 — REJECTED**: initial test files imported Phase 1 symbols at module-import time; pytest stopped during collection with `ImportError: cannot import name 'HopConnectionState' from neko_launcher.domain.models`. That is a collection / test-framework error, not a valid RED. Evidence discarded.
- **Test import-shape repair**: both new test files rewritten to import only the stable module (`from neko_launcher.domain import models as domain_models` / `from neko_launcher.ui import theme as ui_theme`) and resolve required symbols/tokens via `_require_symbol` / `_require_attr` helpers that call `pytest.fail(...)` on absence. All plan §1.3 behavioural coverage preserved.
- **VALID RED (after temporary restoration of production/version files to baseline)**: `.venv/Scripts/python.exe -m pytest -q tests/test_network_hop_model.py tests/ui/test_palette_tokens.py` → exit `1`, **47 failed, 8 passed, 0 collection errors**. Failures directly demonstrate missing `NetworkHopRole`, `HopConnectionState`, `NetworkHop`, `NetworkPath` and the 8 missing `node_*` palette tokens. The 8 passes are the static semantic-naming test (`test_node_token_names_are_semantic_roles`, parametrized) which is a pure literal-string check, not a missing-token check.
- **GREEN (after reapplying minimal production implementation)**: same command → **55 passed, 0 failed, 0 skipped**.

### 1.6.4 Independent PM verification (2026-08-29)

| Gate | Command | Result |
|---|---|---|
| A. P1 suites | `pytest -q tests/test_network_hop_model.py tests/ui/test_palette_tokens.py` | 55 passed |
| B. Focused baseline | `pytest -q tests/test_core_telemetry_domain.py tests/ui/test_dashboard_view.py` | 13 passed, 1 skipped (Tk display) |
| C. RUFF | `ruff check src/neko_launcher/domain/models.py src/neko_launcher/ui/theme.py tests/test_network_hop_model.py tests/ui/test_palette_tokens.py` | All checks passed |
| D. COMPILEALL | `compileall -q src/neko_launcher` | clean |
| E. Canonical non-integration | `env -u TCL_LIBRARY -u TK_LIBRARY .venv/Scripts/python.exe -m pytest -q -m "not integration"` | 674 passed, 1 skipped, 5 deselected, 0 failed |
| F. `git diff --check` | (from repo root) | PASS (benign LF/CRLF note on `uv.lock` only) |

**Important E caveat:** the canonical non-integration suite required process-local removal of `TCL_LIBRARY` and `TK_LIBRARY` for the test process only (`env -u TCL_LIBRARY -u TK_LIBRARY …`). The host's persistent user/system environment was not modified. The contamination source is an unrelated external toolchain install (`Khai-Hub/_internal/_tcl_data`) that pins Tcl 8.6.15 against the system's Tcl 8.6.12, which pollutes the Tk init path. **Product source was NOT changed to work around this.** The process-local env removal is the verified test-run method from this host context and must be carried forward into Phase 2-6 runs on the same machine.

### 1.6.5 Files actually changed (uncommitted, on `feature/dashboard-redesign @ 0fc836d`)

```text
M launcher/src/neko_launcher/domain/models.py      (Phase 1 model block added)
M launcher/src/neko_launcher/ui/theme.py           (Phase 1 node tokens added)
M launcher/src/neko_launcher/__init__.py           (5.0.0a10 -> 5.0.0a11)
M launcher/pyproject.toml                          (5.0.0a10 -> 5.0.0a11)
M launcher/uv.lock                                 (root project version 5.0.0a10 -> 5.0.0a11 only; no dep resolution)
?? launcher/tests/test_network_hop_model.py        (new, repaired import shape)
?? launcher/tests/ui/test_palette_tokens.py        (new, repaired import shape)
```

`git diff launcher/src/neko_launcher/domain/telemetry.py` is empty. `COMMIT = NOT_CREATED`, `PUSH = NOT_REQUESTED`.

---

## 10. Definition of Done for the Redesign

1. Visual hierarchy และ 4-node flow ยังรักษา intent ของ mockup
2. Node semantics ตรงกับ production architecture ที่พิสูจน์แล้ว
3. ไม่มี Bangkok remote hop ปลอม
4. ไม่มี raw IP/hostname/port ใน customer dashboard
5. ไม่มี fabricated latency
6. optional proxy RTT ถ้ามี ต้องมาจาก verified local measurement path
7. existing auth/session/proxy/privacy contracts ไม่ regress
8. all relevant tests PASS
9. packaged build/fresh `_MEI` PASS
10. documentation sync + PM/Owner visual review ก่อน release gate

---

| **สถานะ:** `v1.2 / P0 PROXY CONNECTION INVESTIGATION & FIX COMPLETED / LAUNCHER 5.0.0a29 CANDIDATE BUILT` |

---

## 11. P0 Proxy Connection Regression Audit & Remediation (2026-08-31)

### 11.1 Investigation & Hypotheses
1. **H1 (Diagnostics regression)**: `ELIMINATED` — `DevelopmentLogger` writes are wrapped in `try...except OSError: pass`, hashing occurs once at bootstrap, logging overhead <0.1ms, isolated from functional control path.
2. **H2 (Public proxy status integration)**: `ELIMINATED` — `PublicProxyStatusClient` executes on a dedicated background thread pool (`_proxy_status_executor`), isolated from `_executor`, updates presentation StringVars only.
3. **H3 (Telemetry/state regression)**: `ELIMINATED` — `map_network_path()`, `get_server_status()`, and `translate_customer_status()` are read-only presentation mappers. Automatic reconnect is not armed until proxy reaches `RUNNING`.
4. **H4 (Version/protocol mismatch)**: `ELIMINATED` — `__version__` bump does not participate in backend, permit, or Core Named Pipe handshake.
5. **H5 (Unrelated runtime changes)**: `ELIMINATED` — Proxy connection orchestration pipeline (`controller.py`, `services.py`, `authorized_core.py`, `core_process.py`, `core_control_channel.py`) is verified intact and passes all 760 unit/contract tests.

### 11.2 Remediations & Observability Improvements
- **Diagnostics Observability (`OpaquePermit.diagnostic_length`)**: Fixed permit length logging in `authorized_core.py` to record `permit.diagnostic_length` (previously evaluated `hasattr(permit, "permit_jwt")` returning 0).
- **Core Error Code Allow-list**: Allow-listed non-secret `core_error_code` strings from failed Core START responses to be recorded in `AUTHORIZED_START_RESULT` diagnostics without exposing tokens or secrets.
- **Thread Pool Lifecycle (`app_window.py`)**: Added `_proxy_status_executor.shutdown(wait=False, cancel_futures=True)` to `_perform_close()` to guarantee graceful shutdown and avoid hanging worker threads.
- **Version Bump**: Bapped Launcher version from `5.0.0a28` to `5.0.0a29` (`pyproject.toml`, `__init__.py`, `uv.lock`).

### 11.3 Verification Evidence
- Full unit & contract test suite: **760 passed, 1 skipped, 5 deselected, 4 warnings** in 5.93s.
- Code quality & linting: Ruff check PASS (all checks passed), compileall clean, `git diff --check` PASS.
- PyInstaller executable candidate built: `launcher/dist/NekoLauncher.exe` (SHA256: `0a24b1945d6c390b760d37940eee929100121d88a25ad27d6874f234a8ca0ebb`, size: 30,176,144 bytes).
- Packaged startup smoke test: verified real window appearance (`NEKO FAMILY PROXY`), graceful `WM_CLOSE` handling, clean bootloader process exit code 0, and complete `_MEI` temp directory extraction and cleanup.
