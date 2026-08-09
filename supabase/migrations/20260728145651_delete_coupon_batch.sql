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
      'coupon_batch_deleted',
      'admin_user_status_changed',
      'admin_license_revoked',
      'admin_license_extended',
      'admin_session_revoked'
    )
  );

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
