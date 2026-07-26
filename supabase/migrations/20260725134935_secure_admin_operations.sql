alter table public.audit_events
  drop constraint if exists audit_events_event_type_check;

alter table public.audit_events
  add constraint audit_events_event_type_check
  check (
    event_type in (
      'session_claimed',
      'session_revoked',
      'session_rejected',
      'license_rejected',
      'coupon_batch_created',
      'coupon_redeemed',
      'coupon_batch_revoked',
      'admin_user_status_changed',
      'admin_license_revoked',
      'admin_license_extended',
      'admin_session_revoked'
    )
  );

create or replace function launcher.assert_admin_actor(p_actor_id uuid)
returns void
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
begin
  if p_actor_id is null or not exists (
    select 1
    from public.profiles p
    where p.id = p_actor_id
      and p.role = 'admin'
      and p.status = 'active'
  ) then
    raise exception 'not_authorized' using errcode = '42501';
  end if;
end;
$$;

create or replace function launcher.admin_set_user_status(
  p_actor_id uuid,
  p_user_id uuid,
  p_status text
)
returns boolean
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_previous_status text;
begin
  perform launcher.assert_admin_actor(p_actor_id);
  if p_user_id is null or p_status not in ('active', 'suspended', 'banned') then
    raise exception 'invalid_user_status';
  end if;
  if p_actor_id = p_user_id and p_status <> 'active' then
    raise exception 'cannot_restrict_current_admin';
  end if;

  select p.status into v_previous_status
  from public.profiles p
  where p.id = p_user_id
  for update;
  if v_previous_status is null then
    raise exception 'user_not_found';
  end if;

  if v_previous_status is distinct from p_status then
    update public.profiles
    set status = p_status, updated_at = now()
    where id = p_user_id;

    if p_status <> 'active' then
      update public.launcher_sessions
      set revoked_at = coalesce(revoked_at, now())
      where user_id = p_user_id
        and revoked_at is null;
    end if;

    insert into public.audit_events (user_id, event_type, metadata)
    values (
      p_actor_id,
      'admin_user_status_changed',
      jsonb_build_object(
        'target_user_id', p_user_id,
        'previous_status', v_previous_status,
        'new_status', p_status
      )
    );
  end if;
  return true;
end;
$$;

