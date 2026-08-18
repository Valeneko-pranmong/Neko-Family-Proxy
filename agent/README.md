# Neko Family Proxy — Server Agents (Japan VPS)

This directory contains the source code, systemd configurations, and environment templates for daemons and automation scripts running on the AWS Lightsail Japan VPS.

## 1. Daemons & Automation Tools

1. **`neko_server_agent.py`**:
   - Observes host and service metrics on the Japan VPS and pushes them to the Backend Ingest API for the Admin Web Dashboard.
   - Associated service: `neko-server-monitor.service`.

2. **`neko_discord_worker.py` (Phase T7 V1 / T8)**:
   - Unified long-running worker that sniffs proxy traffic on Shadowsocks port `8388` via `AF_PACKET`, maintains current throughput rates, edits the persistent Current Status message (~60s), posts 30-minute epoch-aligned Traffic Summaries with time-weighted average throughput, and sends anti-flap state transition alerts.
   - Associated service: `systemd/neko-discord-worker.service`.
   - Local state: `/var/lib/neko/discord-state.json`.
   - Secrets: `/etc/neko/discord.env` (chmod 0600).

3. **`neko_ops_status.py` (Phase T8)**:
   - Operator diagnostic CLI reporting real-time system health, systemd service states, port 8388 listeners, and state file integrity.

4. **`neko_weekly_maintenance.py` (Phase T9A)**:
   - Scheduled weekly maintenance automation controller triggered via systemd timer (`systemd/neko-weekly-maintenance.timer`, every Tuesday at 02:00 Asia/Bangkok).
   - Orderly sequence: Stops Discord worker, edits the SAME persistent Discord Current Status message to `🛠️ กำลังซ่อมบำรุง`, and triggers orderly systemd host reboot (`systemctl reboot`).
   - Units: `systemd/neko-weekly-maintenance.service`, `systemd/neko-weekly-maintenance.timer`.

## 2. Invariants
- **Local Autonomy**: Daemons run entirely within the Japan VPS. No dependencies on Vercel Cron, Supabase queries, or Backend APIs.
- **Zero Client/Session Tracking**: No user identifiers, active user counts, or client machine data are collected or sent to Discord.
- **Continuous Packet Accounting**: Long-running worker ensures continuous `AF_PACKET` frame capture without gap loss.
- **Orderly Maintenance**: Missed maintenance windows are skipped (`Persistent=false`), and Discord status recovery occurs naturally via real health evaluation upon post-boot service startup.
