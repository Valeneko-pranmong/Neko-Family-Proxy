# แผนการพัฒนา UI Dashboard — Neko Family Proxy Launcher

> **ประเภทเอกสาร:** เอกสารแผนงาน (Planning Document) — ไม่มีการแก้ไข source code
> **Target version:** v5.0.0a10+ (post-beta redesign)
> **ภาพอ้างอิง:** `composer_2026-08-28_15-25-30-259_c249c0.png`
> **Tech stack ที่ยืนยันแล้ว:** Python 3.11 + CustomTkinter 5.2.2 + Pillow 12.2 + Sarabun font + PinkPalette
> **สถานะ:** Draft v1.0 (2026-08-28)
> **ผู้จัดทำ:** PM
> **Reviewer:** TBD
> **Date:** 2026-08-28

---

## สารบัญ

1. [บริบทและเหตุผล](#1-บริบทและเหตุผล)
2. [เป้าหมายและขอบเขต](#2-เป้าหมายและขอบเขต)
3. [สถาปัตยกรรมเป้าหมาย](#3-สถาปัตยกรรมเป้าหมาย)
4. [กลยุทธ์การแบ่ง Phase](#4-กลยุทธ์การแบ่ง-phase)
5. [Phase 1 — Foundation](#phase-1--foundation-data-models--theme-tokens)
6. [Phase 2 — Reusable Components](#phase-2--reusable-components)
7. [Phase 3 — Layout Restructure](#phase-3--layout-restructure)
8. [Phase 4 — Connection Diagram](#phase-4--connection-diagram-largest-phase)
9. [Phase 5 — Statistics & Polish](#phase-5--statistics--polish)
10. [Phase 6 — Integration & Smoke](#phase-6--integration--smoke)
11. [Risk Register](#5-risk-register)
12. [Open Questions for PM](#6-open-questions-for-pm)
13. [Out of Scope](#7-out-of-scope-deferred)
14. [Success Criteria](#8-success-criteria)
15. [ไฟล์ที่คาดว่าจะถูกแก้ไข](#9-ไฟล์ที่คาดว่าจะถูกแก้ไข)

---

## 1. บริบทและเหตุผล

### 1.1 ภาพรวมปัจจุบัน (verified 2026-08-28)

UI ของ Neko Family Proxy launcher v5.0.0a10 ถูกพัฒนาด้วย **CustomTkinter 5.2.2** บน Python 3.11 โดยมีโครงสร้างหลักดังนี้:

| ไฟล์ | บทบาท |
|---|---|
| `launcher/src/neko_launcher/ui/app_window.py` | Root window + view switching (1,566 LOC) |
| `launcher/src/neko_launcher/ui/views/dashboard_view.py` | Post-login customer dashboard |
| `launcher/src/neko_launcher/ui/views/auth_view.py` | Login/register form |
| `launcher/src/neko_launcher/ui/views/recovery_view.py` | Account recovery form |
| `launcher/src/neko_launcher/ui/theme.py` | PinkPalette + Sarabun font loader |
| `launcher/src/neko_launcher/ui/components/buttons.py` | card(), primary_button(), icon_entry() |
| `launcher/src/neko_launcher/ui/components/toast.py` | Toast notification |
| `launcher/src/neko_launcher/ui/platform/window_chrome.py` | Rounded window shape + native title bar |
| `launcher/src/neko_launcher/ui/platform/window_scaling.py` | `fit_portrait_window()` (~440×620) |
| `launcher/src/neko_launcher/ui/platform/system_tray.py` | System tray manager |
| `Asset/setting.png` | Reference mockup (19,182 B, dark theme v2.5.0) |

### 1.2 Design Goal ใหม่ (จากภาพที่ส่งมา)

ภาพ `composer_2026-08-28_15-25-30-259_c249c0.png` แสดง **dashboard mockup ใหม่** ที่มีองค์ประกอบที่ปัจจุบันยังไม่มี:

| Component | รายละเอียด |
|---|---|
| **Header banner** | "NEKO FAMILY PROXY" + "High Performance & Low Latency" + status pill "พร้อมใช้งาน" (เขียว) |
| **Card "สมาชิก"** | ชื่อผู้ใช้ (tester) + วันคงเหลือ (24 วัน) + วันหมดอายุ (21/09/2026 10:56) + badge "ใช้งานได้" |
| **Card "เครื่องช่วย"** | ความโหลด + อัปโหลด + เวลาเชื่อมต่อ |
| **Connection Diagram** | 4 nodes: เครื่องของคุณ → NEKO PROXY (กรุงเทพฯ) → TOKYO PROXY (โตเกียว) → PSO2 SERVER (Japan) พร้อม latency ระหว่าง hops (1 ms / 8 ms / 18 ms) |
| **Legend** | 3 dots: เขียว=เชื่อมต่อสำเร็จ / เหลือง=กำลังเชื่อมต่อ / แดง=ไม่พร้อมใช้งาน |
| **Statistics row** | 4 cards: เวลาเชื่อมต่อรวม (27 ms) / เวลาแฝง (27 ms) / ความโหลด (- Mbps) / อัปโหลด (- Mbps) |
| **Footer tip** | 💡 ระบบจะเชื่อมต่อ Tokyo Proxy อัตโนมัติเมื่อเปิดเกม PSO2 |
| **Version** | v5.0.0a10 |

### 1.3 เหตุผลที่ต้อง Redesign

1. **Visual upgrade** — design ใหม่มี color hierarchy ที่ชัดเจนกว่า (node-specific accent colors)
2. **Transparency** — Connection diagram แสดง network path ให้ผู้ใช้เห็นชัดเจน
3. **Data density** — 4-column statistics bar เพิ่ม information density
4. **Consistency** — ใช้ PinkPalette tokens ที่มีอยู่แล้ว แต่ขยายด้วย node-specific tokens

---

## 2. เป้าหมายและขอบเขต

### 2.1 Functional Goals

- ✅ Render dashboard ตามภาพ mockup โดยใช้ existing tech stack
- ✅ Truthful telemetry — ทุก IP/latency ที่แสดงต้องมาจาก telemetry state จริง
- ✅ Backward-compatible StringVars เดิมยังทำงาน
- ✅ Existing tests ไม่ regress

### 2.2 Non-Goals (Out of Scope)

- ❌ Animation/transition ระหว่าง state changes
- ❌ Custom font/typography (ยังใช้ Sarabun)
- ❌ Dark mode variant
- ❌ Localization ภาษาอื่น
- ❌ Interactive diagram (click node = details)
- ❌ Historical telemetry chart

---

## 3. สถาปัตยกรรมเป้าหมาย

### 3.1 Component Tree (เป้าหมาย)

```
DashboardView.frame
├── hero_card
│   ├── status_pill (พร้อมใช้งาน / กำลังเชื่อมต่อ / ไม่พร้อมใช้งาน)
│   └── status_subtitle
├── row_grid (2 columns)
│   ├── membership_card
│   │   ├── header: "สมาชิก" + tier_badge
│   │   ├── ชื่อผู้ใช้: {account_var}
│   │   ├── วันคงเหลือ: {entitlement_days_var}
│   │   └── วันหมดอายุ: {entitlement_expiry_var}
│   └── helper_device_card
│       ├── header: "เครื่องช่วย"
│       ├── ความโหลด: {download_speed_var}
│       ├── อัปโหลด: {upload_speed_var}
│       └── เวลาเชื่อมต่อ: {session_duration_var}
├── connection_diagram_card
│   ├── status_legend (3 dots: เขียว/เหลือง/แดง)
│   └── connection_diagram
│       ├── NetworkHopNode (เครื่องของคุณ, เขียว)
│       ├── NetworkHopConnector (1 ms)
│       ├── NetworkHopNode (NEKO PROXY, น้ำเงิน)
│       ├── NetworkHopConnector (8 ms)
│       ├── NetworkHopNode (TOKYO PROXY, ม่วง)
│       ├── NetworkHopConnector (18 ms)
│       └── NetworkHopNode (PSO2 SERVER, ชมพู)
├── statistics_row (4 columns)
│   ├── metric_card (เวลาเชื่อมต่อรวม)
│   ├── metric_card (เวลาแฝง)
│   ├── metric_card (ความโหลด)
│   └── metric_card (อัปโหลด)
└── guidance_card
    └── 💡 ระบบจะเชื่อมต่อ Tokyo Proxy อัตโนมัติ...
```

### 3.2 Data Flow

```
TelemetryState
  ├── local_ip, bangkok_proxy_ip, tokyo_proxy_ip, pso2_server_ip
  ├── per_hop_latency_ms (tuple of 3)
  ├── total_latency_ms
  ├── download_speed, upload_speed
  └── session_duration
       │
       ▼ (event: TelemetryUpdated)
AppWindow._on_telemetry(state)
  ├── update _local_ip_var.set(...)
  ├── update _hop1_latency_var.set(...)
  ├── update _hop2_latency_var.set(...)
  ├── update _hop3_latency_var.set(...)
  ├── update _ping_latency_var.set(...)
  └── ConnectionDiagram.update_hops(hops, latencies)
       │
       ▼
NetworkHopNode.label.configure(...)
NetworkHopConnector.text.configure(...)
```

### 3.3 Theme Tokens (เพิ่มใหม่)

```python
# theme.py extension
node_local: str = "#10B981"        # เขียว
node_local_surface: str = "#F0FDF4"
node_neko: str = "#3B82F6"         # น้ำเงิน
node_neko_surface: str = "#EFF6FF"
node_tokyo: str = "#8B5CF6"        # ม่วง
node_tokyo_surface: str = "#F5F3FF"
node_pso2: str = "#F84B93"         # ชมพู
node_pso2_surface: str = "#FCE7F0"
```

---

## 4. กลยุทธ์การแบ่ง Phase

แบ่งเป็น **6 phases** เรียงตาม dependency จาก foundational → visual → integration:

| Phase | ชื่อ | แตะ UI? | TDD? | Risk |
|---|---|---|---|---|
| 1 | Foundation (Data models + Theme tokens) | ❌ | ✅ | ต่ำ |
| 2 | Reusable components | ❌ (แยก) | ✅ | ต่ำ |
| 3 | Layout restructure | ✅ (DashboardView) | ✅ | กลาง |
| 4 | Connection Diagram | ✅ (Diagram) | ✅ | สูง |
| 5 | Statistics & Polish | ✅ (Metric cards) | ✅ | กลาง |
| 6 | Integration & Smoke | ✅ (End-to-end) | ✅ (manual) | กลาง |

**หลักการ:**
- แต่ละ phase ต้อง **test เขียวก่อน commit**
- แต่ละ phase มี **checkpoint** ให้ PM review
- ห้าม commit production code ก่อน test เขียว (TDD discipline)
- Truthful telemetry: ห้าม hardcode ค่าใน UI

---

## Phase 1 — Foundation: Data Models & Theme Tokens

**เป้าหมาย:** เตรียม data shape + theme tokens ให้พร้อม โดยไม่แตะ UI ที่มีอยู่

### 1.1 Domain models ใหม่

เพิ่มใน `launcher/src/neko_launcher/domain/models.py`:

```python
from dataclasses import dataclass
from enum import Enum

class HopConnectionState(Enum):
    SUCCESS = "success"
    CONNECTING = "connecting"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True)
class NetworkHop:
    label: str                          # "เครื่องของคุณ" / "NEKO PROXY" / etc.
    location: str | None                # "กรุงเทพฯ" / "โตเกียว" / None
    ip_address: str | None              # "192.168.1.100" or None
    connection_state: HopConnectionState
    icon_role: str                      # "computer" / "shield" / "tower" / "planet"

@dataclass(frozen=True)
class NetworkPath:
    hops: tuple[NetworkHop, ...]
    per_hop_latency_ms: tuple[int | None, ...]   # ความยาว = len(hops) - 1
```

**Design decisions:**
- ใช้ `tuple` แทน `list` เพื่อ immutability
- ใช้ `Enum` แทน string เพื่อ type safety
- ใช้ `int | None` (PEP 604) เพราะ Python 3.11

### 1.2 TelemetryState extension

ขยาย `launcher/src/neko_launcher/domain/telemetry.py`:

```python
@dataclass(frozen=True)
class TelemetryState:
    # ... existing fields ...
    local_ip: str | None = None
    bangkok_proxy_ip: str | None = None
    tokyo_proxy_ip: str | None = None
    pso2_server_ip: str | None = None
    per_hop_latency_ms: tuple[int | None, ...] = ()
```

### 1.3 Theme tokens ใหม่

ขยาย `PinkPalette` ใน `launcher/src/neko_launcher/ui/theme.py`:

```python
@dataclass(frozen=True)
class PinkPalette:
    # ... existing fields ...
    node_local: str = "#10B981"
    node_local_surface: str = "#F0FDF4"
    node_neko: str = "#3B82F6"
    node_neko_surface: str = "#EFF6FF"
    node_tokyo: str = "#8B5CF6"
    node_tokyo_surface: str = "#F5F3FF"
    node_pso2: str = "#F84B93"
    node_pso2_surface: str = "#FCE7F0"
```

### 1.4 Tests ที่ต้องเขียน (RED-GREEN-REFACTOR)

| ไฟล์ test | ครอบคลุม |
|---|---|
| `tests/test_network_hop_model.py` | dataclass immutability, enum coercion, NetworkPath invariant (per_hop_latency_ms length) |
| `tests/test_telemetry_state_extension.py` | ทุก field default = None, frozen=True |
| `tests/ui/test_palette_tokens.py` | ทุก node color เป็น hex (#RRGGBB), มี surface variant |

### 1.5 Checkpoint

- [ ] Models เขียนเสร็จ + test เขียว 100%
- [ ] TelemetryState extension + test เขียว
- [ ] Theme tokens + test เขียว
- [ ] ไม่มี import ใน UI layer ถูกแก้
- [ ] `pytest tests/test_network_hop_model.py tests/test_telemetry_state_extension.py tests/ui/test_palette_tokens.py` ผ่าน

---

## Phase 2 — Reusable Components

**เป้าหมาย:** สร้าง building blocks ใน `ui/components/` ใหม่ เพื่อให้ Phase 3-5 นำไปประกอบ

### 2.1 Component ใหม่ที่ต้องสร้าง

ใน `launcher/src/neko_launcher/ui/components/`:

#### `status_legend.py`
```python
def status_legend(parent) -> ctk.CTkFrame:
    """Render 3-dot legend (เขียว/เหลือง/แดง) + labels."""
    # Row of 3 mini-rows, each with:
    # - colored dot (CTkLabel 8x8 with fg_color=PALETTE.success/warning/danger)
    # - label text
```

#### `metric_card.py`
```python
class MetricCard:
    """Single stat tile with label + value (live-updatable)."""
    def __init__(
        self,
        parent,
        label: str,
        value_var: tk.StringVar,
        *,
        role: Literal["primary", "muted"] = "primary",
        icon: str | None = None,
    ) -> None: ...
```

#### `network_hop_node.py`
```python
class NetworkHopNode:
    """Render 1 node box in connection diagram."""
    def __init__(
        self,
        parent,
        hop: NetworkHop,
        *,
        accent_color: str,
        accent_surface: str,
    ) -> None:
        # Top: icon area (text-based)
        # Middle: label (bold)
        # Sub: location (smaller, muted)
        # Footer: IP address (very small, muted)
        # Border color = accent_color
        # Corner radius 12, padding 8
```

#### `network_hop_connector.py`
```python
class NetworkHopConnector:
    """Arrow + latency text between nodes."""
    def __init__(
        self,
        parent,
        latency_ms: int | None,
    ) -> None:
        # Render: "→ 1 ms" or "→ —" if None
```

#### `connection_diagram.py`
```python
class ConnectionDiagram:
    """Horizontal flow visualization of network path."""
    def __init__(self, parent) -> None: ...
    def update_path(self, path: NetworkPath | None) -> None:
        """Re-render diagram with new path. None = placeholder."""
```

### 2.2 Tests ที่ต้องเขียน

| ไฟล์ test | ครอบคลุม |
|---|---|
| `tests/ui/components/test_status_legend.py` | render 3 entries, correct colors mapping |
| `tests/ui/components/test_metric_card.py` | label/value render, value update via StringVar, role switching |
| `tests/ui/components/test_network_hop_node.py` | 4 variants (local/neko/tokyo/pso2), IP display, missing IP |
| `tests/ui/components/test_network_hop_connector.py` | latency value, "—" when None |
| `tests/ui/components/test_connection_diagram.py` | render 4 nodes + 3 connectors, update via `update_path`, empty state |

### 2.3 Design constraints

- Pure presentation — ไม่มี network IO, telemetry subscription, หรือ state
- ใช้ PinkPalette tokens เท่านั้น (ไม่ hardcode hex)
- ทุก component รับ `parent: ctk.CTkBaseClass` เป็น argument แรก
- ทุก component มี `.frame` หรือ `.widget` attribute สำหรับ parent reference

### 2.4 Checkpoint

- [ ] ทุก component render ผ่าน test
- [ ] ไม่มี network/IO ใน component (pure presentation)
- [ ] ทุก component ใช้ PinkPalette tokens เท่านั้น
- [ ] `pytest tests/ui/components/` ผ่าน 100%

---

## Phase 3 — Layout Restructure

**เป้าหมาย:** เปลี่ยน composition ของ `DashboardView` ให้รองรับ 2-column header + diagram + stats

### 3.1 Window size decision (PM checkpoint ต้องอนุมัติ)

**Option A (Landscape 720×520):**
- ขยาย window เป็น landscape
- Diagram render horizontal (ตามภาพ)
- ใช้ `fit_landscape_window()` ใหม่ใน `window_scaling.py`
- **ข้อดี:** ตรงกับ design mockup
- **ข้อเสีย:** เปลี่ยน behavior เดิม (portrait)

**Option B (Portrait extended 440×680):**
- คง portrait แต่ stack diagram เป็น vertical
- ใช้ `fit_portrait_window()` เดิม
- **ข้อดี:** backward-compatible
- **ข้อเสีย:** diagram ไม่ตรงกับภาพ

**Option C (Responsive):**
- Detect width, render accordingly
- **ข้อดี:** flexible
- **ข้อเสีย:** ซับซ้อนกว่า

**Default proposed: Option A** เพราะ diagram ในภาพเป็น horizontal และ metrics เป็น 4-column

### 3.2 DashboardView structure ใหม่

ใน `launcher/src/neko_launcher/ui/views/dashboard_view.py`:

```python
class DashboardView:
    def __init__(
        self,
        parent,
        root,
        *,
        # existing StringVars
        status_title_var,
        status_subtitle_var,
        account_var,
        entitlement_days_var,
        entitlement_expiry_var,
        download_speed_var,
        upload_speed_var,
        session_duration_var,
        # NEW StringVars
        local_ip_var,
        bangkok_proxy_ip_var,
        tokyo_proxy_ip_var,
        pso2_server_ip_var,
        hop1_latency_var,
        hop2_latency_var,
        hop3_latency_var,
        ping_latency_var,
    ) -> None:
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")

        # 1. hero_card (existing)
        self._build_hero()

        # 2. row_grid (2 columns: membership + helper_device)
        self._build_row_grid()

        # 3. connection_diagram_card
        self._build_connection_diagram()

        # 4. statistics_row (4 columns)
        self._build_statistics_row()

        # 5. guidance_card (existing)
        self._build_guidance()
```

### 3.3 AppWindow changes

ใน `launcher/src/neko_launcher/ui/app_window.py`:

```python
# เพิ่ม StringVars ใหม่
self._local_ip = tk.StringVar(value="")
self._bangkok_proxy_ip = tk.StringVar(value="")
self._tokyo_proxy_ip = tk.StringVar(value="")
self._pso2_server_ip = tk.StringVar(value="")
self._hop1_latency = tk.StringVar(value="—")
self._hop2_latency = tk.StringVar(value="—")
self._hop3_latency = tk.StringVar(value="—")
self._ping_latency = tk.StringVar(value="—")

# ส่งเข้า DashboardView constructor
self._dashboard_view = DashboardView(
    self._content,
    self.root,
    # ... existing ...
    local_ip_var=self._local_ip,
    # ... new ...
)
```

### 3.4 Tests ที่ต้องเขียน/อัปเดต

| ไฟล์ test | ครอบคลุม |
|---|---|
| `tests/ui/test_dashboard_view.py` (อัปเดต) | 2-column row exists, helper_device_card present, connection_diagram_card present, statistics_row has 4 metric cards |
| `tests/ui/test_app_window.py` (อัปเดต) | StringVar ใหม่ครบ, backward-compat |

### 3.5 Checkpoint

- [ ] Window size decision บันทึกใน `AI_PROJECT_HANDOFF.md`
- [ ] DashboardView render ใหม่ผ่าน test
- [ ] AppWindow backward-compatible (existing StringVars ยังทำงาน)
- [ ] `pytest tests/ui/test_dashboard_view.py tests/ui/test_app_window.py` ผ่าน

---

## Phase 4 — Connection Diagram (Largest Phase)

**เป้าหมาย:** ส่วนที่ซับซ้อนที่สุด — visualize 4-node network path พร้อม latency ระหว่าง hops

### 4.1 Diagram renderer logic

ใน `ConnectionDiagram.update_path(path: NetworkPath | None)`:

```python
def update_path(self, path: NetworkPath | None) -> None:
    # Clear existing children
    for widget in self.frame.winfo_children():
        widget.destroy()

    if path is None or not path.hops:
        # Render placeholder
        placeholder = ctk.CTkLabel(
            self.frame,
            text="ไม่มีข้อมูลเส้นทาง",
            text_color=PALETTE.text_muted,
        )
        placeholder.pack(expand=True)
        return

    # Render horizontal flow
    for i, hop in enumerate(path.hops):
        # Add node
        node = NetworkHopNode(self.frame, hop, ...)
        node.frame.pack(side="left", padx=4, pady=8)

        # Add connector if not last
        if i < len(path.hops) - 1:
            latency = path.per_hop_latency_ms[i] if i < len(path.per_hop_latency_ms) else None
            connector = NetworkHopConnector(self.frame, latency)
            connector.frame.pack(side="left", padx=2)
```

### 4.2 Data source wiring

ใน `app_window.py`:

```python
def _on_telemetry_updated(self, state: TelemetryState) -> None:
    # Update IP vars
    self._local_ip.set(state.local_ip or "ไม่พร้อมใช้งาน")
    self._bangkok_proxy_ip.set(state.bangkok_proxy_ip or "ไม่พร้อมใช้งาน")
    self._tokyo_proxy_ip.set(state.tokyo_proxy_ip or "ไม่พร้อมใช้งาน")
    self._pso2_server_ip.set(state.pso2_server_ip or "ไม่พร้อมใช้งาน")

    # Update latency vars
    per_hop = state.per_hop_latency_ms
    self._hop1_latency.set(f"{per_hop[0]} ms" if len(per_hop) > 0 and per_hop[0] is not None else "—")
    self._hop2_latency.set(f"{per_hop[1]} ms" if len(per_hop) > 1 and per_hop[1] is not None else "—")
    self._hop3_latency.set(f"{per_hop[2]} ms" if len(per_hop) > 2 and per_hop[2] is not None else "—")

    # Compute ping (last hop or aggregate)
    if per_hop and per_hop[-1] is not None:
        self._ping_latency.set(f"{per_hop[-1]} ms")
    else:
        self._ping_latency.set("—")

    # Build NetworkPath and update diagram
    path = NetworkPath(
        hops=(
            NetworkHop("เครื่องของคุณ", None, state.local_ip, HopConnectionState.SUCCESS, "computer"),
            NetworkHop("NEKO PROXY", "กรุงเทพฯ", state.bangkok_proxy_ip, ..., "shield"),
            NetworkHop("TOKYO PROXY", "โตเกียว", state.tokyo_proxy_ip, ..., "tower"),
            NetworkHop("PSO2 SERVER", "Japan", state.pso2_server_ip, ..., "planet"),
        ),
        per_hop_latency_ms=per_hop,
    )
    self._dashboard_view.connection_diagram.update_path(path)
```

### 4.3 Truthfulness check (memory rule)

- ทุก IP ที่แสดงต้องมาจาก telemetry จริง
- ถ้า telemetry ยังไม่มีค่า → แสดง "ไม่พร้อมใช้งาน" (truthful)
- Latency ที่ยังไม่วัด → "—" (ไม่ใช่ 0)
- ห้ามแสดง "127.0.0.1" หรือ IP placeholder อื่น — ถ้าไม่มีค่า = "ไม่พร้อมใช้งาน"

### 4.4 Tests ที่ต้องเขียน

| ไฟล์ test | ครอบคลุม |
|---|---|
| `tests/ui/components/test_connection_diagram.py` (ขยาย) | update_path(None) → placeholder, partial latency → "—", full data → ครบ |
| `tests/ui/test_app_window.py` (integration) | mock TelemetryUpdated → verify diagram updates |
| `tests/test_telemetry_truthfulness.py` (ใหม่) | ทุก IP/latency ที่แสดงต้องสะท้อน telemetry state |

### 4.5 Checkpoint

- [ ] Diagram render ถูกต้องใน 4 states (empty/partial/full/error)
- [ ] No hardcoded values — ทุกอย่างจาก telemetry
- [ ] No regression ใน existing telemetry tests
- [ ] `pytest tests/ui/components/test_connection_diagram.py tests/test_telemetry_truthfulness.py` ผ่าน

---

## Phase 5 — Statistics & Polish

**เป้าหมาย:** 4-column metrics bar + visual polish (icons, empty states, spacing)

### 5.1 Metric card wiring

ใน `DashboardView._build_statistics_row()`:

```python
def _build_statistics_row(self) -> None:
    row = ctk.CTkFrame(self.frame, fg_color="transparent")
    row.pack(fill="x", padx=8, pady=4)
    row.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="metric")

    # Card 1: เวลาเชื่อมต่อรวม
    MetricCard(
        row,
        label="เวลาเชื่อมต่อรวม",
        value_var=self._session_duration_var,
        role="primary",
    ).frame.grid(row=0, column=0, padx=4, sticky="ew")

    # Card 2: เวลาแฝง (Ping)
    MetricCard(
        row,
        label="เวลาแฝง (Ping)",
        value_var=self._ping_latency_var,
        role="primary",
    ).frame.grid(row=0, column=1, padx=4, sticky="ew")

    # Card 3: ความโหลด
    MetricCard(
        row,
        label="ความโหลด",
        value_var=self._download_speed_var,
        role="muted",
    ).frame.grid(row=0, column=2, padx=4, sticky="ew")

    # Card 4: อัปโหลด
    MetricCard(
        row,
        label="อัปโหลด",
        value_var=self._upload_speed_var,
        role="muted",
    ).frame.grid(row=0, column=3, padx=4, sticky="ew")
```

### 5.2 Iconography

ใช้ text-based icons (emoji) เพื่อหลีกเลี่ยน asset bloat:

| Metric | Icon |
|---|---|
| เวลาเชื่อมต่อรวม | ⏱ |
| เวลาแฝง (Ping) | 📡 |
| ความโหลด | ⬇ |
| อัปโหลด | ⬆ |

Fallback: ถ้า emoji render ไม่ consistent บน Windows → ใช้ text-only label (ไม่มี icon)

### 5.3 Empty states

- เมื่อ metric ไม่มีค่า → แสดง "ไม่พร้อมใช้งาน" (already in StringVar defaults)
- Diagram empty state → "ไม่มีข้อมูลเส้นทาง" placeholder card

### 5.4 Visual polish

- Card spacing ใช้ `pady=4` consistent
- Border radius 10-12 across all cards
- Section headers ใช้ `weight="bold"` size 13
- Status pill, badges ใช้ surface variant ของ node color
- ใช้ Sarabun font ทุกที่ (existing)

### 5.5 Tests

| ไฟล์ test | ครอบคลุม |
|---|---|
| `tests/ui/components/test_metric_card.py` (ขยาย) | value role switching, empty value handling, icon presence |
| Visual smoke test (manual) | Screenshot comparison กับ design mockup |

### 5.6 Checkpoint

- [ ] ทุก metric card แสดงถูกต้อง
- [ ] Empty states ครบทุก card
- [ ] Screenshot เทียบกับ design mockup (manual PM review)

---

## Phase 6 — Integration & Smoke

**เป้าหมาย:** ทดสอบ end-to-end ในสภาพแวดล้อมจริง

### 6.1 Test suites ที่ต้องรัน

```bash
# UI unit tests
pytest tests/ui/ -v

# Controller integration
pytest tests/test_controller.py -v

# Telemetry truthfulness
pytest tests/test_telemetry_privacy.py -v

# Full E2E harness
pytest tests/test_final_windows_e2e_harness.py -v

# All tests
pytest tests/ -v
```

### 6.2 Live verification (mandatory)

```bash
# Run in dev mode
cd launcher
python -m neko_launcher

# Manual checks:
# 1. Login ด้วย test account (tester / รหัสผ่าน)
# 2. Verify ทุก card แสดงถูกต้อง
# 3. Verify telemetry update เมื่อ proxy start
# 4. Verify connection diagram แสดง 4 nodes
# 5. Verify status pill เปลี่ยนสีตาม state
# 6. Screenshot final state เทียบกับ design mockup
```

### 6.3 PyInstaller build verification

```bash
cd launcher
pyinstaller NekoLauncher.spec

# Run built exe
./dist/NekoLauncher.exe

# Verify:
# - Font (Sarabun) render ถูกต้อง
# - Rounded window shape ถูกต้อง
# - Thai text render ถูกต้อง
# - ทุก card แสดง
# - Telemetry update live
```

### 6.4 Regression check

- [ ] `test_dashboard_view.py` เขียว
- [ ] `test_status_presentation.py` เขียว
- [ ] `test_app_window.py` เขียว
- [ ] ไม่มี import cycle ใหม่
- [ ] ไม่มี hardcoded hex นอก PinkPalette
- [ ] ไม่มี emoji ใน production code ที่อาจ render ไม่ consistent

### 6.5 Documentation sync

- [ ] อัปเดต `Asset/` ด้วย screenshot final (manual)
- [ ] อัปเดต `E:\Github\Project manager\AI_PROJECT_HANDOFF.md` ด้วย phase completion status
- [ ] อัปเดต `E:\Github\Project manager\PROJECT_HISTORY_LOG.md` (log entry)
- [ ] อัปเดต `NekoLauncher.spec` ถ้ามี asset ใหม่

### 6.6 Checkpoint

- [ ] All tests เขียว
- [ ] Live verification screenshot ผ่าน
- [ ] PyInstaller build run สำเร็จ
- [ ] Documentation sync เสร็จ
- [ ] PM sign-off

---

## 5. Risk Register

| # | Risk | Probability | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Window width เดิม (~440px) ไม่พอสำหรับ diagram | สูง | กลาง | PM ตัดสิน Option A/B/C ใน Phase 3.1 |
| R2 | Telemetry state ไม่มี hop-level latency | กลาง | สูง | ใช้ aggregate ใน Phase 4 เป็น fallback, TODO backlog |
| R3 | Emoji icon render ไม่ consistent บน Windows | กลาง | ต่ำ | เตรียม text-only fallback ใน Phase 5.2 |
| R4 | Existing tests regress เพราะ layout เปลี่ยน | สูง | สูง | TDD discipline + run full test suite ทุก phase |
| R5 | PyInstaller build ใหญ่ขึ้นจาก asset ใหม่ | ต่ำ | ต่ำ | ใช้ text/emoji icons แทน PNG icons |
| R6 | IP ของ proxy/server ไม่มีใน telemetry (backend limitation) | กลาง | กลาง | แสดง "ไม่พร้อมใช้งาน" (truthful) แทน hardcode |
| R7 | Test ของ connection diagram ต้องใช้ tk root — flaky test | กลาง | ต่ำ | ใช้ fixture pattern เดียวกับ test_dashboard_view.py |
| R8 | PM scope creep — เพิ่ม feature ระหว่าง phase | สูง | กลาง | ใช้ Out of Scope section + checkpoint review |

---

## 6. Open Questions for PM

1. **Window size:** A (landscape 720×520) / B (portrait extended 440×680) / C (responsive)? — **Default proposed: A**
2. **PSO2 server IP:** hardcode constant หรืออ่านจาก config? — **Proposed: hardcode constant ใน `config.py`**
3. **Per-hop latency source:** aggregate จาก telemetry เดียว หรือต้องเพิ่ม measurement ใหม่? — **Proposed: aggregate ก่อน, เพิ่ม measurement เป็น Phase 7+**
4. **Phase priority:** ถ้าเวลาจำกัด ควรตัด Phase ใด (4 = diagram, 5 = polish)? — **Proposed: ตัด 5 ก่อน ถ้าจำเป็น**
5. **Backport target:** Phase 1-3 เข้า main+beta หรือ feature branch ใหม่? — **Proposed: feature branch `feature/dashboard-redesign`**
6. **Icon library:** ใช้ emoji หรือ PNG icons? — **Proposed: emoji (zero asset cost)**
7. **Backward compatibility:** ถ้า telemetry ไม่มี hop latency → diagram แสดง "—" หรือซ่อน connector? — **Proposed: แสดง "—"**

---

## 7. Out of Scope (deferred)

- Animation/transition ระหว่าง state changes — **Phase 7+**
- Custom font/typography (ยังใช้ Sarabun) — **N/A**
- Dark mode variant (palette เป็น light mode เท่านั้น) — **Phase 8+**
- Localization ภาษาอื่น (UI เป็น Thai + English เท่านั้น) — **N/A**
- Interactive elements ใน diagram (เช่น click node = details) — **Phase 7+**
- Historical telemetry chart — **Phase 7+**
- Custom proxy IP detection (currently relies on telemetry) — **Phase 8+**
- Network hop editing (add/remove custom hops) — **Out of scope**
- Real-time latency graph — **Out of scope**

---

## 8. Success Criteria

แผนสำเร็จเมื่อ:

1. ✅ ทุก phase มี checkpoint ผ่านครบ (6/6)
2. ✅ Screenshot final state ตรงกับ design mockup ≥ 90% (visual subjective)
3. ✅ ทุก test suite เขียว (`pytest tests/` exit 0)
4. ✅ PyInstaller build run สำเร็จบน Windows (`dist/NekoLauncher.exe` boot ได้)
5. ✅ Documentation sync ครบ (HANDOFF + HISTORY_LOG)
6. ✅ PM อนุมัติใน checkpoint สุดท้าย
7. ✅ Truthful telemetry — ไม่มี hardcoded IP/latency ใน UI
8. ✅ Backward-compatible — existing StringVars ยังทำงาน
9. ✅ ไม่มี regression ใน existing test suites

---

## 9. ไฟล์ที่คาดว่าจะถูกแก้ไข

### Production code

| ไฟล์ | Action | Phase |
|---|---|---|
| `launcher/src/neko_launcher/domain/models.py` | เพิ่ม NetworkHop, NetworkPath, HopConnectionState | 1 |
| `launcher/src/neko_launcher/domain/telemetry.py` | ขยาย TelemetryState ด้วย IP/latency fields | 1 |
| `launcher/src/neko_launcher/ui/theme.py` | ขยาย PinkPalette ด้วย node tokens | 1 |
| `launcher/src/neko_launcher/ui/components/status_legend.py` | สร้างใหม่ | 2 |
| `launcher/src/neko_launcher/ui/components/metric_card.py` | สร้างใหม่ | 2 |
| `launcher/src/neko_launcher/ui/components/network_hop_node.py` | สร้างใหม่ | 2 |
| `launcher/src/neko_launcher/ui/components/network_hop_connector.py` | สร้างใหม่ | 2 |
| `launcher/src/neko_launcher/ui/components/connection_diagram.py` | สร้างใหม่ | 2 |
| `launcher/src/neko_launcher/ui/views/dashboard_view.py` | refactor composition ใหม่ | 3, 4, 5 |
| `launcher/src/neko_launcher/ui/app_window.py` | เพิ่ม StringVars + telemetry handler | 3, 4 |
| `launcher/src/neko_launcher/ui/platform/window_scaling.py` | เพิ่ม `fit_landscape_window()` (ถ้า Option A) | 3 |

### Test code

| ไฟล์ | Action | Phase |
|---|---|---|
| `launcher/tests/test_network_hop_model.py` | สร้างใหม่ | 1 |
| `launcher/tests/test_telemetry_state_extension.py` | สร้างใหม่ | 1 |
| `launcher/tests/ui/test_palette_tokens.py` | สร้างใหม่ | 1 |
| `launcher/tests/ui/components/test_status_legend.py` | สร้างใหม่ | 2 |
| `launcher/tests/ui/components/test_metric_card.py` | สร้างใหม่ | 2 |
| `launcher/tests/ui/components/test_network_hop_node.py` | สร้างใหม่ | 2 |
| `launcher/tests/ui/components/test_network_hop_connector.py` | สร้างใหม่ | 2 |
| `launcher/tests/ui/components/test_connection_diagram.py` | สร้างใหม่ | 2, 4 |
| `launcher/tests/ui/test_dashboard_view.py` | อัปเดต | 3 |
| `launcher/tests/ui/test_app_window.py` | อัปเดต | 3, 4 |
| `launcher/tests/test_telemetry_truthfulness.py` | สร้างใหม่ | 4 |

### Documentation

| ไฟล์ | Action | Phase |
|---|---|---|
| `E:\Github\Project manager\AI_PROJECT_HANDOFF.md` | อัปเดต | 6 |
| `E:\Github\Project manager\PROJECT_HISTORY_LOG.md` | log entry | 6 |
| `Asset/dashboard-final-screenshot.png` | สร้างใหม่ (manual) | 6 |

### Build & Spec

| ไฟล์ | Action | Phase |
|---|---|---|
| `launcher/NekoLauncher.spec` | อัปเดต (ถ้ามี asset ใหม่) | 6 |

---

## 10. แผนสำรอง (Fallback)

ถ้าเกิด blocker ที่ทำให้ไม่สามารถทำ Phase 4 (Connection Diagram) ได้:

**Fallback Phase 4':** แสดง diagram แบบ simplified
- ใช้ vertical layout (ไม่ใช่ horizontal)
- ไม่มี per-hop latency
- ใช้ 1 aggregate latency แทน
- ลด components ที่ต้องสร้าง

**Fallback Phase 5':** Polish จำกัด
- ไม่มี emoji icons (text-only)
- spacing/padding ใช้ existing tokens

---

**สถานะ:** Draft v1.0 (2026-08-28)
**ผู้จัดทำ:** PM
**Reviewer:** TBD
**Next action:** PM review + Phase 1 kickoff
