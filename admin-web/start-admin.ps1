$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
  Copy-Item "admin-api/.env.example" ".env"
  Write-Host "Created .env. Set SUPABASE_SECRET_KEY, then run this script again." -ForegroundColor Yellow
  exit 1
}

npm run build:standalone
node admin-api/src/server.mjs
