# ============================================================================
#  verify-core-install.ps1 - post-install Core manifest verification
# ----------------------------------------------------------------------------
#  Verifies the installed external ProxyCore runtime against its
#  core-manifest.json. Exits 0 only when ALL of the following hold:
#    * manifest source_commit == candidate Core authority (-ExpectedCommit / -CoreAuthority)
#    * every declared file is present with the declared SHA-256
#    * v2ray-sn.exe present, hash correct (pinned approved value)
#    * runtime-settings.nkps present
#    * no runtime-settings.key and no plaintext production settings file
#
#  Usage: powershell -File verify-core-install.ps1 -CoreDir <path> -ExpectedCommit <authority>
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CoreDir,

    [Parameter(Mandatory = $false)]
    [Alias('CoreAuthority')]
    [string]$ExpectedCommit = ''
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

if ([string]::IsNullOrWhiteSpace($ExpectedCommit) -or ($manifest.source_commit -ne $ExpectedCommit)) {
    Fail 4 ("FAIL: source_commit mismatch: expected $ExpectedCommit, got " +
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

# --- manifest files array validation ---
if (-not ($manifest.files -is [System.Array])) {
    Fail 6 "FAIL: manifest files must be a non-empty array"
}
if ($manifest.files.Count -eq 0) {
    Fail 5 "FAIL: manifest declares zero files"
}

$resolvedCore = [System.IO.Path]::GetFullPath($CoreDir)
$resolvedCoreWithSep = $resolvedCore.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

$seenPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
$bad = New-Object 'System.Collections.Generic.List[string]'
$total = 0

foreach ($entry in $manifest.files) {
    $total++
    if ($null -eq $entry -or -not ($entry -is [System.Management.Automation.PSCustomObject])) {
        Fail 6 "FAIL: manifest entry must be a JSON object"
    }

    $props = @($entry.PSObject.Properties)
    if ($props.Count -ne 3 -or
        (-not $entry.PSObject.Properties['path']) -or
        (-not $entry.PSObject.Properties['size']) -or
        (-not $entry.PSObject.Properties['sha256'])) {
        Fail 6 "FAIL: manifest entry must contain exactly path, size, and sha256 fields"
    }

    $rawPath = [string]$entry.path
    if ([string]::IsNullOrWhiteSpace($rawPath)) {
        Fail 6 "FAIL: manifest entry path must not be empty"
    }

    # Safe relative path validation
    if ($rawPath -match '(^|[\\/])\.\.([\\/]|$)' -or
        $rawPath.StartsWith('\') -or $rawPath.StartsWith('/') -or
        $rawPath -match '^[a-zA-Z]:' -or
        [System.IO.Path]::IsPathRooted($rawPath)) {
        Fail 6 "FAIL: unsafe relative path: $rawPath"
    }

    $rel = $rawPath -replace '/', '\'
    $targetPath = [System.IO.Path]::GetFullPath((Join-Path $resolvedCore $rel))
    if (-not $targetPath.StartsWith($resolvedCoreWithSep, [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail 6 "FAIL: path escapes CoreDir: $rawPath"
    }

    $normalizedRel = $rel.ToLowerInvariant()
    if ($seenPaths.Contains($normalizedRel)) {
        Fail 6 "FAIL: duplicate path declared in manifest: $rawPath"
    }
    $seenPaths.Add($normalizedRel) | Out-Null

    # Validate size type and value
    if (-not ($entry.size -is [int] -or $entry.size -is [long] -or $entry.size -is [int64]) -or $entry.size -lt 0) {
        Fail 6 "FAIL: invalid size for entry $rawPath"
    }
    $expectedSize = [int64]$entry.size

    # Validate sha256 format
    $rawSha = [string]$entry.sha256
    if (-not ($rawSha -match '^[0-9a-fA-F]{64}$')) {
        Fail 6 "FAIL: invalid sha256 for entry $rawPath"
    }
    $expectedSha = $rawSha.ToLowerInvariant()

    # Check file on disk
    if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
        $bad.Add("MISSING $rel") | Out-Null
        continue
    }

    $fileItem = Get-Item -LiteralPath $targetPath
    if ($fileItem.Length -ne $expectedSize) {
        $bad.Add("SIZE $rel (expected $expectedSize, got $($fileItem.Length))") | Out-Null
        continue
    }

    $got = Get-Sha256 $targetPath
    if ($got -ne $expectedSha) {
        $bad.Add("HASH $rel (expected $expectedSha, got $got)") | Out-Null
    }
}

if ($bad.Count -gt 0) {
    $head = ($bad | Select-Object -First 8) -join '; '
    Fail 6 "FAIL: $($bad.Count)/$total declared files bad: $head"
}

# --- v2ray-sn.exe pinned approved hash ---
$v2rayExpected = 'a219f435671fb214c0c530084c65e576fdc1404f40b187b5586e869d2a3e4dff'
$v2rayRel = 'bin\v2ray-sn.exe'
$v2rayEntry = $manifest.files | Where-Object {
    ($_.path -replace '/', '\').ToLowerInvariant() -eq $v2rayRel.ToLowerInvariant()
} | Select-Object -First 1

if (-not $v2rayEntry) {
    Fail 7 'FAIL: v2ray-sn.exe not declared by manifest'
}

$v2rayTarget = Join-Path $resolvedCore $v2rayRel
if (-not (Test-Path -LiteralPath $v2rayTarget -PathType Leaf)) {
    Fail 7 "FAIL: v2ray-sn.exe missing on disk"
}

$v2rayGot = Get-Sha256 $v2rayTarget
if ($v2rayGot -ne $v2rayExpected) {
    Fail 7 "FAIL: v2ray-sn.exe hash mismatch"
}

if (([string]$v2rayEntry.sha256).ToLowerInvariant() -ne $v2rayExpected) {
    Fail 7 "FAIL: manifest v2ray-sn.exe hash mismatch"
}

if ($manifest.v2ray_sn_exe_hash -and (([string]$manifest.v2ray_sn_exe_hash).ToLowerInvariant() -ne $v2rayExpected)) {
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
