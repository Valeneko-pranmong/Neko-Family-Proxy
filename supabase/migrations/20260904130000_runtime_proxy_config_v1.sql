-- 20260904130000_runtime_proxy_config_v1.sql
-- Runtime Proxy Config v1: Immutable version ledger and singleton active pointer.

create schema if not exists launcher;

-- Immutable version ledger
create table if not exists launcher.runtime_proxy_config_versions (
  config_version bigint primary key check (config_version > 0),
  endpoint_id text not null check (endpoint_id ~ '^[\x20-\x7e]{1,64}$'),
  host text not null check (host ~ '^[\x20-\x7e]{1,253}$'),
  port integer not null check (port between 1 and 65535),
  protocol text not null check (protocol = 'shadowsocks'),
  cipher text not null check (cipher ~ '^[\x20-\x7e]{1,64}$'),
  credential text not null check (credential ~ '^[\x20-\x7e]{1,256}$'),
  published_at timestamptz not null default now()
);

-- Singleton active pointer state
create table if not exists launcher.runtime_proxy_config_state (
  singleton_id boolean primary key default true check (singleton_id = true),
  active_config_version bigint not null references launcher.runtime_proxy_config_versions(config_version),
  updated_at timestamptz not null default now()
);

-- Immutability enforcement: prevent update or delete on published version rows
create or replace function launcher.runtime_proxy_config_versions_prevent_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'runtime_proxy_config_versions rows are immutable';
end;
$$;

drop trigger if exists trg_runtime_proxy_config_versions_prevent_mutation on launcher.runtime_proxy_config_versions;
create trigger trg_runtime_proxy_config_versions_prevent_mutation
before update or delete on launcher.runtime_proxy_config_versions
for each row execute function launcher.runtime_proxy_config_versions_prevent_mutation();

-- Revoke all table access from customer/public roles and service_role
revoke all on table launcher.runtime_proxy_config_versions from public, anon, authenticated, service_role;
revoke all on table launcher.runtime_proxy_config_state from public, anon, authenticated, service_role;

-- Grant schema USAGE to service_role so it can access RPC functions in the schema
grant usage on schema launcher to service_role;

-- Service-role-only RPC to publish runtime proxy config
create or replace function launcher.publish_runtime_proxy_config(
  p_endpoint_id text,
  p_host text,
  p_port integer,
  p_cipher text,
  p_credential text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_next_version bigint;
  v_published_at timestamptz;
begin
  -- Validate inputs
  if p_endpoint_id is null or p_endpoint_id !~ '^[\x20-\x7e]{1,64}$' then
    raise exception 'invalid_endpoint_id';
  end if;
  if p_host is null or p_host !~ '^[\x20-\x7e]{1,253}$' then
    raise exception 'invalid_host';
  end if;
  if p_port is null or p_port < 1 or p_port > 65535 then
    raise exception 'invalid_port';
  end if;
  if p_cipher is null or p_cipher !~ '^[\x20-\x7e]{1,64}$' then
    raise exception 'invalid_cipher';
  end if;
  if p_credential is null or p_credential !~ '^[\x20-\x7e]{1,256}$' then
    raise exception 'invalid_credential';
  end if;

  -- Acquire deterministic advisory transaction lock for linearizing runtime config publication
  perform pg_advisory_xact_lock(hashtextextended('launcher.runtime_proxy_config_publication', 0));

  select coalesce(max(config_version), 0) + 1
  into v_next_version
  from launcher.runtime_proxy_config_versions;

  v_published_at := clock_timestamp();

  insert into launcher.runtime_proxy_config_versions (
    config_version,
    endpoint_id,
    host,
    port,
    protocol,
    cipher,
    credential,
    published_at
  ) values (
    v_next_version,
    p_endpoint_id,
    p_host,
    p_port,
    'shadowsocks',
    p_cipher,
    p_credential,
    v_published_at
  );

  insert into launcher.runtime_proxy_config_state (
    singleton_id,
    active_config_version,
    updated_at
  ) values (
    true,
    v_next_version,
    v_published_at
  )
  on conflict (singleton_id) do update
  set
    active_config_version = excluded.active_config_version,
    updated_at = excluded.updated_at;

  -- Return safe metadata only; never return credential
  return jsonb_build_object(
    'config_version', v_next_version,
    'endpoint_id', p_endpoint_id,
    'published_at', v_published_at
  );
end;
$$;

-- Service-role-only RPC to get active runtime proxy config
create or replace function launcher.get_active_runtime_proxy_config()
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_result jsonb;
begin
  select jsonb_build_object(
    'config_version', v.config_version,
    'endpoint_id', v.endpoint_id,
    'host', v.host,
    'port', v.port,
    'protocol', v.protocol,
    'cipher', v.cipher,
    'credential', v.credential,
    'published_at', v.published_at
  )
  into v_result
  from launcher.runtime_proxy_config_state s
  join launcher.runtime_proxy_config_versions v
    on v.config_version = s.active_config_version
  where s.singleton_id = true;

  return v_result;
end;
$$;

-- Revoke RPC access from public, anon, authenticated
revoke all on function launcher.publish_runtime_proxy_config(text, text, integer, text, text) from public, anon, authenticated;
revoke all on function launcher.get_active_runtime_proxy_config() from public, anon, authenticated;

-- Minimum execution grant to service_role
grant execute on function launcher.publish_runtime_proxy_config(text, text, integer, text, text) to service_role;
grant execute on function launcher.get_active_runtime_proxy_config() to service_role;
