# Neko Family Proxy — Server Agents (Japan VPS)

This directory contains the source code, systemd configurations, and environment templates for daemons running on the AWS Lightsail Japan VPS.

## 1. Daemons

1. **`neko_server_agent.py`**:
   - Observes host and service metrics on the Japan VPS and pushes them to the Backend Ingest API for the Admin Web Dashboard.
   - Associated service: `neko-server-monitor.service`.

2. **`neko_discord_worker.py` (Phase T7 V1 Candidate)**:
   - Unified long-running worker that sniffs proxy traffic on Shadowsocks port `8388` via `AF_PACKET`, maintains current throughput rates, edits the persistent Current Status message (~60s), posts 30-minute epoch-aligned Traffic Summaries with time-weighted average throughput, and sends anti-flap state transition alerts.
   - Associated service: `systemd/neko-discord-worker.service`.
   - Local state: `/var/lib/neko/discord-state.json`.
   - Secrets: `/etc/neko/discord.env` (chmod 0600).

## 2. Invariants
- **Local Autonomy**: Discord worker runs entirely within the Japan VPS. No dependencies on Vercel Cron, Supabase queries, or Backend APIs.
- **Zero Client/Session Tracking**: No user identifiers, active user counts, or client machine data are collected or sent to Discord.
- **Continuous Packet Accounting**: Long-running service ensures continuous `AF_PACKET` frame capture without gap loss.