create or replace function launcher.admin_revoke_license(
  p_actor_id uuid,
  p_license_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid;
  v_previous_status text;
begin
  perform launcher.assert_admin_actor(p_actor_id);

  select l.user_id, l.status
  into v_user_id, v_previous_status
  from public.licenses l
  where l.id = p_license_id
  for update;
  if v_user_id is null then
    raise exception 'license_not_found';
  end if;

  if v_previous_status <> 'revoked' then
    update public.licenses
    set status = 'revoked'
    where id = p_license_id;

    update public.launcher_sessions
    set revoked_at = coalesce(revoked_at, now())
    where license_id = p_license_id
      and revoked_at is null;

    insert into public.audit_events (user_id, event_type, metadata)
    values (
      p_actor_id,
      'admin_license_revoked',
      jsonb_build_object(
        'license_id', p_license_id,
        'target_user_id', v_user_id,
        'previous_status', v_previous_status
      )
    );
  end if;
  return true;
end;
$$;

create or replace function launcher.admin_extend_license(
  p_actor_id uuid,
  p_license_id uuid,
  p_days integer
)
returns timestamptz
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid;
  v_previous_until timestamptz;
  v_valid_until timestamptz;
begin
  perform launcher.assert_admin_actor(p_actor_id);
  if p_days is null or p_days not between 1 and 3650 then
    raise exception 'invalid_extension_days';
  end if;

  select l.user_id, l.valid_until
  into v_user_id, v_previous_until
  from public.licenses l
  where l.id = p_license_id
  for update;
  if v_user_id is null then
    raise exception 'license_not_found';
  end if;

  v_valid_until := greatest(v_previous_until, now())
    + make_interval(days => p_days);
  update public.licenses
  set valid_until = v_valid_until, status = 'active'
  where id = p_license_id;

  insert into public.audit_events (user_id, event_type, metadata)
  values (
    p_actor_id,
    'admin_license_extended',
    jsonb_build_object(
      'license_id', p_license_id,
      'target_user_id', v_user_id,
      'days_added', p_days,
      'previous_valid_until', v_previous_until,
      'valid_until', v_valid_until
    )
  );
  return v_valid_until;
end;
$$;

create or replace function launcher.admin_revoke_session(
  p_actor_id uuid,
  p_session_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid;
  v_was_active boolean;
begin
  perform launcher.assert_admin_actor(p_actor_id);

  select s.user_id, s.revoked_at is null
  into v_user_id, v_was_active
  from public.launcher_sessions s
  where s.id = p_session_id
  for update;
  if v_user_id is null then
    raise exception 'session_not_found';
  end if;

  if v_was_active then
    update public.launcher_sessions
    set revoked_at = now()
    where id = p_session_id;

    insert into public.audit_events (user_id, event_type, metadata)
    values (
      p_actor_id,
      'admin_session_revoked',
      jsonb_build_object(
        'session_id', p_session_id,
        'target_user_id', v_user_id
      )
    );
  end if;
  return true;
end;
$$;

create or replace function launcher.admin_generate_coupon_batch(
  p_actor_id uuid,
  p_product_code text,
  p_duration_days integer,
  p_quantity integer,
  p_expires_at timestamptz default null,
  p_note text default null
)
returns table(batch_id uuid, code text)
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_product_id uuid;
  v_batch_id uuid;
  v_secret text;
  v_normalized text;
  v_counter integer;
begin
  perform launcher.assert_admin_actor(p_actor_id);
  if p_duration_days is null
     or p_duration_days not between 1 and 3650
     or p_quantity is null
     or p_quantity not between 1 and 500
     or (p_expires_at is not null and p_expires_at <= now())
     or (p_note is not null and length(p_note) > 500) then
    raise exception 'invalid_coupon_batch';
  end if;

  select p.id into v_product_id
  from public.products p
  where p.code = lower(trim(p_product_code))
    and p.is_active;
  if v_product_id is null then
    raise exception 'product_not_found';
  end if;

  insert into public.coupon_batches (
    product_id,
    duration_days,
    quantity,
    expires_at,
    note,
    created_by
  )
  values (
    v_product_id,
    p_duration_days,
    p_quantity,
    p_expires_at,
    nullif(trim(p_note), ''),
    p_actor_id
  )
  returning id into v_batch_id;

  for v_counter in 1..p_quantity loop
    loop
      v_secret := upper(encode(gen_random_bytes(16), 'hex'));
      v_normalized := 'NEKO' || v_secret;
      begin
        insert into public.coupons (batch_id, code_hash)
        values (v_batch_id, encode(digest(v_normalized, 'sha256'), 'hex'));
        exit;
      exception when unique_violation then
        null;
      end;
    end loop;

    batch_id := v_batch_id;
    code := 'NEKO-'
      || substr(v_secret, 1, 8) || '-'
      || substr(v_secret, 9, 8) || '-'
      || substr(v_secret, 17, 8) || '-'
      || substr(v_secret, 25, 8);
    return next;
  end loop;

  insert into public.audit_events (user_id, event_type, metadata)
  values (
    p_actor_id,
    'coupon_batch_created',
    jsonb_build_object(
      'batch_id', v_batch_id,
      'product_id', v_product_id,
      'duration_days', p_duration_days,
      'quantity', p_quantity,
      'expires_at', p_expires_at
    )
  );
end;
$$;

create or replace function launcher.admin_revoke_coupon_batch(
  p_actor_id uuid,
  p_batch_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_count integer;
begin
  perform launcher.assert_admin_actor(p_actor_id);

  update public.coupon_batches
  set revoked_at = now()
  where id = p_batch_id
    and revoked_at is null;
  get diagnostics v_count = row_count;

  if v_count > 0 then
    update public.coupons
    set status = 'revoked'
    where batch_id = p_batch_id
      and status = 'active';

    insert into public.audit_events (user_id, event_type, metadata)
    values (
      p_actor_id,
      'coupon_batch_revoked',
      jsonb_build_object('batch_id', p_batch_id)
    );
  end if;
  return v_count > 0;
end;
$$;

grant usage on schema launcher to service_role;

revoke all on function launcher.assert_admin_actor(uuid)
  from public, anon, authenticated;
revoke all on function launcher.admin_set_user_status(uuid, uuid, text)
  from public, anon, authenticated;
revoke all on function launcher.admin_revoke_license(uuid, uuid)
  from public, anon, authenticated;
revoke all on function launcher.admin_extend_license(uuid, uuid, integer)
  from public, anon, authenticated;
revoke all on function launcher.admin_revoke_session(uuid, uuid)
  from public, anon, authenticated;
revoke all on function launcher.admin_generate_coupon_batch(
  uuid, text, integer, integer, timestamptz, text
) from public, anon, authenticated;
revoke all on function launcher.admin_revoke_coupon_batch(uuid, uuid)
  from public, anon, authenticated;

grant execute on function launcher.assert_admin_actor(uuid)
  to service_role;
grant execute on function launcher.admin_set_user_status(uuid, uuid, text)
  to service_role;
grant execute on function launcher.admin_revoke_license(uuid, uuid)
  to service_role;
grant execute on function launcher.admin_extend_license(uuid, uuid, integer)
  to service_role;
grant execute on function launcher.admin_revoke_session(uuid, uuid)
  to service_role;
grant execute on function launcher.admin_generate_coupon_batch(
  uuid, text, integer, integer, timestamptz, text
) to service_role;
grant execute on function launcher.admin_revoke_coupon_batch(uuid, uuid)
  to service_role;
