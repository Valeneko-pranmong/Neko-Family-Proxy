# Supabase security and concurrency test plan

> **Status: CURRENT — reviewed 8 August 2026.** Run only with disposable test
> accounts and data.

Run this plan against disposable test accounts before enabling the Launcher
login, coupon, or session UI. Do not store test passwords, access tokens,
customer data, or secret/service-role keys in this repository.

## Prerequisites

- The `launcher` schema is exposed through the Data API.
- All migrations in `supabase/migrations/` are applied.
- Create two disposable Auth users through the normal Supabase Auth signup
  flow: one admin and one customer.
- Promote only the admin account through a trusted server-side or SQL workflow.
- Keep both profiles active for the positive-path tests.

## RLS and privilege tests

1. Confirm an unauthenticated client cannot read launcher-owned public tables.
2. Confirm the customer can read only their own profile, licenses,
   installations, and launcher sessions.
3. Confirm the customer cannot read another user's rows.
4. Confirm the customer cannot insert, update, or delete launcher-owned tables
   directly.
5. Confirm the customer cannot change `profiles.role`, `profiles.status`, or
   any license fields.
6. Confirm only an active admin can read coupon batches and coupon metadata.
7. Confirm audit events and coupon redemption attempts are unavailable through
   direct customer queries.

## Coupon tests

1. Confirm a customer cannot call `launcher.generate_coupon_batch`.
2. Generate a batch as the admin and save the returned plaintext codes only in
   an approved temporary location.
3. Confirm the database stores only 64-character lowercase SHA-256 hashes.
4. Redeem one coupon as the customer and confirm one active license is created.
5. Redeem the same coupon again and confirm it cannot extend the license twice.
6. Revoke a batch and confirm unused coupons from that batch cannot be redeemed.
7. Confirm an expired batch cannot be redeemed.
8. Submit ten invalid attempts within ten minutes and confirm later attempts are
   rate limited.
9. Redeem the same coupon concurrently and confirm exactly one request succeeds.
10. Redeem two different coupons for the same user/product concurrently and
    confirm there is still one active license whose expiry includes both
    successful extensions.
11. Confirm every generate, redeem, and revoke action creates the expected audit
    event without recording plaintext coupon codes.

## Session tests

1. Confirm `launcher.claim_session` fails without an active license.
2. Claim a session with a valid license and installation hash.
3. Claim a second session for the same user and confirm the first is revoked.
4. Confirm heartbeat succeeds only for the newest active session.
5. Confirm heartbeat fails for a revoked session and after license expiry.
6. Release the active session and confirm a second release is a safe no-op.
7. Confirm a suspended or banned profile cannot redeem coupons or keep using a
   launcher session.

## Completion gate

- All tests above pass using publishable keys and authenticated user sessions.
- No client uses a secret/service-role key.
- Supabase security advisors have no ERROR or WARN findings for this schema.
- Test coupons, sessions, licenses, and disposable Auth users are removed
  through an approved cleanup workflow.
