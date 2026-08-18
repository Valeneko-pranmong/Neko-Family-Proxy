-- Phase T6B — Historical Server Metrics Persistence & Retention
-- Table for bounded time-series telemetry append.
-- Privacy invariant: Strictly aggregate server metrics only. No client telemetry.

create table if not exists public.server_metrics_history (
  server_id text not null check (length(server_id) between 1 and 64 and server_id = lower(server_id)),
  observed_at timestamptz not null,
  rx_bytes_total bigint not null check (rx_bytes_total >= 0),
  tx_bytes_total bigint not null check (tx_bytes_total >= 0),
  rx_bps double precision not null check (rx_bps >= 0),
  tx_bps double precision not null check (tx_bps >= 0),
  host_uptime_seconds bigint not null check (host_uptime_seconds >= 0),
  ping_ms double precision check (ping_ms is null or ping_ms >= 0),
  ping_status text not null default 'UNKNOWN' check (ping_status in ('AVAILABLE', 'TIMEOUT', 'UNSUPPORTED', 'UNKNOWN')),
  packet_loss_percent double precision check (packet_loss_percent is null or (packet_loss_percent >= 0 and packet_loss_percent <= 100)),
  shadowsocks_service_status text not null check (shadowsocks_service_status in ('active', 'inactive', 'failed', 'unknown')),
  shadowsocks_listener_status text not null check (shadowsocks_listener_status in ('listening', 'closed', 'error', 'unknown')),
  cpu_percent double precision check (cpu_percent is null or (cpu_percent >= 0 and cpu_percent <= 100)),
  memory_percent double precision check (memory_percent is null or (memory_percent >= 0 and memory_percent <= 100)),
  created_at timestamptz not null default now(),

  constraint server_metrics_history_pkey primary key (server_id, observed_at)
);

-- Primary range scan index (for date_bin downsampling queries)
create index if not exists server_metrics_history_range_idx
  on public.server_metrics_history (server_id, observed_at desc);

-- Retention index for efficient pruning by observed_at
create index if not exists server_metrics_history_retention_idx
  on public.server_metrics_history (observed_at);

alter table public.server_metrics_history enable row level security;

revoke all on public.server_metrics_history from anon, authenticated;
grant select on public.server_metrics_history to service_role;

