# Neko Family Launcher

Desktop launcher for Supabase username/password membership, entitlement checks,
ProxyCore, and user-selected PSO2 Tweaker startup.

## Set up

```powershell
python -m pip install -e ".[dev,release]"
```

The launcher contains the Supabase project URL and publishable client key.
Publishable keys are safe for desktop clients; never place a
secret/service-role key in the launcher.

Run from source:

```powershell
python -m neko_launcher.main
```

## Customer flow

1. Register with a username, password, and real recovery email.
2. Sign in with the username; the Launcher derives the deterministic,
   non-PII Supabase Auth identifier locally.
3. Request a password-reset link from the **ลืมรหัสผ่าน** tab without exposing
   whether an account exists.
4. Check remaining entitlement time or redeem a coupon.
5. Start the embedded ProxyCore runtime.
6. Select `Tweaker.exe`; the launcher remembers the path.
7. Start Tweaker only while authentication, entitlement, session, and Proxy
   checks remain valid.

`PASSWORD_RESET_REDIRECT_URL` in
`src/neko_launcher/infrastructure/defaults.py` must remain empty until the
permanent Vercel production URL is deployed and allow-listed in Supabase Auth.
Do not embed a preview URL in a Launcher release.

## Validation

```powershell
python -m ruff check src tests
python -m pytest -q -m "not integration"
```

Integration tests require disposable Supabase credentials:

```powershell
python -m pytest -q -m integration
```

## One-file build

An approved `../ProxyCore/` directory must exist during the build:

```powershell
python -m PyInstaller --clean --noconfirm NekoLauncher.spec
```

The output is `dist/NekoLauncher.exe`. ProxyCore and the publishable client
configuration are embedded. The publishable key is extractable by design;
never embed a secret/service-role key.
