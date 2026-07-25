# Neko Control Room

Private admin console for Neko Family Proxy. It manages users, licenses,
coupon batches, live sessions, and the audit trail through the Supabase
server API.

## Runtime configuration

Copy `.env.example` to `.env.local` for local development. The
`SUPABASE_SECRET_KEY` must stay server-side; never expose it in browser code
or commit it to the repository. `ADMIN_EMAIL_ALLOWLIST` is optional but
recommended for production.

When the Supabase variables are not present, the local UI runs in a clearly
marked demo mode so the layout can be reviewed safely.

## Commands

```bash
npm install
npm run dev
npm run build
npm run lint
```
