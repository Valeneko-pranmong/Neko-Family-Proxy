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

1. Register with a username and password.
2. Sign in with the username; the Launcher derives the deterministic,
   non-PII Supabase Auth identifier locally.
3. Contact an administrator if the password is forgotten; email reset is not
   part of the Launcher.
4. Change the password from the Launcher after signing in.
5. Check remaining entitlement time or redeem a coupon.
6. Start the embedded ProxyCore runtime.
7. Select `Tweaker.exe`; the launcher remembers the path.
8. Start Tweaker only while authentication, entitlement, session, and Proxy
   checks remain valid.

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
