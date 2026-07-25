-- The Admin web console uses the actor-checked admin_* RPCs. These older
-- functions are retained for migration compatibility but must not remain part
-- of the client-facing API.
revoke all on function launcher.generate_coupon_batch(
  text,
  integer,
  integer,
  timestamptz,
  text
) from public, anon, authenticated, service_role;

revoke all on function launcher.revoke_coupon_batch(uuid)
  from public, anon, authenticated, service_role;
