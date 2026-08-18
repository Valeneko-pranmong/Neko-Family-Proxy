# NEKO FAMILY PROXY — CURRENT PROJECT STATUS & START HERE GUIDE

```text
DOCUMENT:               docs/current/README.md
STATUS:                 AUTHORITATIVE CURRENT PROJECT STATUS
CLASSIFICATION:         PRIMARY ORIENTATION & GOVERNANCE AUTHORITY
CURRENT_PHASE:          T9A CANDIDATE COMPLETE — WEEKLY MAINTENANCE AUTOMATION & SEGA DISCOVERY
LAST_CLOSED_PHASE:      T8C (Controlled Production Operations Hardening Rollout + Proof)
ACTIVE_PHASE:           T9A (Weekly Maintenance Automation & SEGA Discovery — CANDIDATE)
NEXT_PHASE:             T9B (Controlled Weekly Maintenance Production Rollout)
DATE:                   2026-08-18
```

---

## 1. Quick Orientation: What is the Project Doing Now?

**Neko Family Proxy** is a high-performance proxy routing and management platform for *Phantasy Star Online 2 (PSO2 JP)*.

The project has completed **Phase T6 (Historical Server Metrics)**, **Phase T7 V1 (Unified AWS Lightsail Discord Integration)**, and **Phase T8 (Production Operations & Health Hardening)**, and has now completed candidate implementation for **Phase T9A (Weekly Maintenance Automation & SEGA Probe Authority Discovery)**:
- **Phase T4B (Closed)** established the live server monitoring pipeline from Japan VPS to Backend to Admin Dashboard.
- **Phase T5 (Closed)** polished the Admin Dashboard UI and added an honest browser-local rolling 5-minute live network graph.
- **Phase T6 (Closed)** designed, implemented, migrated, and production-verified 7-day raw historical server time-series storage, automated hourly retention pruning via `pg_cron`, and historical range queries (1h, 24h, 7d).
- **Phase T7 V1 (Closed & Production Verified)**: Unified Discord status embed (~60s), transition alerts with anti-flap 2-sample confirmation and 300s cooldown, time-weighted average throughput Traffic Summary (30m epoch boundary, 1 MiB threshold gating), and local atomic state persistence (`/var/lib/neko/discord-state.json`) into a single long-running Lightsail daemon (`neko-discord-worker.service`). Controlled production cutover completed with zero dual-publishing and legacy service safely disabled.
- **Phase T8 (Closed & Production Verified)**: Hardened VPS reliability, boot authority, restart backoff, journal hygiene, atomic state cleanup, and operator diagnostics without adding external SaaS dependencies, external watchdogs, or cloud scheduler infrastructure.
- **Phase T9A (Candidate Complete / Discovery Frozen)**: Designed and implemented source-controlled weekly maintenance controller (`agent/neko_weekly_maintenance.py`), systemd oneshot service (`agent/systemd/neko-weekly-maintenance.service`), and systemd timer (`agent/systemd/neko-weekly-maintenance.timer`) executing every Tuesday at 02:00 Asia/Bangkok with `Persistent=false` and `AccuracySec=1s`. Implemented bounded duplicate message protection (no blind POST on missing state ID) and in-place Discord `🛠️ กำลังซ่อมบำรุง` status editing. Completed deep read-only inspection of legacy JP AES project, freezing `SEGA_PROBE_AUTHORITY = BLOCKED_PENDING_AUTHORITY` and strictly preserving `Ping (Proxy VPS → Upstream)` probing `1.1.1.1`. 62 deterministic unit tests passing.

---

## 2. Phase Status & Authority Checkpoints

| Phase | Description | Status | Authority Commit / Milestone |
| :--- | :--- | :---: | :--- |
| **Phase T1-T2** | Core Telemetry Engine | **CLOSED** | Frozen at Phase T2 (Local Named Pipe diagnostics) |
| **Phase T3** | Launcher Telemetry Consumer | **CLOSED** | Frozen at Phase T3 (Local GUI consumption) |
| **Phase T4A** | Server Monitoring Architecture Contract | **CLOSED** | `docs/architecture/server-monitoring-session-boundary.md` |
| **Phase T4B** | Server Monitoring Data Plane & Production Deploy | **CLOSED** | Backend `bc34b5b1...` / Admin `2aac1028...` |
| **Phase T5** | Admin Dashboard Polish & Live Visualization | **CLOSED** | Source: `840adc18...` / Evidence: `41067701...` |
| **Phase T6A** | Historical Server Metrics Architecture | **CLOSED (DESIGN FROZEN)** | Commit `7168bf65...` / `docs/architecture/historical-server-metrics.md` |
| **Phase T6B** | Historical Persistence & Admin History API | **CLOSED** | Backend `94f389c5...` / Admin `2662193e...` |
| **Phase T6C** | Admin Dashboard Historical Charts UI | **CLOSED** | Commit `6b5940bd...` / UI Range Selectors & Gap Splitting |
| **Phase T6D** | Production Deployment & Historical Proof | **CLOSED** | Backend `852bfb67...` / Retention `pg_cron` / Remote Proof Verified |
| **Original T7A** | Vercel Cron / Backend Discord Architecture | **SUPERSEDED** | Commit `d242c598...` (Superseded by Owner Decision in favor of T7 V1) |
| **Phase T7 V1A** | Legacy Discord Discovery & Lightsail Architecture Freeze | **CLOSED (AUTHORITY FROZEN)** | Admin `6a59900a...` / Discovery & Architecture Freeze |
| **Phase T7 V1B** | Unified Lightsail Discord Worker & Tests | **CLOSED (CANDIDATE COMPLETE)**| Backend `5ad8e693...` / 29 Unit Tests Passing / Systemd Candidate |
| **Phase T7 V1C** | Production Deployment & Legacy Cutover | **CLOSED (PRODUCTION PROOF)**  | Live Proof Verified / 1 Publisher Active / Legacy Disabled |
| **Phase T8A** | Production Operations Baseline Audit & Hardening Design | **CLOSED (AUDIT & DESIGN FROZEN)** | Admin Doc Commit `e810ee8b...` / Live VPS Audit Verified |
| **Phase T8B** | Local Operations Hardening Candidate Implementation | **CLOSED (CANDIDATE COMPLETE)** | Backend `3ce6ccdb...` / Admin `077e523c...` / 51 Tests PASS |
| **Phase T8C** | Controlled Production Hardening Rollout & Proof | **CLOSED (PRODUCTION PROOF)** | Live Proof Verified / Restart=always / Journal 500M / Ops Status Live |
| **Phase T9A** | Weekly Maintenance Automation & SEGA Discovery | **CLOSED (CANDIDATE COMPLETE)** | `docs/current/weekly-maintenance-automation-handoff.md` / 62 Tests PASS |

