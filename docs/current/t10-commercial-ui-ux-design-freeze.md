# NEKO FAMILY PROXY — T10A COMMERCIAL LAUNCHER UI/UX DESIGN FREEZE

```text
DOCUMENT:                       docs/current/t10-commercial-ui-ux-design-freeze.md
STATUS:                         FROZEN
PHASE:                          T10A
AUTHORITY:                      docs/current/t10-commercial-ui-ux-design-freeze.md
BASE_SHA:                       8d4543553622f927d2d62dd054715a6523d82698
BASE_BRANCH:                    main
BRANCH:                         feature/t10-commercial-launcher-ui
SUCCESSOR:                      T10B (Commercial Launcher UI Implementation)
LAST_UPDATED:                   2026-08-18
```

---

## 1. Executive Product Direction

The commercial Neko Family Proxy Launcher must strictly transition from a **developer/customer control utility** into a **read-only customer dashboard with a separate Settings window**.

```text
┌─────────────────────────────────────────────────────────────┐
│                      PRODUCT PRINCIPLE                      │
├─────────────────────────────────────────────────────────────┤
│ MAIN_WINDOW       = READ-ONLY CUSTOMER STATUS DASHBOARD     │
│ SETTINGS_WINDOW   = ALL USER CONFIGURATION & MANAGEMENT     │
│ DIAGNOSTICS       = SUPPORT & TROUBLESHOOTING IN SETTINGS   │
│ MAIN_CONTROLS     = NONE (Only Gear ⚙ and Window Chrome)    │
│ MAIN_ACTIONS      = NONE (Automatic proxy connection on PSO2)│
└─────────────────────────────────────────────────────────────┘
```

The typical customer must never encounter raw network internals (such as *Named Pipes, SOCKS endpoints, redirectors, TCP connections, or raw packet counters*) on the primary screen. All technical observability tools remain fully accessible to support staff and power users under **Settings > Diagnostics**.

---

## 2. Current UI Source Map

