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
      'coupon_batch_revoked'
    )
  );

create table public.coupon_batches (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete restrict,
  duration_days integer not null check (duration_days between 1 and 3650),
  quantity integer not null check (quantity between 1 and 500),
  expires_at timestamptz,
  note text check (note is null or length(note) <= 500),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  check (expires_at is null or expires_at > created_at)
);

create index coupon_batches_product_id_idx
  on public.coupon_batches (product_id);

create index coupon_batches_created_by_idx
  on public.coupon_batches (created_by);

create table public.coupons (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid not null references public.coupon_batches(id) on delete restrict,
  code_hash text not null unique check (code_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'active' check (status in ('active', 'redeemed', 'revoked')),
  redeemed_by uuid references auth.users(id) on delete set null,
  redeemed_at timestamptz,
  created_at timestamptz not null default now(),
  check (
    (status = 'redeemed' and redeemed_by is not null and redeemed_at is not null)
    or
    (status in ('active', 'revoked') and redeemed_by is null and redeemed_at is null)
  )
);

create index coupons_batch_id_idx on public.coupons (batch_id);
create index coupons_redeemed_by_idx on public.coupons (redeemed_by);

create table public.coupon_redemption_attempts (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  coupon_id uuid references public.coupons(id) on delete set null,
  succeeded boolean not null default false,
  error_code text,
  attempted_at timestamptz not null default now()
);

create index coupon_redemption_attempts_user_time_idx
  on public.coupon_redemption_attempts (user_id, attempted_at desc);

alter table public.coupon_batches enable row level security;
alter table public.coupons enable row level security;
alter table public.coupon_redemption_attempts enable row level security;

create policy coupon_batches_admin_select
  on public.coupon_batches for select
  to authenticated
  using (
    exists (
      select 1
      from public.profiles p
      where p.id = (select auth.uid())
        and p.role = 'admin'
        and p.status = 'active'
    )
  );

create policy coupons_admin_select
  on public.coupons for select
  to authenticated
  using (
    exists (
      select 1
      from public.profiles p
      where p.id = (select auth.uid())
        and p.role = 'admin'
        and p.status = 'active'
    )
  );

create or replace function launcher.generate_coupon_batch(
  p_product_code text,
  p_duration_days integer,
  p_quantity integer,
  p_expires_at timestamptz default null,
  p_note text default null
)
returns table(batch_id uuid, code text)
language plpgsql
security definer
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_product_id uuid;
  v_batch_id uuid;
  v_secret text;
  v_normalized text;
  v_counter integer;
begin
  if v_user_id is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;

  if not exists (
    select 1
    from public.profiles p
    where p.id = v_user_id
      and p.role = 'admin'
      and p.status = 'active'
  ) then
    raise exception 'not_authorized' using errcode = '42501';
  end if;

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
    v_user_id
  )
  returning id into v_batch_id;

  for v_counter in 1..p_quantity loop
    loop
      v_secret := upper(encode(gen_random_bytes(16), 'hex'));
      v_normalized := 'NEKO' || v_secret;
      begin
        insert into public.coupons (batch_id, code_hash)
        values (v_batch_id, digest(v_normalized, 'sha256'));
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
    v_user_id,
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

create or replace function launcher.revoke_coupon_batch(p_batch_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public, launcher, pg_temp
as $$
declare
  v_user_id uuid := auth.uid();
  v_count integer;
begin
  if v_user_id is null then
    raise exception 'not_authenticated' using errcode = '28000';
  end if;

  if not exists (
    select 1
    from public.profiles p
    where p.id = v_user_id
      and p.role = 'admin'
      and p.status = 'active'
  ) then
    raise exception 'not_authorized' using errcode = '42501';
  end if;

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
      v_user_id,
      'coupon_batch_revoked',
      jsonb_build_object('batch_id', p_batch_id)
    );
  end if;

  return v_count > 0;
end;
$$;

revoke all on function launcher.generate_coupon_batch(text, integer, integer, timestamptz, text) from public;
revoke all on function launcher.redeem_coupon(text) from public;
revoke all on function launcher.revoke_coupon_batch(uuid) from public;

grant execute on function launcher.generate_coupon_batch(text, integer, integer, timestamptz, text) to authenticated;
grant execute on function launcher.redeem_coupon(text) to authenticated;
grant execute on function launcher.revoke_coupon_batch(uuid) to authenticated;
