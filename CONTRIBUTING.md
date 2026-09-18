# Contributing to Neko Family Proxy

First off, thank you for considering contributing to Neko Family Proxy! It's people like you that make open-source software great.

## Code of Conduct

By participating in this project, you are expected to uphold standard open-source professional conduct. Be respectful, constructive, and inclusive.

## Development Setup

To ensure code quality and security, please run the following local checks before submitting any pull request:

```powershell
# 1. Run repository safety checks (Credential leak prevention)
python scripts/check_repository_safety.py

# 2. Run Ruff linter and formatter
Set-Location launcher
python -m ruff check src tests

# 3. Run automated tests
python -m pytest -q -m "not integration"
```

## Contribution Guidelines

Before committing your changes, ensure you meet the following baseline requirements:

- **Security First**: 
  - Never put Supabase secret/service-role keys, Ed25519 signing keys, or customer data in the client source.
  - Check `git diff --check` to avoid whitespace errors or accidental secret leaks.
- **Environment & Ignored Files**: Keep `.env.local`, build output (`dist/`, `build/`), caches, and ProxyCore binaries out of Git.
- **Database Migrations**: Preserve all Supabase migrations in `supabase/migrations/` unless the database is intentionally rebuilt from a new baseline. Do not rewrite historical migrations.
- **Testing**: Live Supabase integration tests use disposable accounts through the manual `Supabase integration` workflow. Do not run integration tests against production instances.
- **Verification**: Verify a self-contained build with an approved local ProxyCore bundle before submitting a Pull Request.

## Pull Request Process

1. Fork the repository and create your branch from `main`.
2. Ensure your code passes all local checks and tests.
3. Update documentation (like README or inline docs) if you are introducing new features.
4. Describe your changes clearly in the Pull Request description, linking any relevant issues.
5. Wait for maintainer review. All PRs must pass automated CI checks and security reviews before merging.
