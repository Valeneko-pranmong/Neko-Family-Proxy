# Contributing

## Local checks

```powershell
python scripts/check_repository_safety.py
Set-Location launcher
python -m ruff check src tests
python -m pytest -q -m "not integration"
```

Before committing:

- Keep `.env.local`, build output, caches, and ProxyCore out of Git.
- Never put Supabase secret/service-role keys or customer data in the client.
- Preserve all Supabase migrations unless the database is intentionally
  rebuilt from a new baseline.
- Verify a self-contained build with an approved local ProxyCore bundle.
- Check `git diff --check`.

Live Supabase integration tests use disposable accounts through the manual
`Supabase integration` workflow.
