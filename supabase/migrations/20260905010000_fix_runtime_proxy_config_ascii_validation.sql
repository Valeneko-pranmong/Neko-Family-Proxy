-- Replace runtime proxy config regex validation with explicit printable ASCII checks.

create or replace function launcher.runtime_proxy_config_text_is_printable_ascii(
  p_value text,
  p_max_length integer
)
returns boolean
language plpgsql
immutable
parallel safe
set search_path = ''
as $$
declare
  v_position integer;
  v_codepoint integer;
begin
  if p_value is null or p_max_length is null or p_max_length < 1 then
    return false;
  end if;

  if pg_catalog.length(p_value) not between 1 and p_max_length then
    return false;
  end if;

  for v_position in 1..pg_catalog.length(p_value) loop
    v_codepoint := pg_catalog.ascii(pg_catalog.substr(p_value, v_position, 1));
    if v_codepoint not between 32 and 126 then
      return false;
    end if;
  end loop;

  return true;
end;
$$;

alter table launcher.runtime_proxy_config_versions
  drop constraint runtime_proxy_config_versions_endpoint_id_check,
  drop constraint runtime_proxy_config_versions_host_check,
  drop constraint runtime_proxy_config_versions_cipher_check,
  drop constraint runtime_proxy_config_versions_credential_check;

alter table launcher.runtime_proxy_config_versions
  add constraint runtime_proxy_config_versions_endpoint_id_check
    check (launcher.runtime_proxy_config_text_is_printable_ascii(endpoint_id, 64)),
  add constraint runtime_proxy_config_versions_host_check
    check (launcher.runtime_proxy_config_text_is_printable_ascii(host, 253)),
  add constraint runtime_proxy_config_versions_cipher_check
    check (launcher.runtime_proxy_config_text_is_printable_ascii(cipher, 64)),
  add constraint runtime_proxy_config_versions_credential_check
    check (launcher.runtime_proxy_config_text_is_printable_ascii(credential, 256));

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
  if not launcher.runtime_proxy_config_text_is_printable_ascii(p_endpoint_id, 64) then
    raise exception 'invalid_endpoint_id';
  end if;
  if not launcher.runtime_proxy_config_text_is_printable_ascii(p_host, 253) then
    raise exception 'invalid_host';
  end if;
  if p_port is null or p_port < 1 or p_port > 65535 then
    raise exception 'invalid_port';
  end if;
  if not launcher.runtime_proxy_config_text_is_printable_ascii(p_cipher, 64) then
    raise exception 'invalid_cipher';
  end if;
  if not launcher.runtime_proxy_config_text_is_printable_ascii(p_credential, 256) then
    raise exception 'invalid_credential';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('launcher.runtime_proxy_config_publication', 0)
  );

  select pg_catalog.coalesce(pg_catalog.max(config_version), 0) + 1
  into v_next_version
  from launcher.runtime_proxy_config_versions;

  v_published_at := pg_catalog.clock_timestamp();

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

  return pg_catalog.jsonb_build_object(
    'config_version', v_next_version,
    'endpoint_id', p_endpoint_id,
    'published_at', v_published_at
  );
end;
$$;

revoke all on function launcher.runtime_proxy_config_text_is_printable_ascii(text, integer)
  from public, anon, authenticated, service_role;
revoke all on function launcher.publish_runtime_proxy_config(text, text, integer, text, text)
  from public, anon, authenticated, service_role;
grant execute on function launcher.publish_runtime_proxy_config(text, text, integer, text, text)
  to service_role;
