# ============================================================================
#  verify-core-install.ps1 - post-install Core manifest verification
# ----------------------------------------------------------------------------
#  Verifies the installed external ProxyCore runtime against its
#  core-manifest.json. Exits 0 only when ALL of the following hold:
#    * manifest source_commit == pinned Closed Beta Core authority
#    * every declared file is present with the declared SHA-256
#    * v2ray-sn.exe present, hash correct (pinned approved value)
#    * runtime-settings.nkps present
#    * no runtime-settings.key and no plaintext production settings file
#
#  Usage: powershell -File verify-core-install.ps1 -CoreDir <path>
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CoreDir
)

$ErrorActionPreference = 'Stop'

function Fail([int]$Code, [string]$Message) {
    Write-Output $Message
    exit $Code
}

$manifestPath = Join-Path $CoreDir 'core-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    Fail 3 "FAIL: missing core-manifest.json in $CoreDir"
}

try {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
} catch {
    Fail 3 "FAIL: core-manifest.json unreadable: $($_.Exception.Message)"
}

$expectedCommit = '33f97ae0110075089f39b1e123890f931417d907'
if ($manifest.source_commit -ne $expectedCommit) {
    Fail 4 ("FAIL: source_commit mismatch: expected $expectedCommit, got " +
        "$($manifest.source_commit)")
}

$sha256 = [System.Security.Cryptography.SHA256]::Create()
function Get-Sha256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ([System.BitConverter]::ToString(
            $sha256.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
    }
}

# --- all declared files present + hash match ---
$files = $manifest.files.PSObject.Properties
$total = 0
$bad = New-Object System.Collections.Generic.List[string]
foreach ($entry in $files) {
    $total++
    $rel = $entry.Name -replace '/', '\'
    $path = Join-Path $CoreDir $rel
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $bad.Add("MISSING $rel") | Out-Null
        continue
    }
    $got = Get-Sha256 $path
    if ($got -ne $entry.Value) {
        $bad.Add("HASH $rel") | Out-Null
    }
}
if ($total -eq 0) { Fail 5 'FAIL: manifest declares zero files' }
if ($bad.Count -gt 0) {
    $head = ($bad | Select-Object -First 8) -join '; '
    Fail 6 "FAIL: $($bad.Count)/$total declared files bad: $head"
}

# --- v2ray-sn.exe pinned approved hash ---
$v2rayRel = 'bin/v2ray-sn.exe'
if (-not $manifest.files.PSObject.Properties[$v2rayRel]) {
    Fail 7 'FAIL: v2ray-sn.exe not declared by manifest'
}
$v2rayExpected = 'a219f435671fb214c0c530084c65e576fdc1404f40b187b5586e869d2a3e4dff'
$v2rayGot = Get-Sha256 (Join-Path $CoreDir 'bin\v2ray-sn.exe')
if ($v2rayGot -ne $v2rayExpected) {
    Fail 7 "FAIL: v2ray-sn.exe hash mismatch"
}
if ($manifest.v2ray_sn_exe_hash -and $manifest.v2ray_sn_exe_hash -ne $v2rayExpected) {
    Fail 7 "FAIL: manifest v2ray_sn_exe_hash mismatch"
}

# --- protected settings present, plaintext key absent ---
if (-not (Test-Path -LiteralPath (Join-Path $CoreDir 'runtime-settings.nkps'))) {
    Fail 8 'FAIL: runtime-settings.nkps missing'
}
if (Test-Path -LiteralPath (Join-Path $CoreDir 'runtime-settings.key')) {
    Fail 8 'FAIL: plaintext runtime-settings.key present'
}

# --- no plaintext settings payloads anywhere in the installed tree ---
$plaintextHits = Get-ChildItem -LiteralPath $CoreDir -Recurse -File |
    Where-Object {
        $_.Name -match '^(?i)(runtime[-_]?settings|appsettings)\.(json|ini|conf|xml|txt)$' -or
        $_.Extension -in '.key', '.pem', '.pfx', '.env'
    }
if ($plaintextHits) {
    $names = ($plaintextHits | Select-Object -First 5 |
        ForEach-Object { $_.Name }) -join ', '
    Fail 9 "FAIL: plaintext settings/key-like files present: $names"
}

Write-Output "PASS: core manifest verified: $total/$total files OK; v2ray OK; nkps present; no plaintext settings"
exit 0
