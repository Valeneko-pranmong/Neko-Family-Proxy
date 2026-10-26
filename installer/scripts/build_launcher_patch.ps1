<#
.SYNOPSIS
    Build the NEKO FAMILY PROXY launcher login-fix patch installer.

.DESCRIPTION
    Stages the approved patched NekoLauncher.exe and compiles
    installer\patch\login-fix.iss with Inno Setup.

    This is a launcher-only test patch. It does not build a full 5.2.0
    installer and does not re-sign the release envelope.

.PARAMETER LauncherPath
    Patched launcher to package. Defaults to the Python 3.12/Tcl 8.6 build.

.PARAMETER OutputDir
    Installer output directory. Defaults to launcher\dist.

.PARAMETER IsccPath
    Inno Setup ISCC.exe path. Auto-detected when omitted.

.PARAMETER SkipHashCheck
    Allow a different launcher hash. Use only when intentionally replacing
    the approved patch binary.
#>

#Requires -Version 5.1

[CmdletBinding()]
param(
    [string]$LauncherPath,
    [string]$OutputDir,
    [string]$IsccPath,
    [switch]$SkipHashCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$expectedSha256 = 'c7ae2c148b9f92f47cbc83401f09c797771bc737c3e65ffc56f3bc57c40e4a2b'

if (-not $LauncherPath) {
    $LauncherPath = Join-Path $repo 'launcher\dist\NekoLauncher-login-fix-py312.exe'
}
if (-not (Test-Path -LiteralPath $LauncherPath)) {
    throw "Patched launcher not found: $LauncherPath"
}
$LauncherPath = (Resolve-Path -LiteralPath $LauncherPath).Path
$launcherSha256 = (Get-FileHash -LiteralPath $LauncherPath -Algorithm SHA256).Hash.ToLowerInvariant()

if (-not $SkipHashCheck -and $launcherSha256 -ne $expectedSha256) {
    throw "Launcher SHA-256 mismatch. Expected $expectedSha256, got $launcherSha256. Use -SkipHashCheck only for an intentional replacement."
}

if (-not $OutputDir) {
    $OutputDir = Join-Path $repo 'launcher\dist'
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path

$payloadDir = Join-Path $env:TEMP 'neko-launcher-patch-payload'
if (Test-Path -LiteralPath $payloadDir) {
    Remove-Item -LiteralPath $payloadDir -Recurse -Force
}
New-Item -ItemType Directory -Path $payloadDir -Force | Out-Null
Copy-Item -LiteralPath $LauncherPath -Destination (Join-Path $payloadDir 'NekoLauncher.exe') -Force

if (-not $IsccPath) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
    )
    $IsccPath = $candidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath)) {
    throw 'Inno Setup 6 ISCC.exe was not found. Install Inno Setup 6 or pass -IsccPath.'
}

$issPath = Join-Path $repo 'installer\patch\login-fix.iss'
if (-not (Test-Path -LiteralPath $issPath)) {
    throw "Installer source not found: $issPath"
}

Write-Host "Launcher : $LauncherPath"
Write-Host "SHA-256  : $launcherSha256"
Write-Host "Output   : $OutputDir"
Write-Host "ISCC     : $IsccPath"

$arguments = @(
    "/DPayloadDir=$payloadDir",
    "/DExpectedPatchSha256=$launcherSha256",
    "/O$OutputDir",
    $issPath
)
& $IsccPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "ISCC failed with exit code $LASTEXITCODE"
}

$installerPath = Join-Path $OutputDir 'NekoLauncher-Patch-5.2.0-login-fix.exe'
if (-not (Test-Path -LiteralPath $installerPath)) {
    throw "Expected installer was not produced: $installerPath"
}

$installer = Get-Item -LiteralPath $installerPath
$installerSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$record = [ordered]@{
    built_at            = (Get-Date).ToString('o')
    purpose             = 'launcher login-fix test patch'
    launcher_path       = $LauncherPath
    launcher_sha256     = $launcherSha256
    installer_path      = $installerPath
    installer_size_bytes = $installer.Length
    installer_sha256    = $installerSha256
    note                = 'Launcher-only patch; Core, state, trust, and release envelope are unchanged.'
}
$recordPath = Join-Path $OutputDir 'NekoLauncher-Patch-5.2.0-login-fix.build.json'
$record | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $recordPath -Encoding UTF8

Write-Host ''
Write-Host 'Patch installer built successfully.'
Write-Host "Installer : $installerPath"
Write-Host "Size      : $($installer.Length) bytes"
Write-Host "SHA-256   : $installerSha256"
Write-Host "Record    : $recordPath"
