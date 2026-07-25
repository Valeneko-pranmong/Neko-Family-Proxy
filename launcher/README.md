# Launcher V2

This directory is the rebuilt desktop launcher. The sanitized legacy
implementation is preserved on the separate `v1` branch for reference only.

## Run from source

```powershell
Set-Location launcher
$env:PYTHONPATH = "src"
python -m neko_launcher.main
```

The V2 shell currently demonstrates the state-driven UI and process lifecycle.
Authentication, entitlement checks, and the remaining Windows integrations are
added through the application and infrastructure ports instead of being placed
inside the UI.

The customer-facing UI preserves the original pink Neko Family brand palette,
logo, and Windows application icon. Shared colors live in `ui/theme.py`.
