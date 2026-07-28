-- Supabase installs pgcrypto in the extensions schema. Keep privileged
-- coupon functions on an explicit search_path so crypto helpers resolve
-- consistently in production.
alter function launcher.admin_generate_coupon_batch(
  uuid, text, integer, integer, timestamptz, text
) set search_path = public, launcher, extensions, pg_temp;

alter function launcher.redeem_coupon(text)
  set search_path = public, launcher, extensions, pg_temp;

alter function launcher.generate_coupon_batch(
  text, integer, integer, timestamptz, text
) set search_path = public, launcher, extensions, pg_temp;
