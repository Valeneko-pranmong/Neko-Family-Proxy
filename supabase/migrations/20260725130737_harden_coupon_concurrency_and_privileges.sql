create index if not exists coupon_redemption_attempts_coupon_id_idx
  on public.coupon_redemption_attempts (coupon_id);

-- Customer clients use read-only RLS policies and SECURITY DEFINER RPCs.
-- Remove direct table mutation privileges as defense in depth.
revoke insert, update, delete, truncate, references, trigger
  on table
    public.profiles,
    public.products,
    public.licenses,
    public.installations,
    public.launcher_sessions,
    public.audit_events,
    public.coupon_batches,
    public.coupons,
    public.coupon_redemption_attempts
  from anon, authenticated;

create or replace function launcher.redeem_coupon(p_code text)
returns jsonb
language plpgsql
security definer
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_normalized text;
  v_code_hash text;
  v_attempt_count integer;
  v_coupon_id uuid;
  v_coupon_status text;
  v_redeemed_by uuid;
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
    c.redeemed_by,
    b.id,
    b.revoked_at,
    b.expires_at,
    b.product_id,
    p.code,
    b.duration_days
  into
    v_coupon_id,
    v_coupon_status,
    v_redeemed_by,
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
      succeeded,
      error_code
    )
    values (
      v_user_id,
      v_coupon_id,
      false,
      case
        when v_coupon_status = 'redeemed' and v_redeemed_by = v_user_id then 'already_redeemed'
        else 'invalid_coupon'
      end
    );
    return jsonb_build_object(
      'ok', false,
      'error',
      case
        when v_coupon_status = 'redeemed' and v_redeemed_by = v_user_id then 'already_redeemed'
        else 'invalid_coupon'
      end
    );
  end if;

  -- Different coupons for the same user/product can arrive concurrently.
  -- Serialize the license read/insert/update so only one active row is created.
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

  update public.coupons
  set
    status = 'redeemed',
    redeemed_by = v_user_id,
    redeemed_at = now()
  where id = v_coupon_id;

  insert into public.coupon_redemption_attempts (
    user_id,
    coupon_id,
    succeeded
  )
  values (
    v_user_id,
    v_coupon_id,
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
      'valid_until', v_valid_until
    )
  );

  return jsonb_build_object(
    'ok', true,
    'product_code', v_product_code,
    'days_added', v_duration_days,
    'valid_until', v_valid_until
  );
end;
$$;

revoke all on function launcher.redeem_coupon(text) from public;
grant execute on function launcher.redeem_coupon(text) to authenticated;