-- Atomic Ingestion RPC: Handles History Append + Latest Snapshot Upsert + Duplicate Conflict Checks
create or replace function launcher.store_server_metrics_sample(
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
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_existing_hist record;
  v_current_latest_observed_at timestamptz;
  v_history_inserted boolean := false;
  v_latest_updated boolean := false;
  v_is_idempotent_retry boolean := false;
  v_now timestamptz := clock_timestamp();
begin
  -- 1. Validation
  if p_server_id is null or length(p_server_id) < 1 or length(p_server_id) > 64 or p_server_id <> lower(p_server_id) then
    raise exception 'invalid_server_id';
  end if;
  if p_observed_at is null then
    raise exception 'invalid_observed_at';
  end if;

  -- Exact timestamp validation boundaries:
  -- Future tolerance: 2 minutes (120s)
  -- Max ingest sample age: 10 minutes (600s)
  if p_observed_at > v_now + interval '2 minutes' then
    raise exception 'future_timestamp_rejected';
  end if;
  if p_observed_at < v_now - interval '10 minutes' then
    raise exception 'sample_too_old';
  end if;

  -- 2. Check for existing historical record for duplicate/conflict detection
  select * into v_existing_hist
  from public.server_metrics_history
  where server_id = p_server_id and observed_at = p_observed_at;

  if v_existing_hist is not null then
    -- Verify if incoming sample is an identical retry or a conflicting duplicate
    if v_existing_hist.rx_bytes_total = p_rx_bytes_total
       and v_existing_hist.tx_bytes_total = p_tx_bytes_total
       and v_existing_hist.rx_bps = p_rx_bps
       and v_existing_hist.tx_bps = p_tx_bps
       and v_existing_hist.host_uptime_seconds = p_host_uptime_seconds
       and v_existing_hist.shadowsocks_service_status = p_shadowsocks_service_status
       and v_existing_hist.shadowsocks_listener_status = p_shadowsocks_listener_status
       and v_existing_hist.ping_status = p_ping_status
       and v_existing_hist.ping_ms is not distinct from p_ping_ms
       and v_existing_hist.packet_loss_percent is not distinct from p_packet_loss_percent
       and v_existing_hist.cpu_percent is not distinct from p_cpu_percent
       and v_existing_hist.memory_percent is not distinct from p_memory_percent
    then
      -- Identical retry: IDEMPOTENT success
      v_is_idempotent_retry := true;
      v_history_inserted := false;
    else
      -- Conflicting duplicate: REJECT
      raise exception 'sample_conflict';
    end if;
  else
    -- Insert new historical observation
    insert into public.server_metrics_history (
      server_id,
      observed_at,
      rx_bytes_total,
      tx_bytes_total,
      rx_bps,
      tx_bps,
      host_uptime_seconds,
      ping_ms,
      ping_status,
      packet_loss_percent,
      shadowsocks_service_status,
      shadowsocks_listener_status,
      cpu_percent,
      memory_percent,
      created_at
    ) values (
      p_server_id,
      p_observed_at,
      p_rx_bytes_total,
      p_tx_bytes_total,
      p_rx_bps,
      p_tx_bps,
      p_host_uptime_seconds,
      p_ping_ms,
      p_ping_status,
      p_packet_loss_percent,
      p_shadowsocks_service_status,
      p_shadowsocks_listener_status,
      p_cpu_percent,
      p_memory_percent,
      v_now
    );
    v_history_inserted := true;
  end if;

  -- 3. Atomic Latest Snapshot Update (Only advances if observation is newer)
  select observed_at into v_current_latest_observed_at
  from public.server_metrics_latest
  where server_id = p_server_id;

  if v_current_latest_observed_at is null or p_observed_at > v_current_latest_observed_at then
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
    ) values (
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
      v_now
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
      updated_at = v_now
    where public.server_metrics_latest.observed_at < excluded.observed_at;

    v_latest_updated := true;
  else
    -- Out-of-order sample: latest snapshot does NOT regress
    v_latest_updated := false;
  end if;

  return jsonb_build_object(
    'ok', true,
    'history_inserted', v_history_inserted,
    'latest_updated', v_latest_updated,
    'is_idempotent_retry', v_is_idempotent_retry
  );
end;
$$;

revoke all on function launcher.store_server_metrics_sample(
  text, timestamptz, bigint, text, text, double precision, text, double precision, bigint, bigint, double precision, double precision, double precision, double precision
) from public, anon, authenticated;
grant execute on function launcher.store_server_metrics_sample(
  text, timestamptz, bigint, text, text, double precision, text, double precision, bigint, bigint, double precision, double precision, double precision, double precision
) to service_role;

-- Retention Pruning Function: 7-Day Bounded Rolling Retention
create or replace function launcher.prune_server_metrics_history(p_retention_days integer default 7)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_deleted_count integer;
  v_cutoff timestamptz;
begin
  if p_retention_days is null or p_retention_days < 1 then
    p_retention_days := 7;
  end if;
  v_cutoff := clock_timestamp() - (p_retention_days || ' days')::interval;
  delete from public.server_metrics_history
  where observed_at < v_cutoff;
  get diagnostics v_deleted_count = row_count;
  return v_deleted_count;
end;
$$;

revoke all on function launcher.prune_server_metrics_history(integer) from public, anon, authenticated;
grant execute on function launcher.prune_server_metrics_history(integer) to service_role;

-- Query-Time Downsampling RPC: Bounded Buckets for 1h, 24h, and 7d
create or replace function launcher.query_server_metrics_history(
  p_server_id text,
  p_range text,
  p_now timestamptz default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_now timestamptz := coalesce(p_now, clock_timestamp());
  v_window_duration interval;
  v_bucket_interval interval;
  v_bucket_seconds integer;
  v_window_start timestamptz;
  v_available_since timestamptz;
  v_points jsonb;
  v_points_count integer := 0;
begin
  if p_server_id is null or length(p_server_id) < 1 or length(p_server_id) > 64 or p_server_id <> lower(p_server_id) then
    raise exception 'invalid_server_id';
  end if;

  case p_range
    when '1h' then
      v_window_duration := interval '1 hour';
      v_bucket_interval := interval '1 minute';
      v_bucket_seconds := 60;
    when '24h' then
      v_window_duration := interval '24 hours';
      v_bucket_interval := interval '5 minutes';
      v_bucket_seconds := 300;
    when '7d' then
      v_window_duration := interval '7 days';
      v_bucket_interval := interval '30 minutes';
      v_bucket_seconds := 1800;
    else
      raise exception 'invalid_range';
  end case;

  v_window_start := v_now - v_window_duration;

  -- Look up earliest available sample for server
  select min(observed_at) into v_available_since
  from public.server_metrics_history
  where server_id = p_server_id;

  -- Aggregate into bounded uniform buckets using date_bin
  with bucketed as (
    select
      date_bin(v_bucket_interval, observed_at, v_window_start) as b_start,
      count(*)::integer as sample_count,
      round(avg(rx_bps)::numeric, 2)::double precision as rx_bps_avg,
      round(max(rx_bps)::numeric, 2)::double precision as rx_bps_max,
      round(avg(tx_bps)::numeric, 2)::double precision as tx_bps_avg,
      round(max(tx_bps)::numeric, 2)::double precision as tx_bps_max,
      case when count(ping_ms) > 0 then round(avg(ping_ms)::numeric, 2)::double precision else null end as ping_ms_avg,
      min(ping_ms)::double precision as ping_ms_min,
      max(ping_ms)::double precision as ping_ms_max,
      case when count(packet_loss_percent) > 0 then round(avg(packet_loss_percent)::numeric, 2)::double precision else null end as packet_loss_percent_avg,
      max(packet_loss_percent)::double precision as packet_loss_percent_max,
      bool_or(shadowsocks_service_status <> 'active') as had_service_failure,
      bool_or(shadowsocks_listener_status <> 'listening') as had_listener_failure
    from public.server_metrics_history
    where server_id = p_server_id
      and observed_at >= v_window_start
      and observed_at <= v_now
    group by date_bin(v_bucket_interval, observed_at, v_window_start)
    order by b_start asc
  )
  select
    coalesce(jsonb_agg(
      jsonb_build_object(
        'bucket_start', to_char(b_start, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        'sample_count', sample_count,
        'rx_bps_avg', rx_bps_avg,
        'rx_bps_max', rx_bps_max,
        'tx_bps_avg', tx_bps_avg,
        'tx_bps_max', tx_bps_max,
        'ping_ms_avg', ping_ms_avg,
        'ping_ms_min', ping_ms_min,
        'ping_ms_max', ping_ms_max,
        'packet_loss_percent_avg', packet_loss_percent_avg,
        'packet_loss_percent_max', packet_loss_percent_max,
        'shadowsocks_service_healthy', not had_service_failure,
        'shadowsocks_listener_healthy', not had_listener_failure,
        'had_service_failure', had_service_failure,
        'had_listener_failure', had_listener_failure
      )
    ), '[]'::jsonb),
    count(*)::integer
  into v_points, v_points_count
  from bucketed;

  return jsonb_build_object(
    'ok', true,
    'server_id', p_server_id,
    'range', p_range,
    'bucket_seconds', v_bucket_seconds,
    'window_start', to_char(v_window_start, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'window_end', to_char(v_now, 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'available_since', case when v_available_since is not null then to_char(v_available_since, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') else null end,
    'points_count', v_points_count,
    'points', v_points
  );
end;
$$;

revoke all on function launcher.query_server_metrics_history(text, text, timestamptz) from public, anon, authenticated;
grant execute on function launcher.query_server_metrics_history(text, text, timestamptz) to service_role;