| Component / File | Current Responsibility | Proposed T10 Target |
| :--- | :--- | :--- |
| [`app_window.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/app_window.py) | Root Tk window, view switcher, event loop, process polling, modal dialogs, debug dialog | Pure UI Composition Root, window lifecycle, background event dispatch, Settings window lifecycle owner |
| [`theme.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/theme.py) | Theme colors (`PinkPalette`), font family (`Sarabun`), font loading | Extended semantic palette tokens (Success, Warning, Danger, Surface, Border) |
| [`views/auth_view.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/views/auth_view.py) | Login and Registration tabs, entry fields, validation | Preserved in T10A/T10B (Pre-auth stage) |
| [`views/recovery_view.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/views/recovery_view.py) | Account recovery code verification and password reset | Preserved in T10A/T10B (Pre-auth stage) |
| [`views/dashboard_view.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/views/dashboard_view.py) | Monolithic post-login panel containing account, coupon, proxy status, telemetry, game path, Tweaker launch | Refactored into pure read-only customer status dashboard; all configuration moved to Settings |
| [`components/buttons.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/components/buttons.py) | Primary button, secondary button, card frame, field label, icon entry | Reused across Main and Settings pages |
| [`components/toast.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/components/toast.py) | Transient floating notifications | Reused for feedback across Main and Settings |
| [`platform/window_chrome.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/platform/window_chrome.py) | Win32 DWM rounded corners, borderless dragging, title styling | Reused for Main and Settings windows |
| [`platform/window_scaling.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/platform/window_scaling.py) | DPI calculation, window auto-fit and centering | Reused with dedicated geometry calculation for Settings |
| [`platform/system_tray.py`](file:///D:/Github/Neko-Family-Proxy/launcher/src/neko_launcher/ui/platform/system_tray.py) | Tray icon and background restore/close queue | Preserved; toggle configuration exposed in Settings > General |

---

## 3. Current Business Logic Bindings & Ownership Map

Every UI control, state variable, and backend binding has been audited:

| Item / Action | UI Owner | State Owner | Action Owner | Service / Controller Call | Persistence | Can Move to Settings |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Root Window** | `AppWindow` | `AppWindow` | `AppWindow.close()` | `LauncherService.shutdown()` | None | **NO** (Root lifecycle) |
| **Dashboard** | `DashboardView` | `AppState` / Tk Vars | `AppWindow` | Multiple | None | **CONDITIONAL** (Read-only on Main, Controls in Settings) |
| **Login** | `AuthView` | `AppState.auth_status` | `AppWindow._login()` | `LauncherService.sign_in()` | Keyring / SecureStore | **NO** (Pre-auth) |
| **Recovery** | `RecoveryView` | `AppState.auth_status` | `AppWindow._verify_recovery_code()` | `LauncherService.verify_recovery_code()` | Memory-only session | **NO** (Pre-auth) |
| **Password Dialog** | `open_password_dialog` | `tk.StringVar` | `AppWindow._change_password()` | `LauncherService.change_password()` | Supabase Auth | **YES** (Move to Settings > Account) |
| **Debug Dialog** | `AppWindow._debug_dialog` | `CoreDiagnosticsRecorder` | `AppWindow._show_debug_dialog()` | `diagnostics.snapshot()` | Local log files | **YES** (Move to Settings > Diagnostics) |
| **System Tray** | `SystemTrayManager` | `AppWindow._tray_manager` | `drain_tray_actions()` | Native tray loop | None | **NO** (Integration stays, config in Settings) |
| **Game Path** | `DashboardView` | `AppWindow._game_path` | `AppWindow._choose_game()` | File dialog + text write | `%LOCALAPPDATA%/NEKO FAMILY/tweaker.path` | **YES** (Move to Settings > PSO2) |
| **Auto-Launch** | `DashboardView` | `AppWindow._auto_launch` | `AppWindow._auto_launch_tweaker()` | `LauncherService.launch_tweaker()` | Memory default | **YES** (Move to Settings > PSO2) |
| **Coupon Redeem** | `DashboardView` | `AppWindow._coupon_code` | `AppWindow._redeem_coupon()` | `LauncherService.redeem_coupon()` | Supabase DB RPC | **YES** (Move to Settings > Subscription) |
| **Logout** | `DashboardView` | `AppState.auth_status` | `AppWindow._sign_out()` | `LauncherService.sign_out()` | Keyring deletion | **YES** (Move to Settings > Account) |
| **Password Change** | `DashboardView` | `AppWindow._new_password` | `AppWindow._change_password()` | `LauncherService.change_password()` | Supabase Auth | **YES** (Move to Settings > Account) |
| **Game Launch** | `DashboardView` | `AppState.game_status` | `AppWindow._launch_game()` | `LauncherService.launch_tweaker()` | None | **YES** (Move to Settings > PSO2) |
| **Game Detection** | `AppWindow` | `AppState.game_process_running`| `AppWindow._poll_game_process()`| `is_any_process_running()` | None | **NO** (Background loop stays in AppWindow) |
| **Core State** | `AppWindow` | `AppState.proxy_status` | `ApplicationController.dispatch()` | `AuthorizedProxyGateway` | None | **NO** (Projected to UI) |
| **Telemetry State**| `AppWindow` | `TelemetryState` | `NamedPipeCoreTelemetryClient` | `\\.\pipe\NekoProxyCoreTelemetry` | None | **NO** (Projected to UI) |
| **Entitlement** | `AppWindow` | `AppState.entitlement` | `LauncherService` | `SupabaseGateway.get_user_entitlement()` | Supabase DB | **YES** (Summary on Main, details in Settings) |
| **Account Info** | `AppWindow` | `AppState.user_email` | `LauncherService` | `SupabaseGateway` | Keyring | **YES** (Summary on Main, details in Settings) |
| **Theme** | `neko_launcher.ui.theme`| `ctk.ThemeManager` | Static module | CustomTkinter + Win32 GDI | None | **NO** (Theme tokens stay central) |
| **Window Sizing** | `window_scaling.py` | `AppWindow._window_size` | `fit_portrait_window()` | Win32 DPI Tracker | None | **NO** (Main is portrait, Settings is landscape) |
| **Window Chrome** | `window_chrome.py` | Win32 HWND | `WindowDragHandler` | `ctypes.windll.dwmapi` | None | **NO** (Shared platform helper) |

---

## 4. Main Dashboard Information Architecture

Following successful login or session restoration, the Main Window displays a clean, vertical status card hierarchy with **zero configuration forms or developer controls**:

```text
┌─────────────────────────────────────────────────────────────┐
│ NEKO FAMILY PSO2NGS                                   ⚙ ─ × │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                   ●  พ ร้ อ ม ใ ช้ ง า น                    │
│                      กำลังรอเปิด PSO2                       │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│  MEMBERSHIP                                                 │
│  👤 zalovenext                                    NEKO PRO  │
│  ⏳ เหลือ 72 วัน (หมดอายุ 28 ต.ค. 2026 14:30)               │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│  NETWORK                                                    │
│  📶 Ping                   -- ms                            │
│  ▼ Download               0 KB/s                            │
│  ▲ Upload                 0 KB/s                            │
│  ⏱ Connected              00:00:00                          │
│                                                             │
│ ─────────────────────────────────────────────────────────── │
│                                                             │
│  💡 ระบบจะเชื่อมต่อ Tokyo Proxy อัตโนมัติเมื่อเปิดเกม PSO2   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Main Window Content Breakdown
1. **Brand & Chrome Header**:
   - Neko Family Mascot & Logo
   - Product title: `NEKO FAMILY PROXY PSO2NGS`
   - Settings Gear Button (`⚙`) to open Settings Window
   - Native Window Minimize (`—`) and Close (`×`)
2. **Hero Connection Status Card**:
   - Status Indicator Pill (e.g. `● พร้อมใช้งาน`, `● กำลังเชื่อมต่อ...`, `● เชื่อมต่อแล้ว`, `● หมดอายุ`)
   - Human-friendly subtitle description
3. **Membership Card**:
   - Username badge
   - Membership tier badge (`NEKO PRO` / `ACTIVE`)
   - Remaining active days and formatted expiry timestamp
4. **Network Card**:
   - Latency (Ping in ms)
   - Real-time Download speed (KB/s or MB/s)
   - Real-time Upload speed (KB/s or MB/s)
   - Active session duration (`HH:MM:SS`)
5. **Passive Customer Guidance Footer**:
   - Reassuring guidance note: *"ระบบจะเชื่อมต่ออัตโนมัติเมื่อตรวจพบเกม PSO2"*
   - Version tag: `v1.0.0`

---

## 5. Settings Information Architecture

The Settings window is a standalone, single-instance top-level desktop window (`CTkToplevel`) structured with a left-hand navigation sidebar and right-hand page content:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  ⚙ การตั้งค่า (Settings)                                               ─ × │
├────────────────────────┬─────────────────────────────────────────────────────┤
│  🔍 ค้นหาการตั้งค่า...    │  ACCOUNT SETTINGS                                   │
│                        │                                                     │
│  📌 ทั่วไป (General)     │  ข้อมูลบัญชี                                         │
│  👤 บัญชี (Account)     │  ชื่อผู้ใช้: zalovenext                             │
│  💎 สมาชิก (Subscription)│  สถานะ: ใช้งานได้ (Active)                          │
│  🎮 PSO2               │                                                     │
│  🛠 PSO2 Tweaker       │  เปลี่ยนรหัสผ่าน                                     │
│  🌐 การเชื่อมต่อ        │  [ รหัสผ่านใหม่ .................... ]               │
│  🎨 การแสดงผล           │  [ ยืนยันรหัสผ่านใหม่ .............. ]               │
│  🔔 การแจ้งเตือน        │  [ บันทึกรหัสผ่านใหม่ ]                             │
│  🩺 การวินิจฉัย         │                                                     │
│  ℹ️ เกี่ยวกับ (About)    │  [ ออกจากระบบ (Sign Out) ]                          │
└────────────────────────┴─────────────────────────────────────────────────────┘
```

### Approved Settings Hierarchy
1. **GENERAL (`ทั่วไป`)**
   - เปิดพร้อม Windows (Start with Windows)
   - ย่อเข้า System Tray (Minimize to System Tray on close/minimize)
   - เชื่อมต่ออัตโนมัติ (Auto connect when game starts)
2. **ACCOUNT (`บัญชีผู้ใช้`)**
   - ชื่อผู้ใช้ (Username / User identifier)
   - เปลี่ยนรหัสผ่าน (Change password form with validation)
   - ออกจากระบบ (Sign out / Invalidate session)
3. **SUBSCRIPTION (`วันใช้งาน & สมาชิก`)**
   - วันคงเหลือ (Remaining days)
   - วันหมดอายุ (Expiry date & time)
   - ช่องกรอกคูปอง (Coupon code entry)
   - ปุ่มเติมวันใช้งาน (Redeem coupon action)
4. **PSO2 (`เกม PSO2`)**
   - ที่อยู่ไฟล์เกม (Game executable path / `pso2.exe` or `Tweaker.exe`)
   - ตรวจจับอัตโนมัติ (Auto process detection status)
   - พฤติกรรมการเปิดเกม (Launch behavior / Auto-launch on login)
5. **PSO2 TWEAKER (`PSO2 Tweaker`)**
   - ที่อยู่ไฟล์ Tweaker (Tweaker.exe Path selector)
   - ตัวเลือกเปิดเกมที่รองรับ (Launch Tweaker shortcut)
6. **CONNECTION (`การเชื่อมต่อ`)**
   - โซนเซิร์ฟเวอร์ (Region: `Japan (Tokyo) - AWS Lightsail`)
   - โหมดการเชื่อมต่อ (Proxy mode: `High-Speed Direct Tunnel`)
   - *Security Rule: Never display internal IPs, port 8388, Shadowsocks keys, or ciphers.*
7. **APPEARANCE (`การแสดงผล`)**
   - ธีมสี (Theme: `Neko Pink (Light)`)
   - เริ่มต้นแบบย่อหน้าต่าง (Start minimized)
8. **NOTIFICATIONS (`การแจ้งเตือน`)**
   - แจ้งเตือนเมื่อเชื่อมต่อสำเร็จ (Connection notification)
   - แจ้งเตือนการปิดปรับปรุงเซิร์ฟเวอร์ (Maintenance notice)
9. **DIAGNOSTICS (`การวินิจฉัย & เครื่องมือสนับสนุน`)**
   - สถานะ Core & Pipes (Core status, Control Pipe, Telemetry Pipe)
   - สถิติเครือข่ายเชิงลึก (Active TCP connections, DNS query count, Raw RX/TX bytes)
   - บันทึกการทำงาน (Live sanitized log viewer)
   - เปิดโฟลเดอร์ Log (Open logs directory in Windows Explorer)
   - โหมดทดสอบระบบ (Debug Mode retry action)
10. **ABOUT (`เกี่ยวกับโปรแกรม`)**
    - เวอร์ชันโปรแกรม (Launcher version)
    - เวอร์ชัน Core Engine (Core version)
    - หมายเลข Build (Build / Commit reference)
    - ลิขสิทธิ์ (Copyright © 2026 NEKO FAMILY)

---

## 6. Settings Capability Matrix

| Setting Item | Current Runtime Support | Source Location | T10 Implementation Class | Risk | Business Logic Change |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **เปิดพร้อม Windows** | Not implemented | OS Registry | `REQUIRES_NEW_OS_INTEGRATION` / `DEFER_RECOMMENDED` | Medium | NO |
| **ย่อเข้า System Tray** | Runtime tray exists, setting unpersisted | `system_tray.py` | `REQUIRES_NEW_PERSISTENCE` | Low | NO |
| **เชื่อมต่ออัตโนมัติ** | Implemented & active | `app_window.py:964` | `EXISTING_BEHAVIOR_NO_SETTINGS_UI` | Low | NO |
| **Username** | Implemented | `AppState.user_email` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **เปลี่ยนรหัสผ่าน** | Implemented | `LauncherService.change_password` | `EXISTING_UI_BINDING` | Low | NO |
| **ออกจากระบบ** | Implemented | `LauncherService.sign_out` | `EXISTING_UI_BINDING` | Low | NO |
| **วันคงเหลือ** | Implemented | `AppState.entitlement` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **วันหมดอายุ** | Implemented | `AppState.entitlement` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **ช่องกรอกคูปอง** | Implemented | `app_window.py:703` | `EXISTING_UI_BINDING` | Low | NO |
| **เติมวันใช้งาน** | Implemented | `LauncherService.redeem_coupon` | `EXISTING_UI_BINDING` | Low | NO |
| **Game Path** | Implemented & persisted | `LauncherConfig.game_exe` | `EXISTING_UI_BINDING` | Low | NO |
| **Auto Detect** | Implemented & active | `process_detector.py` | `EXISTING_BEHAVIOR_NO_SETTINGS_UI` | Low | NO |
| **Launch behavior** | Implemented | `app_window.py:742` | `EXISTING_UI_BINDING` | Low | NO |
| **Tweaker Path** | Implemented & persisted | `tweaker.path` | `EXISTING_UI_BINDING` | Low | NO |
| **Tweaker Options** | Basic launch supported | `game_process_manager.py` | `EXISTING_BEHAVIOR_NO_SETTINGS_UI` / `DEFER_RECOMMENDED` | Low | NO |
| **Region / Server** | Fixed Tokyo VPS | `defaults.py` | `AVAILABLE_DATA_ONLY` (Read-only Tokyo badge) | Low | NO |
| **User Proxy Options**| Transparent auto routing | Core Orchestrator | `AVAILABLE_DATA_ONLY` (Read-only Auto badge) | Low | NO |
| **Theme Selector** | Hardcoded Pink Light | `theme.py` | `NOT_CURRENTLY_SUPPORTED` / `DEFER_RECOMMENDED` | Low | NO |
| **Start Minimized** | Not implemented | N/A | `REQUIRES_NEW_PERSISTENCE` / `DEFER_RECOMMENDED` | Low | NO |
| **Notifications** | In-app toasts only | `toast.py` | `DEFER_RECOMMENDED` (Native OS notifications) | Low | NO |
| **Core Status** | Implemented | `AppState.proxy_status` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **Control Pipe** | Implemented | `CoreDiagnosticsRecorder` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **Telemetry Pipe** | Implemented | `TelemetryConnectionState` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **TCP Connections** | Implemented | `TelemetrySnapshot.tcp_active` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **DNS Query Count** | Implemented | `TelemetrySnapshot.dns_query_total`| `AVAILABLE_DATA_ONLY` | Low | NO |
| **RX / TX Raw** | Implemented | `TelemetrySnapshot.rx_bytes` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **Log Viewer** | Implemented | `app_window.py:465` | `EXISTING_UI_BINDING` | Low | NO |
| **Open Log Folder** | Implemented | `app_window.py:510` | `EXISTING_UI_BINDING` | Low | NO |
| **Debug Mode** | Implemented | `app_window.py:483` | `EXISTING_UI_BINDING` | Low | NO |
| **Launcher Version** | Implemented | `neko_launcher.__version__` | `AVAILABLE_DATA_ONLY` | Low | NO |
| **Core Version** | Implemented | Telemetry snapshot | `AVAILABLE_DATA_ONLY` | Low | NO |
| **Build & Copyright**| Implemented | Static constants | `AVAILABLE_DATA_ONLY` | Low | NO |

---

## 7. Customer-Facing Status Translation & Truth Table

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STATUS TRANSLATION LAYER                           │
├───────────────────────────────┬─────────────────────────────────────────────┤
│ INTERNAL RUNTIME STATE        │ CUSTOMER-FACING COPY & PRESENTATION         │
├───────────────────────────────┼─────────────────────────────────────────────┤
│ Core Waiting / No Game Process│ พร้อมใช้งาน (กำลังรอเปิด PSO2)                │
│ Game Detected / Starting Core │ กำลังเชื่อมต่อ... (ตรวจพบ PSO2)              │
│ Core Running & Telemetry Up   │ เชื่อมต่อแล้ว (Tokyo Proxy พร้อมใช้งาน)     │
│ Core Start / Auth Failure     │ ไม่สามารถเชื่อมต่อได้ (ดูใน Diagnostics)     │
│ Entitlement Expired           │ วันใช้งานหมดอายุ (กรุณาเติมวันใน Settings)   │
│ Telemetry Pipe Disconnected   │ เชื่อมต่อแล้ว (สถิติเครือข่ายขัดข้อง)        │
│ Session Revoked / Replaced    │ เซสชันหมดอายุ (กรุณาเข้าสู่ระบบใหม่)         │
└───────────────────────────────┴─────────────────────────────────────────────┘
```

### Strict Truth Table

| State Condition | Title | Subtitle | Semantic Token | Main Network Values | Settings Window | Diagnostics Detail | Allowed Action | Forbidden False Claim |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A. Auth Restoring** | `กำลังเตรียมข้อมูล...` | `กำลังตรวจสอบการเข้าสู่ระบบ` | `NEUTRAL` | `-- / 0 KB/s / 00:00:00` | Disabled | `AUTH_RESTORING` | None | Must NOT claim "พร้อมใช้งาน" before verification |
| **B. Auth OK, Idle (No Game)** | `● พร้อมใช้งาน` | `กำลังรอเปิด PSO2` | `SUCCESS` | `-- / 0 KB/s / 00:00:00` | Enabled | `WAITING_FOR_GAME` | Open Settings, Launch Game | Must NOT claim "เชื่อมต่อแล้ว" or display fake traffic |
| **C. Game Detected, Connecting**| `● กำลังเชื่อมต่อ...` | `ตรวจพบ PSO2 กำลังเริ่ม Proxy` | `WARNING` | `-- / 0 KB/s / 00:00:00` | Enabled | `START_REQUESTED` | Open Settings | Must NOT claim "เชื่อมต่อแล้ว" before handshake |
| **D. Connected & Running** | `● เชื่อมต่อแล้ว` | `Tokyo Proxy ทำงานสมบูรณ์` | `SUCCESS` | Live Ping, RX/TX, Uptime | Enabled | `RUNNING` | Open Settings | Must NOT display synthetic/fake zero ping |
| **E. Game Closed** | `● พร้อมใช้งาน` | `เกมปิดแล้ว • พักการเชื่อมต่อ` | `SUCCESS` | `-- / 0 KB/s / 00:00:00` | Enabled | `STOPPED` | Open Settings, Re-enter Game | Must NOT leave Core running after game exits |
| **F. Entitlement Expired** | `● วันใช้งานหมดอายุ` | `กรุณาเติมวันใช้งานใน Settings` | `DANGER` | `Inactive` | Enabled | `ENTITLEMENT_EXPIRED` | Open Settings > Subscription | Must NOT attempt Core start or claim "พร้อมใช้งาน" |
| **G. Session Invalidation** | `● เซสชันหมดอายุ` | `กรุณาเข้าสู่ระบบใหม่อีกครั้ง` | `DANGER` | `Disconnected` | Disabled (Auth View) | `SESSION_REVOKED` | Re-login | Must NOT display customer dashboard |
| **H. Core Start Failed** | `● การเชื่อมต่อขัดข้อง` | `ไม่สามารถเริ่มระบบ Proxy ได้` | `DANGER` | `Error` | Enabled | `START_TYPED_FAILURE` | Open Settings > Diagnostics | Must NOT mask failure as normal idle state |
| **I. Telemetry Disconnected** | `● เชื่อมต่อแล้ว` | `สถิติเครือข่ายขัดข้องชั่วคราว` | `WARNING` | `-- / -- / --` | Enabled | `TELEMETRY_DISCONNECTED`| Open Settings > Diagnostics | Must NOT fabricate traffic metrics |
| **J. Telemetry Stale** | `● เชื่อมต่อแล้ว` | `สถิติเครือข่ายไม่อัปเดตชั่วขณะ` | `WARNING` | `0 B/s (stale)` | Enabled | `TELEMETRY_STALE` | Open Settings | Must NOT claim live updates when metrics frozen |
| **K. Network / VPS Error** | `● เครือข่ายขัดข้อง` | `ไม่สามารถติดต่อเซิร์ฟเวอร์ได้` | `DANGER` | `Network Error` | Enabled | `PERMIT_TIMEOUT / 500` | Open Settings > Diagnostics | Must NOT claim tunnel is functioning |
| **L. Server Maintenance** | `● เซิร์ฟเวอร์ปิดปรับปรุง` | `ระบบกำลังบำรุงรักษาประจำสัปดาห์` | `WARNING` | `Maintenance` | Enabled | `SERVER_MAINTENANCE` | Open Settings | Must NOT claim permanent error during 2-min reboot |

---

## 8. Shared State & Window Lifecycle Architecture

```text
                  ┌─────────────────────────────────────┐
                  │        APPLICATION ROOT             │
                  │ (Services, EventBus, Config, State) │
                  └──────────────────┬──────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    ┌──────────────────────────┐           ┌───────────────────────────┐
    │       MAIN WINDOW        │           │      SETTINGS WINDOW      │
    │      (`AppWindow`)       │           │    (`SettingsWindow`)     │
    ├──────────────────────────┤           ├───────────────────────────┤
    │ • Read-Only Projections  │           │ • Single-instance toplevel│
    │ • Hero Status Card       │ ──opens──▶│ • Category navigation     │
    │ • Membership Summary     │           │ • Account & Password form │
    │ • Live Network Metrics   │           │ • Coupon redemption form  │
    │ • Tray & Background Loop │           │ • Game path configuration │
    │ • Settings Gear Button ⚙ │           │ • Local Diagnostics tools │
    └──────────────────────────┘           └───────────────────────────┘
```

### Lifecycle Rules:
1. **Single State Authority**: `SettingsWindow` **never** creates an independent `ApplicationController`, `LauncherService`, `EventBus`, or `NamedPipeCoreTelemetryClient`. It receives shared references from `AppWindow`.
2. **Single Instance Pattern**: Clicking the gear button (`⚙`) creates `SettingsWindow`. If already open, clicking gear lifts and focuses the existing window (`lift()`, `focus_force()`).
3. **Independent Dismissal**: Closing `SettingsWindow` destroys only the Settings toplevel without interrupting the Main Dashboard or Core routing.
4. **Coordinated Shutdown**: Closing Main Launcher initiates a graceful application shutdown, closing `SettingsWindow`, stopping telemetry, cancelling pending futures, and shutting down child processes.

---

## 9. Diagnostics & Privacy Boundary

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       CLIENT OBSERVABILITY PRIVACY RULE                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ ALL LOCAL DIAGNOSTICS & TELEMETRY = STRICTLY LOCAL TO USER MACHINE          │
│ FORBIDDEN TO SEND TO SUPABASE / ADMIN WEB / EXTERNAL BACKENDS:              │
│ • Core PID & Game PID                                                       │
│ • Named Pipe raw message buffers                                            │
│ • Per-process TCP connection endpoints & remote IPs                         │
│ • Local DNS queries & resolution logs                                       │
│ • Raw byte throughput histories                                             │
│ • Diagnostic exception stack traces                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Sanitization**: Any diagnostic text copied or logged must pass through `sanitize_diagnostic_text()` to strip tokens, passwords, private keys, and session challenges.
- **Debug Mode Guard**: Debug Mode is strictly an enhanced local logging and manual simulation tool. It **never** bypasses authentication, permit verification, or cryptographic challenges.

---

## 10. Visual System & Design Direction

Preserving the distinctive **NEKO Pink** commercial identity:

```text
┌───────────────────────────────┬──────────────┬──────────────────────────────┐
│ TOKEN NAME                    │ VALUE (HEX)  │ INTENDED ROLE / USAGE        │
├───────────────────────────────┼──────────────┼──────────────────────────────┤
│ PALETTE.primary               │ #F84B93      │ Brand pink, hero buttons     │
│ PALETTE.primary_soft          │ #FFB6C1      │ Badges, subtle brand accents │
│ PALETTE.primary_dark          │ #E83A82      │ Headings, emphasized brand   │
│ PALETTE.primary_hover         │ #FF65A8      │ Button hover state           │
│ PALETTE.background            │ #FFFFFF      │ Clean light background       │
│ PALETTE.card                  │ #FFFFFF      │ Elevated card containers     │
│ PALETTE.surface               │ #FFF0F5      │ Soft tinted surface panels   │
│ PALETTE.border                │ #FFC1D6      │ Soft decorative border       │
│ PALETTE.text                  │ #333333      │ Primary high-contrast text   │
│ PALETTE.text_muted            │ #8A7180      │ Secondary captions & labels  │
│ PALETTE.success               │ #32CD72      │ Ready / Connected status     │
│ PALETTE.success_surface       │ #ECFBF3      │ Success badge background     │
│ PALETTE.warning               │ #FFA07A      │ Connecting / Waiting status  │
│ PALETTE.danger                │ #FF6347      │ Failure / Expired status     │
│ PALETTE.danger_surface        │ #FFF1EE      │ Error badge background       │
└───────────────────────────────┴──────────────┴──────────────────────────────┘
```

- **Typography**: Bundled `Sarabun` (`Sarabun-Regular.ttf`, `Sarabun-Bold.ttf`) loaded via private Win32 GDI font resource.
- **Dimensions**:
  - Main Window: `480x760` (Portrait, DPI scaled)
  - Settings Window: `760x540` (Landscape, DPI scaled, minsize bounded)

---

## 11. Proposed Modular File Structure

```text
launcher/src/neko_launcher/ui/
├── __init__.py
├── app_window.py                 # Composition root, window lifecycle, background event loop
├── theme.py                      # Theme tokens, PinkPalette, fonts
├── settings_window.py            # Settings CTkToplevel shell & sidebar router
├── components/
│   ├── __init__.py
│   ├── buttons.py                # Primary/secondary buttons, cards, icon inputs
│   ├── toast.py                  # In-app toast feedback
│   └── status_pill.py            # Hero status indicator pill widget
├── platform/
│   ├── __init__.py
│   ├── system_tray.py            # Windows notification tray integration
│   ├── window_chrome.py          # Native title bar styling & DWM rounded corners
│   └── window_scaling.py         # DPI calculation for portrait & landscape
└── views/
    ├── __init__.py
    ├── auth_view.py              # Login & Registration views (pre-auth)
    ├── recovery_view.py          # Account Recovery views (pre-auth)
    ├── dashboard_view.py         # Read-only commercial status dashboard (Main)
    └── settings/
        ├── __init__.py
        ├── general_page.py       # General settings (tray, auto-connect)
        ├── account_page.py       # Account settings (username, change password, logout)
        ├── subscription_page.py  # Subscription info, remaining days, coupon redemption
        ├── pso2_page.py          # Game path, Tweaker path, launch behavior
        ├── connection_page.py    # Read-only server info (Tokyo VPS)
        ├── diagnostics_page.py   # Diagnostics, log viewer, open log folder, debug
        └── about_page.py         # Version, Core build, copyright
```

---

## 12. Implementation Scope for Phase T10B

Phase T10B will implement the visual architecture frozen here:
1. Refactor `dashboard_view.py` to be a pure read-only status dashboard.
2. Implement `settings_window.py` as a single-instance `CTkToplevel`.
3. Implement modular settings pages under `ui/views/settings/` (Account, Subscription, PSO2, Connection, Diagnostics, About, General).
4. Update `app_window.py` to delegate configuration actions to Settings.
5. Create comprehensive unit, structural, and lifecycle tests in `launcher/tests/ui/`.

---

## 13. Explicitly Deferred Items

The following items are outside the scope of T10 and deferred:
- **Windows Startup Registry Integration** (`เปิดพร้อม Windows`): Requires OS registry management.
- **Custom Theme Switching (Dark Mode)**: Requires complete dark palette design and testing.
- **Native OS Toast Notifications**: Requires native Windows 10/11 toast notification bridge.
- **Advanced Tweaker Command-line Injections**: Not needed for standard proxy operation.

---

## 14. Test Impact Plan

| Test Category | Target Coverage | Method |
| :--- | :--- | :--- |
| **Settings Lifecycle** | Single-instance enforcement, reopen existing window, close handling | Unit & Tk Mock tests in `test_settings_window.py` |
| **Main Dashboard Structure** | Verify Main contains zero configuration forms, no coupon inputs, no game browse | UI structural inspection tests |
| **Action Delegation** | Verify password change, logout, coupon redemption, and game path work correctly from Settings | Service binding verification tests |
| **Status Projection** | Verify all 12 truth table states project correct customer titles, subtitles, and color tokens | State projection unit tests |
| **Diagnostics & Privacy** | Verify sanitized log output and zero remote transmission of local metrics | Diagnostics unit tests |

---

## 15. T10A Acceptance Gates

```text
T10_BRANCH_CREATED                      = YES (feature/t10-commercial-launcher-ui)
T10_BRANCH_BASE_CORRECT                 = YES (8d4543553622f927d2d62dd054715a6523d82698)
UI_SOURCE_MODIFIED                      = NO
BUSINESS_LOGIC_MODIFIED                 = NO
CORE_MODIFIED                           = NO
SETTINGS_ARCHITECTURE                   = FROZEN
MAIN_DASHBOARD_ARCHITECTURE             = FROZEN
STATE_MATRIX                            = COMPLETE
SETTINGS_CAPABILITY_MATRIX              = COMPLETE
DIAGNOSTICS_PRIVACY                     = PASS
DOCS                                    = CURRENT
SECRET_AUDIT                            = PASS
WORKTREES                               = CLEAN
```

---

## 16. T10B1 Commercial UI Foundation Implementation

Phase T10B1 implements the commercial UI foundation, transforming the authenticated main view into a read-only customer dashboard and providing a dedicated single-instance Settings window shell with 10 navigation categories:

1. **Read-Only Dashboard (`dashboard_view.py`)**:
   - Connection Hero status pill with truth-table status presentation (`status_presentation.py`).
   - Membership summary card (Username, Active status, Expiry date).
   - Network stats summary (Download rate, Upload rate, Session duration; ping omitted per lack of latency authority).
   - Passive guidance card (*"ระบบจะเชื่อมต่อ Tokyo Proxy อัตโนมัติเมื่อเปิดเกม PSO2"*).
   - Removed coupon controls, password change button, sign-out button, game-path controls, Tweaker launch button, and debug mode controls from the Main view.

2. **Settings Window Shell (`settings_window.py`)**:
   - Standalone `CTkToplevel` window with 10 sidebar navigation categories (General, Account, Subscription, PSO2, Tweaker, Connection, Appearance, Notifications, Diagnostics, About).
   - Search filter for settings categories.
   - Strict single-instance lifecycle managed by `AppWindow`: subsequent clicks on `⚙` lift and focus the existing window; window destruction cleanly resets reference; closing Launcher terminates Settings.
   - Connection page displays sanitized customer-safe data (Tokyo VPS Lightsail, Automatic High-Speed Direct Tunnel) with zero internal IPs, ports, ciphers, or passwords exposed.

3. **Status Presentation Layer (`status_presentation.py`)**:
   - Maps `AppState` and `TelemetryState` into human-friendly customer statuses without ever falsely reporting `READY` during Core or Auth failures.

4. **Quality & Packaging Proof**:
   - 492 automated unit tests passing across all suites.
   - New debug executable built: `NekoLauncher-Debug.exe`.
   - Fresh `_MEI` extraction verified upon launch.
   - Sanitized UI screenshots captured for owner visual review.

---

## 9. Phase T10B1.1 — Commercial Visual Polish Implementation (Current Candidate)

```text
STATUS:                         T10B1.1 VISUAL POLISH CANDIDATE — OWNER REVIEW PENDING
PREDECESSOR:                    T10B1 COMMERCIAL UI FOUNDATION (Functional: PASS, Visual: REVISED)
OBJECTIVE:                      Refine UI aesthetics, hierarchy, brand identity, and remove developer language
```

### Key Visual Refinements Implemented:
1. **Developer / Phase Language Removal**:
   - All references to internal phases (`T10`, `T10B1`, `T10B2`, `รอบถัดไป`, `implementation`, `not implemented`, `pending owner review`) removed from customer-facing UI.
   - Unimplemented settings rows and preview notices cleanly omitted.

2. **Window Chrome Authority**:
   - Native Windows DWM title bar styling with single window-control authority.
   - Main window retains only the `⚙` (Settings) action in client area; internal duplicate `—` and `×` controls removed.
   - Settings window uses native Windows title bar close control; internal duplicate `×` button removed.

3. **Neko Brand Identity & Header**:
   - Compact Neko Family logo (`image_11.png`, 140x50) restored to Main header alongside clean typography.
   - Compact launcher footprint with `DESIGN_WIDTH = 440` and `DESIGN_HEIGHT = 580`, eliminating excessive lower blank space.

4. **Visual Hierarchy & Theme Tokens**:
   - Preserved Neko Pink as purposeful brand accent (buttons, selected nav, gear, subtle highlights).
   - Replaced all harsh pink card borders with subtle low-contrast structural borders (`#E5E7EB`).
   - Clean tabular alignment across Membership and Network cards.

5. **Customer Copy & Consistency**:
   - Primary Thai localization across Main cards and Settings pages (สมาชิก, เครือข่าย, ใช้งานได้, การตั้งค่าทั่วไป, บัญชีผู้ใช้, การเชื่อมต่อ, etc.).
   - Connection page displays customer-safe region `Japan (Tokyo)` and mode `อัตโนมัติ` without raw infrastructure or vendor terminology (no AWS, Lightsail, Shadowsocks, Direct Tunnel).
   - Version strictly sourced from `neko_launcher.__version__`.

---

## 18. Phase T10B1.2 — Customer-Safe Visual Closure Candidate

```text
T10B1.2:                        CUSTOMER-SAFE VISUAL CLOSURE CANDIDATE
T10B1:                          FUNCTIONAL PASS
OWNER_VISUAL_APPROVAL:          PENDING
T10B2:                          NOT STARTED
```

This bounded visual-closure candidate removes internal runtime terminology from
customer Diagnostics, removes framework and window-manager implementation detail
from About, restores the visible Settings search placeholder while preserving
category filtering, and reserves sufficient Main-window height for the complete
version footer. The product direction, Settings hierarchy, Main cards, native
chrome, and functional scope remain unchanged.

---

## 19. T10B1 Final Closure

```text
T10B1_FINAL_RESULT:             PASS
ENGINEERING:                    PASS
OWNER_VISUAL_APPROVAL:          PASS
APPROVED_COMMIT:                57698a853c0dc2b171617b19b15ae3f249afd606
APPROVED_PDW-2_EXE_SHA256:      9CD33B128CB1AFD123A78CE960612BF8DE8FE8E7ADCBCCECF4826E59E1B5ACF4
T10B2:                          IN PROGRESS
```

Approved T10B1 commercial UI foundation:

- Main read-only dashboard
- Settings dedicated window
- Customer-safe terminology
- Native chrome
- Commercial visual hierarchy

This closure preserves the historical T10B1, T10B1.1, and T10B1.2 progression
above. It is approval of the commercial UI foundation only; it is not final
product release approval, public release authorization, Phase 2.5 closure, or
authorization to merge the Launcher feature branch into `main`.

---

## 20. T10B2 Settings Functional Migration

```text
NAME:                           SETTINGS FUNCTIONAL MIGRATION
STATUS:                         BLOCKED — FINAL AUTHENTICATED PACKAGED PROOF PENDING
PRIMARY_OBJECTIVE:              Move existing supported customer actions from legacy locations
                                into the approved Settings architecture without changing
                                backend/business contracts.
```

Approved T10B2 target areas:

- Account
- Subscription
- PSO2
- PSO2 Tweaker
- Diagnostics
- About

The General, Connection, Appearance, and Notifications capability freeze remains
in force unless a capability is explicitly supported by existing product
authority.

Implemented capability authority:

| Area | Existing authority migrated into Settings |
| --- | --- |
| Account | Shared username plus existing change-password dialog and sign-out callbacks |
| Subscription | Shared entitlement values and coupon `StringVar` plus existing redeem callback |
| PSO2 | Read-only automatic `pso2.exe` process-detection status only |
| PSO2 Tweaker | Shared Tweaker executable path plus existing Browse and Launch callbacks |
| Diagnostics | Customer-safe shared connection status, existing local logs action, and existing debug-gated advanced dialog |
| About | `neko_launcher.__version__` |

```text
GAME_PATH_VAR_ACTUAL_MEANING:   TWEAKER_EXECUTABLE
PSO2_PATH_AUTHORITY:            NONE — NO EDITABLE PSO2 PATH IS PRESENTED
TWEAKER_PATH_AUTHORITY:         %LOCALAPPDATA%\NEKO FAMILY\tweaker.path
TWEAKER_PATH_OWNER:             AppWindow / LauncherConfig existing authority
BACKEND_CONTRACT_CHANGED:       NO
CORE_CHANGED:                   NO
OWNER_FUNCTIONAL_REVIEW:        PASS
SOURCE_TEST_BUILD_STATUS:       PASS
FINAL_EXE_AUTHENTICATED_PROOF:  PASS
T10B2:                          CLOSED
```

---

## 21. T10B2 Final Closure and T10B3 Opening

```text
T10B2 FINAL RESULT =
PASS

ENGINEERING =
PASS

AUTHENTICATED_PACKAGED_PROOF =
PASS

OWNER_FUNCTIONAL_UI_REVIEW =
PASS

APPROVED_SOURCE_COMMIT =
b5497e35481ffacabdc3c43ffd1191342b6c2ae2

APPROVED_EXE_SHA256 =
1A886ADEB4F142B031B5BD771F87939BA323445346F1361A4FA1EFDC8C19D4A6
```

### Final Authority Matrix

```text
ACCOUNT_CHANGE_PASSWORD =
EXISTING CALLBACK / MIGRATED TO SETTINGS

ACCOUNT_SIGN_OUT =
EXISTING CALLBACK / MIGRATED TO SETTINGS

COUPON_REDEMPTION =
EXISTING CALLBACK / MIGRATED TO SETTINGS

PSO2_PROCESS_DETECTION =
EXISTING AUTHORITY / READ-ONLY PRESENTATION

PSO2_PATH_AUTHORITY =
NO INDEPENDENT EDITABLE PATH AUTHORITY

TWEAKER_PATH_AUTHORITY =
EXISTING LEGACY PATH AUTHORITY

TWEAKER_BROWSE_LAUNCH =
MIGRATED TO SETTINGS

DIAGNOSTICS =
LOCAL CUSTOMER-SAFE SUPPORT
```

### T10B3 Commercial Polish / Final UX

```text
T10B3_NAME =
COMMERCIAL POLISH / FINAL UX

T10B3_STATUS =
IN PROGRESS

T10B3_OBJECTIVE =
Polish the now-functional commercial Settings experience without
changing business/backend contracts.
```

T10B3 may address presentation-only items such as:

- spacing/alignment of functional controls
- coupon-input placeholder/copy
- customer wording
- PSO2 status wording
- disabled/hover/focus states
- consistent field/button sizing
- DPI behavior
- 100% / 125% / 150% layout verification
- keyboard focus / tab behavior where practical
- final customer-facing state consistency
- overall visual balance after functional controls were added

Explicit owner-review carry-forward items:

1. Subscription coupon input: add customer-facing placeholder such as
   `กรอกรหัสคูปอง`.
2. PSO2 idle status: prefer customer wording such as `กำลังรอเปิด PSO2`
   instead of exposing `(รอ pso2.exe)` in normal UI.

These are T10B3 polish items, not T10B2 defects.

### T10B3 Capability Freeze

T10B3 must not introduce:

- new backend capability
- new authentication behavior
- new session behavior
- new entitlement behavior
- new coupon behavior
- dark mode
- Windows startup feature
- native notification system
- server selection
- proxy-region selection
- advanced Tweaker args
- new preference persistence
- diagnostic upload
- Ping without authority

```text
T10B3 =
UX/PRESENTATION POLISH ONLY
```

---

## 22. T10B3 Implemented Candidate

```text
T10B3_STATUS =
IMPLEMENTED CANDIDATE — OWNER FINAL VISUAL REVIEW PENDING

T10B4 =
NOT STARTED

OWNER_FINAL_VISUAL_REVIEW =
PENDING

RUNTIME_SOURCE_BASE =
52dabe8dfc83fc0cb8b74d862d292773ab5fafda

NEW_EXE_SHA256 =
695096E214C02CA147D437BBE4962DC21AC080C54CE45E6DF23D63120F93F656
```

Implemented presentation-only polish:

- Coupon guidance now visibly renders `กรอกรหัสคูปอง` while the shared coupon
  authority remains empty until the customer types; clearing restores the
  placeholder.
- Normal PSO2 status maps internal detector wording to customer-safe
  `กำลังรอเปิด PSO2` / `ตรวจพบ PSO2 แล้ว`; detector behavior is unchanged.
- Primary `เติมวัน` and `เปิด PSO2 Tweaker`, secondary file/password/log
  actions, and destructive `ออกจากระบบ` now have distinct visual hierarchy.
- Settings fields and actions use consistent minimum heights, borders, spacing,
  and long-path containment. Read-only connection and diagnostics values use
  neutral/semantic presentation instead of brand color.
- Deterministic Main and Settings geometry contracts cover logical 100%, 125%,
  and 150% scaling, content width, footer visibility, and fixed min/max bounds.
- Keyboard focus order covers Search, Account actions, Coupon, Tweaker actions,
  and Open Logs; `Ctrl+F` focuses Search without adding a custom accessibility
  framework.
- Search filtering keeps the active page coherent by selecting the first
  matching category when the previous page is filtered out; clearing restores
  all categories without altering Settings business state.
- Packaged authenticated review verified Main, Account, Subscription, PSO2,
  Tweaker, Connection, Diagnostics, About, and Search with no clipping,
  overflow, duplicate controls, or normal-customer forbidden terms.

Verification snapshot:

```text
TARGETED_UI_TESTS =               37 passed
LAUNCHER_NON_INTEGRATION =        521 passed, 5 deselected
FULL_REPOSITORY_NON_INTEGRATION = 583 passed, 5 deselected
REPOSITORY_SAFETY =               PASS
RUFF =                            PASS
FRESH_MEI =                       _MEI100442
SCREENSHOTS =                     9 packaged authenticated PNG files
```

T10B3 is not closed by this record. Owner final visual approval remains the
next gate, and T10B4 must not start before that decision.

---

## 23. T10B3.1 Final Subscription Hierarchy Candidate

```text
T10B3.1 =
FINAL SUBSCRIPTION HIERARCHY CANDIDATE

OWNER_FINAL_VISUAL_REVIEW =
PENDING

T10B4 =
NOT STARTED

NEW_EXE_SHA256 =
E4E114E138845566F7D25172CB4E8EAAC862FC43948EBEB8AF79D2F3AC9378C2
```

The Settings Subscription card now derives a presentation-only membership
status from the existing shared entitlement status. `สถานะสมาชิก` displays
only the truthful state (`ใช้งานได้`, `หมดอายุ`, or fail-closed
`ไม่พร้อมใช้งาน`), while `วันคงเหลือ` and `วันหมดอายุ` remain bound to their
existing shared authorities. No entitlement calculation or backend behavior
changed. Coupon synchronization, `กรอกรหัสคูปอง`, and `เติมวัน` are unchanged.

Verification snapshot:

```text
TARGETED_AFFECTED_UI_TESTS =     92 passed, 1 skipped
LAUNCHER_NON_INTEGRATION =       529 passed, 5 deselected
FULL_REPOSITORY_NON_INTEGRATION = 591 passed, 5 deselected
REPOSITORY_SAFETY =              PASS
RUFF =                           PASS
FRESH_MEI =                      _MEI65242
PACKAGED_SCREENSHOTS =           Main, Subscription, Account, PSO2, Tweaker
SUBSCRIPTION_INFORMATION_HIERARCHY = PASS
DUPLICATE_ENTITLEMENT_INFORMATION = NO
```

T10B3 remains not closed. Owner final visual approval is the next gate, and
T10B4 remains not started.

---

## 24. T10B3 Final Closure

```text
T10B3 =
CLOSED — ENGINEERING + OWNER FINAL VISUAL REVIEW PASS

T10B3_APPROVED_COMMIT =
1edfdb05042ed4a74128fc6826280f70f558b61d

T10B3_APPROVED_EXE_SHA256 =
E4E114E138845566F7D25172CB4E8EAAC862FC43948EBEB8AF79D2F3AC9378C2

T10B4 =
BLOCKED — CORE ARTIFACT AUTHORITY RESOLUTION REQUIRED

CORE_DEPLOYED_ARTIFACT =
AMBIGUOUS / NOT YET REFROZEN

PHASE_2_5 =
PUBLIC RELEASE BLOCKER
```

T10B3 engineering and owner final visual review are closed. T10B4 is not yet
executable and requires a separate Core artifact authority audit. No runtime
source, Core, packaging, or public-release authority changes are granted here.

