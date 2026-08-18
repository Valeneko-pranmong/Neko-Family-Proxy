-- Phase T4B — Server Monitoring Data Plane / Latest Snapshot Storage Authority
-- Dedicated persisted single-row snapshot table per server.
-- Privacy invariant: Contains exclusively aggregate VPS infrastructure metrics.
-- No client telemetry or credentials may be stored in this table.

create table if not exists public.server_metrics_latest (
  server_id text primary key check (length(server_id) between 1 and 64 and server_id = lower(server_id)),
  observed_at timestamptz not null,
  host_uptime_seconds bigint not null check (host_uptime_seconds >= 0),
  shadowsocks_service_status text not null check (shadowsocks_service_status in ('active', 'inactive', 'failed', 'unknown')),
  shadowsocks_listener_status text not null check (shadowsocks_listener_status in ('listening', 'closed', 'error', 'unknown')),
  ping_ms double precision check (ping_ms is null or ping_ms >= 0),
  ping_status text not null default 'UNKNOWN' check (ping_status in ('AVAILABLE', 'TIMEOUT', 'UNSUPPORTED', 'UNKNOWN')),
  packet_loss_percent double precision check (packet_loss_percent is null or (packet_loss_percent >= 0 and packet_loss_percent <= 100)),
  rx_bytes_total bigint not null check (rx_bytes_total >= 0),
  tx_bytes_total bigint not null check (tx_bytes_total >= 0),
  rx_bps double precision not null check (rx_bps >= 0),
  tx_bps double precision not null check (tx_bps >= 0),
  cpu_percent double precision check (cpu_percent is null or (cpu_percent >= 0 and cpu_percent <= 100)),
  memory_percent double precision check (memory_percent is null or (memory_percent >= 0 and memory_percent <= 100)),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists server_metrics_latest_observed_idx
  on public.server_metrics_latest (server_id, observed_at desc);

alter table public.server_metrics_latest enable row level security;

-- Atomic upsert with replay and stale-write protection
create or replace function launcher.upsert_server_metrics_latest(
  p_server_id text,
  p_observed_at timestamptz,
  p_host_uptime_seconds bigint,
  p_shadowsocks_service_status text,
  p_shadowsocks_listener_status text,
  p_ping_ms double precision,
  p_ping_status text,
  p_packet_loss_percent double precision,
  p_rx_bytes_total bigint,
  p_tx_bytes_total bigint,
  p_rx_bps double precision,
  p_tx_bps double precision,
  p_cpu_percent double precision default null,
  p_memory_percent double precision default null
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_current_observed_at timestamptz;
begin
  if p_server_id is null or length(p_server_id) < 1 or length(p_server_id) > 64 or p_server_id <> lower(p_server_id) then
    raise exception 'invalid_server_id';
  end if;
  if p_observed_at is null then
    raise exception 'invalid_observed_at';
  end if;

  select observed_at into v_current_observed_at
  from public.server_metrics_latest
  where server_id = p_server_id;

  if v_current_observed_at is not null and p_observed_at <= v_current_observed_at then
    -- Stale report or replay: do not overwrite newer authoritative snapshot
    return false;
  end if;

  insert into public.server_metrics_latest (
    server_id,
    observed_at,
    host_uptime_seconds,
    shadowsocks_service_status,
    shadowsocks_listener_status,
    ping_ms,
    ping_status,
    packet_loss_percent,
    rx_bytes_total,
    tx_bytes_total,
    rx_bps,
    tx_bps,
    cpu_percent,
    memory_percent,
    updated_at
  )
  values (
    p_server_id,
    p_observed_at,
    p_host_uptime_seconds,
    p_shadowsocks_service_status,
    p_shadowsocks_listener_status,
    p_ping_ms,
    p_ping_status,
    p_packet_loss_percent,
    p_rx_bytes_total,
    p_tx_bytes_total,
    p_rx_bps,
    p_tx_bps,
    p_cpu_percent,
    p_memory_percent,
    now()
  )
  on conflict (server_id) do update set
    observed_at = excluded.observed_at,
    host_uptime_seconds = excluded.host_uptime_seconds,
    shadowsocks_service_status = excluded.shadowsocks_service_status,
    shadowsocks_listener_status = excluded.shadowsocks_listener_status,
    ping_ms = excluded.ping_ms,
    ping_status = excluded.ping_status,
    packet_loss_percent = excluded.packet_loss_percent,
    rx_bytes_total = excluded.rx_bytes_total,
    tx_bytes_total = excluded.tx_bytes_total,
    rx_bps = excluded.rx_bps,
    tx_bps = excluded.tx_bps,
    cpu_percent = excluded.cpu_percent,
    memory_percent = excluded.memory_percent,
    updated_at = now()
  where public.server_metrics_latest.observed_at < excluded.observed_at;

  return true;
end;
$$;
