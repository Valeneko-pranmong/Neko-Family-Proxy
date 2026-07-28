alter table public.coupon_redemption_attempts
  add column if not exists batch_id uuid
  references public.coupon_batches(id) on delete set null;

update public.coupon_redemption_attempts a
set batch_id = c.batch_id
from public.coupons c
where a.coupon_id = c.id
  and a.batch_id is null;

create index if not exists coupon_redemption_attempts_batch_id_idx
  on public.coupon_redemption_attempts (batch_id);

-- A redeemed coupon is no longer a durable record. Redemption history remains
-- in coupon_redemption_attempts and audit_events.
delete from public.coupons
where status = 'redeemed';

create or replace function launcher.redeem_coupon(p_code text)
returns jsonb
language plpgsql
security definer
set search_path = public, launcher, extensions, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_normalized text;
  v_code_hash text;
  v_attempt_count integer;
  v_coupon_id uuid;
  v_coupon_status text;
  v_batch_id uuid;
  v_batch_revoked_at timestamptz;
  v_batch_expires_at timestamptz;
  v_product_id uuid;
  v_product_code text;
  v_duration_days integer;
  v_license public.licenses%rowtype;
  v_valid_until timestamptz;
begin
  if v_user_id is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;

  select count(*) into v_attempt_count
  from public.coupon_redemption_attempts a
  where a.user_id = v_user_id
    and a.attempted_at > now() - interval '10 minutes';

  if v_attempt_count >= 10 then
    return jsonb_build_object('ok', false, 'error', 'rate_limited');
  end if;

  if not exists (
    select 1
    from public.profiles p
    where p.id = v_user_id
      and p.status = 'active'
  ) then
    insert into public.coupon_redemption_attempts (user_id, succeeded, error_code)
    values (v_user_id, false, 'account_restricted');
    return jsonb_build_object('ok', false, 'error', 'account_restricted');
  end if;

  v_normalized := upper(regexp_replace(coalesce(p_code, ''), '[^0-9A-Za-z]', '', 'g'));

  if v_normalized !~ '^NEKO[0-9A-F]{32}$' then
    insert into public.coupon_redemption_attempts (user_id, succeeded, error_code)
    values (v_user_id, false, 'invalid_coupon');
    return jsonb_build_object('ok', false, 'error', 'invalid_coupon');
  end if;

  v_code_hash := encode(digest(v_normalized, 'sha256'), 'hex');
  perform pg_advisory_xact_lock(hashtextextended(v_code_hash, 0));

  select
    c.id,
    c.status,
    b.id,
    b.revoked_at,
    b.expires_at,
    b.product_id,
    p.code,
    b.duration_days
  into
    v_coupon_id,
    v_coupon_status,
    v_batch_id,
    v_batch_revoked_at,
    v_batch_expires_at,
    v_product_id,
    v_product_code,
    v_duration_days
  from public.coupons c
  join public.coupon_batches b on b.id = c.batch_id
  join public.products p on p.id = b.product_id
  where c.code_hash = v_code_hash
  for update of c;

  if v_coupon_id is null
     or v_coupon_status <> 'active'
     or v_batch_revoked_at is not null
     or (v_batch_expires_at is not null and v_batch_expires_at <= now()) then
    insert into public.coupon_redemption_attempts (
      user_id,
      coupon_id,
      batch_id,
      succeeded,
      error_code
    )
    values (
      v_user_id,
      v_coupon_id,
      v_batch_id,
      false,
      'invalid_coupon'
    );
    return jsonb_build_object('ok', false, 'error', 'invalid_coupon');
  end if;

  -- Different coupons for the same user/product can arrive concurrently.
  -- Serialize license mutation so only one active row is created or extended.
  perform pg_advisory_xact_lock(
    hashtextextended(v_user_id::text || ':' || v_product_id::text, 1)
  );

  select l.* into v_license
  from public.licenses l
  where l.user_id = v_user_id
    and l.product_id = v_product_id
    and l.status = 'active'
  order by l.valid_until desc
  limit 1
  for update;

  if v_license.id is null then
    v_valid_until := now() + make_interval(days => v_duration_days);
    insert into public.licenses (
      user_id,
      product_id,
      status,
      valid_from,
      valid_until
    )
    values (
      v_user_id,
      v_product_id,
      'active',
      now(),
      v_valid_until
    );
  else
    v_valid_until := greatest(v_license.valid_until, now())
      + make_interval(days => v_duration_days);
    update public.licenses
    set valid_until = v_valid_until
    where id = v_license.id;
  end if;

  insert into public.coupon_redemption_attempts (
    user_id,
    coupon_id,
    batch_id,
    succeeded
  )
  values (
    v_user_id,
    v_coupon_id,
    v_batch_id,
    true
  );

  insert into public.audit_events (user_id, event_type, metadata)
  values (
    v_user_id,
    'coupon_redeemed',
    jsonb_build_object(
      'coupon_id', v_coupon_id,
      'batch_id', v_batch_id,
      'product_id', v_product_id,
      'duration_days', v_duration_days,
      'valid_until', v_valid_until,
      'coupon_deleted', true
    )
  );

  delete from public.coupons
  where id = v_coupon_id;

  return jsonb_build_object(
    'ok', true,
    'product_code', v_product_code,
    'days_added', v_duration_days,
    'valid_until', v_valid_until
  );
end;
$$;

revoke all on function launcher.redeem_coupon(text)
  from public, anon;
grant execute on function launcher.redeem_coupon(text)
  to authenticated;

create or replace function launcher.admin_delete_coupon_batch(
  p_actor_id uuid,
  p_batch_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = public, launcher, pg_temp
as $$
declare
  v_batch public.coupon_batches%rowtype;
  v_coupon_count integer;
begin
  perform launcher.assert_admin_actor(p_actor_id);

  select *
  into v_batch
  from public.coupon_batches
  where id = p_batch_id
  for update;

  if not found then
    return false;
  end if;
  if v_batch.revoked_at is null then
    raise exception 'coupon_batch_must_be_revoked';
  end if;
  if exists (
    select 1
    from public.coupons
    where batch_id = p_batch_id
      and status = 'redeemed'
  ) or exists (
    select 1
    from public.coupon_redemption_attempts
    where batch_id = p_batch_id
      and succeeded
  ) then
    raise exception 'redeemed_coupon_batch_cannot_be_deleted';
  end if;

  select count(*)::integer
  into v_coupon_count
  from public.coupons
  where batch_id = p_batch_id;

  insert into public.audit_events (user_id, event_type, metadata)
  values (
    p_actor_id,
    'coupon_batch_deleted',
    jsonb_build_object(
      'batch_id', p_batch_id,
      'product_id', v_batch.product_id,
      'coupon_count', v_coupon_count,
      'created_at', v_batch.created_at
    )
  );

  delete from public.coupons where batch_id = p_batch_id;
  delete from public.coupon_batches where id = p_batch_id;
  return true;
end;
$$;

revoke all on function launcher.admin_delete_coupon_batch(uuid, uuid)
  from public, anon, authenticated;
grant execute on function launcher.admin_delete_coupon_batch(uuid, uuid)
  to service_role;
