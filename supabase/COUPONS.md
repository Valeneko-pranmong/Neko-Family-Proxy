# Coupon workflow

## Roles

- Customers register and sign in with Supabase Auth.
- Admins receive payment outside the application and generate coupon batches.
- The launcher redeems a coupon through the `launcher.redeem_coupon` RPC.
- Clients never write directly to `licenses`, `coupons`, or `coupon_batches`.

## Admin workflow

1. Sign in with an account whose `public.profiles.role` is `admin`.
2. Choose the product, number of access days, quantity, optional coupon expiry, and an internal note.
3. Call `launcher.generate_coupon_batch`.
4. Copy or export the returned coupon codes immediately. The plaintext codes are returned once and are never stored in the database.
5. Send one coupon to the customer.
6. Revoke the entire unused portion of a batch with `launcher.revoke_coupon_batch` if the batch is exposed or issued by mistake.

Coupon format:

```text
NEKO-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX
```

Each coupon contains 128 bits of cryptographically secure randomness. The database stores only a SHA-256 hash of the normalized coupon.

## Customer workflow

1. Register or sign in.
2. Open the Redeem Coupon screen.
3. Enter the coupon.
4. The server validates the account, coupon, batch, expiry, and previous redemption state.
5. The server creates or extends the active license in the same database transaction that marks the coupon as redeemed.
6. The launcher refreshes entitlement state and claims a launcher session.

## Security behavior

- Coupon redemption is limited to ten attempts per user in ten minutes.
- A coupon can be redeemed once.
- Concurrent redemptions of the same coupon are serialized with a database advisory lock and row lock.
- Coupon plaintext is never written to audit logs or database tables.
- Admin authorization comes from `public.profiles.role`, which customers cannot update through RLS.
- The publishable key is safe for the launcher; secret/service-role keys must not be embedded in it.

## Bootstrap

The first admin must sign up normally and then have `public.profiles.role` changed to `admin` through a trusted administrative path such as the Supabase SQL editor. Do not expose a client-side RPC that promotes users to admin.