### Git Authority Identifiers:
- **Admin Git T6A Design Commit**: `7168bf655623230f3a327f48705cb880f34fa830`
- **Backend Git T6B Migration Commit**: `94f389c5c3dfd6c919dcbdb54955ebc621345b5f`
- **Backend Git T6D Retention Commit**: `852bfb67e482d264729fc83aa862340c732df7db`
- **Backend Git T7 V1B Server Commit**: `5ad8e693e549b7d8b5b178f7269f9b1b737ac8bf`
- **Backend Git T8B Server Commit**: `3ce6ccdb2d98eb5869ddfdbeb3946431d34eae4a`
- **Backend Git T8C Server Remote Authority**: `3ce6ccdb2d98eb5869ddfdbeb3946431d34eae4a`
- **Admin Git T6B Implementation Commit**: `2662193e077789a3beae5d4063b74b6fba7fd6ec`
- **Admin Git T6C UI Implementation Commit**: `6b5940bdfcd2dcbaf1d5966213fab934c2a4c85d`
- **Admin Runtime Source (Deployed Authority)**: `6b5940bdfcd2dcbaf1d5966213fab934c2a4c85d`
- **Admin Original T7A Baseline Commit**: `d242c5981d04b2b11fdbae79aa908bd646275eb7`
- **Admin T7 V1B Architecture Correction**: `a35311d059e591430f99cb74bf70dca0f31cb435`
- **Admin T7 V1B Doc Record Commit**: `b33db64e2b480b5851943b15f396779dca77917b`
- **Admin T7 V1C Production Proof Commit**: `683cb99724e9dffbf342875031f0e0a4abbc6172`
- **Admin T8A Baseline Audit Commit**: `e810ee8ba07a5f45d05da75aaf1d34c50d139494`
- **Admin T8B Implementation Handoff Commit**: `077e523c9511b48b47c4e45720b448d0445399cf`

---

## 3. Monitoring System Operational State

```text
CURRENT_PRODUCTION_MONITORING   = LIVE (T4B/T5/T6)
CURRENT_PRODUCTION_STORAGE      = LATEST + HISTORY (public.server_metrics_latest & public.server_metrics_history)
CURRENT_LIVE_GRAPH              = BROWSER_LOCAL_ROLLING (~5 minutes, 60 samples, resets on reload)
PRODUCTION_HISTORY              = LIVE (7-day bounded rolling raw telemetry)
PRODUCTION_HISTORY_API          = LIVE (GET /api/server/metrics/history?range=1h|24h|7d)
PRODUCTION_HISTORICAL_CHARTS    = LIVE (Interactive range switching, gap splitting, degradation markers)
HISTORICAL_RETENTION_RULE       = 7 DAYS RAW (Pruned hourly via database scheduled job launcher.prune_server_metrics_history)
DISCORD_PRODUCTION_STATE        = UNIFIED WORKER ACTIVE (neko-discord-worker.service on AWS Lightsail)
UNIFIED_T7_V1_DISCORD_WORKER    = PRODUCTION HARDENED & LIVE (Restart=always / MemoryMax=128M / TasksMax=16)
LEGACY_DISCORD_SERVICE          = INACTIVE & DISABLED (Rollback Artifacts Preserved)
SHADOWSOCKS_RECOVERY_POLICY     = ACTIVE (Restart=always / 5s / 60s burst 5 drop-in)
JOURNALD_STORAGE_POLICY         = ACTIVE (SystemMaxUse=500M drop-in)
OPERATOR_DIAGNOSTICS_TOOL       = LIVE (/opt/neko/neko_ops_status.py — 0_HEALTHY)
CONFIG_PREFLIGHT_CHECK          = ACTIVE (ExecStartPre /opt/neko/neko_discord_worker.py --check-config)
OPERATIONS_HARDENING_STATE      = T8C PRODUCTION DEPLOYED & VERIFIED
WEEKLY_MAINTENANCE_STATE        = T9A CANDIDATE IMPLEMENTED & VERIFIED LOCALLY
```
