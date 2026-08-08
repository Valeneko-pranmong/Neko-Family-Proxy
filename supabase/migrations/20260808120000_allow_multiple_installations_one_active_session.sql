-- Allow an account to retain multiple installation records while keeping exactly
-- one active Launcher session. max_devices remains in the wire response for
-- backward compatibility but no longer limits installation history.

-- The existing launcher_sessions_one_active_per_user_idx remains authoritative.
-- Do not recreate or weaken it in this policy-only migration; staging must verify
-- its deployed definition before applying this function replacement.

create or replace function launcher.claim_session(
  p_product_code text,
  p_installation_key_hash text,
  p_display_name text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_product_id uuid;
  v_license public.licenses%rowtype;
  v_installation public.installations%rowtype;
  v_session public.launcher_sessions%rowtype;
  v_max_devices smallint;
begin
  if v_user_id is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;
  if p_product_code is null
    or p_product_code <> lower(p_product_code)
    or length(p_product_code) not between 3 and 64
  then
    raise exception 'invalid_product';
  end if;
  if p_installation_key_hash is null
    or p_installation_key_hash !~ '^[0-9a-f]{64}$'
  then
    raise exception 'invalid_installation';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(v_user_id::text, 0));

  perform 1
  from public.profiles p
  where p.id = v_user_id
    and p.status = 'active'
  for share;
  if not found then
    raise exception 'account_restricted';
  end if;

  select p.id
  into v_product_id
  from public.products p
  where p.code = p_product_code
    and p.is_active;
  if v_product_id is null then
    insert into public.audit_events(user_id, event_type, metadata)
    values (
      v_user_id,
      'license_rejected',
      jsonb_build_object('reason', 'product_not_found')
    );
    raise exception 'license_invalid';
  end if;

  select l.*
  into v_license
  from public.licenses l
  where l.user_id = v_user_id
    and l.product_id = v_product_id
    and l.status = 'active'
    and l.valid_from <= now()
    and l.valid_until > now()
  order by l.valid_until desc
  limit 1
  for share;
  if v_license.id is null then
    insert into public.audit_events(user_id, event_type, metadata)
    values (
      v_user_id,
      'license_rejected',
      jsonb_build_object(
        'reason', 'license_not_valid',
        'product_code', p_product_code
      )
    );
    raise exception 'license_invalid';
  end if;

  select i.*
  into v_installation
  from public.installations i
  where i.user_id = v_user_id
    and i.installation_key_hash = p_installation_key_hash
  for update;

  if v_installation.id is not null
    and v_installation.revoked_at is not null
  then
    raise exception 'installation_revoked';
  end if;

  v_max_devices := coalesce(
    v_license.max_devices,
    (select p.max_devices from public.products p where p.id = v_product_id),
    1
  );

  if v_installation.id is null then
    insert into public.installations(
      user_id,
      installation_key_hash,
      display_name
    )
    values (
      v_user_id,
      p_installation_key_hash,
      nullif(left(p_display_name, 120), '')
    )
    returning * into v_installation;
  else
    update public.installations
    set last_seen_at = now(),
        display_name = coalesce(
          nullif(left(p_display_name, 120), ''),
          display_name
        )
    where id = v_installation.id
    returning * into v_installation;
  end if;

  with revoked_sessions as (
    update public.launcher_sessions
    set revoked_at = now()
    where user_id = v_user_id
      and revoked_at is null
    returning id
  )
  insert into public.audit_events(user_id, event_type, metadata)
  select
    v_user_id,
    'session_revoked',
    jsonb_build_object(
      'session_id', id,
      'reason', 'replaced_by_new_session',
      'replacement_installation_id', v_installation.id
    )
  from revoked_sessions;

  insert into public.launcher_sessions(user_id, installation_id, license_id)
  values (v_user_id, v_installation.id, v_license.id)
  returning * into v_session;

  insert into public.audit_events(user_id, event_type, metadata)
  values (
    v_user_id,
    'session_claimed',
    jsonb_build_object(
      'session_id', v_session.id,
      'installation_id', v_installation.id,
      'license_id', v_license.id,
      'product_code', p_product_code
    )
  );

  return jsonb_build_object(
    'session_id', v_session.id,
    'installation_id', v_installation.id,
    'license_id', v_license.id,
    'product_code', p_product_code,
    'valid_until', v_license.valid_until,
    'max_devices', v_max_devices
  );
end;
$$;

revoke all on function launcher.claim_session(text, text, text) from public;
revoke all on function launcher.claim_session(text, text, text) from anon;
grant execute on function launcher.claim_session(text, text, text) to authenticated;
