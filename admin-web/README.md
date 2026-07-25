# Neko Control Room

Private admin console for Neko Family Proxy. It manages users, licenses,
coupon batches, live sessions, and the audit trail through the Supabase
server API.

## Runtime configuration

Copy `.env.example` to `.env.local` for local development. The
`SUPABASE_SECRET_KEY` must stay server-side; never expose it in browser code
or commit it to the repository. `ADMIN_EMAIL_ALLOWLIST` is required and must
contain the workspace-authenticated email addresses allowed to open the
console.

Every allowlisted email must also belong to an active Supabase Auth user whose
`public.profiles` row has `role = 'admin'` and `status = 'active'`. The server
checks both conditions before reading data or invoking an Admin command.
Mutations go through the `launcher.admin_*` RPC functions so validation,
session revocation, and audit logging happen in one database transaction.

When the Supabase variables are not present, the local UI runs in a clearly
marked demo mode for an allowlisted workspace user so the layout can be
reviewed safely.

## Commands

```bash
npm ci
npm run dev
npm run build
npm run lint
npm test
npm audit --omit=dev --audit-level=high
```

Production dependency overrides are pinned in `package.json` and the lockfile
so patched PostCSS and Sharp builds are used consistently.
