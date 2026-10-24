# ============================================================================
#  ensure-netfilter2.ps1 - netfilter2 driver readiness (existing supported path)
# ----------------------------------------------------------------------------
#  Reuses EXACTLY the proven Netch/NFSDK registration mechanism that
#  NekoProxyCore itself uses (Netch/Controllers/NFController.cs):
#      1. copy bin\nfdriver.sys  ->  System32\drivers\netfilter2.sys
#      2. register via Redirector.bin export aio_register("netfilter2")
#         (= nf_registerDriver, creates/starts the kernel service)
#
#  Safety policy:
#    * core-manifest.json, nfdriver.sys, and Redirector.bin must match the
#      SHA-256 values pinned by the installer build. A mismatch fails closed
#      before any machine state is touched.
#    * An already-valid RUNNING driver is verified only - nothing is touched,
#      no elevation requested.
#    * A RUNNING driver whose on-disk bytes DIFFER from this bundle's approved
#      nfdriver.sys is treated as INCOMPATIBLE and is never silently
#      overwritten (exit 20).
#    * Registration/start requires admin rights; run under elevation when
#      changes are needed (the installer requests UAC only for this step).
#    * Elevated registration copies verified files into an admin-only staging
#      directory and loads Redirector.bin from there, so a user-writable
#      Core bundle cannot be swapped in after verification.
#    * The driver is a SHARED MACHINE PREREQUISITE: this script never deletes
#      or unregisters an existing working installation.
#
#  Usage:
#    ensure-netfilter2.ps1 -CoreBinDir <path> -CheckOnly `
#      -ExpectedCoreManifestSha256 <hex> `
#      -ExpectedRedirectorSha256 <hex> `
#      -ExpectedNfDriverSha256 <hex>
#      exit 0  = valid and running (nothing to do)
#      exit 10 = changes required (missing or stopped-without-file); rerun
#                elevated with -Apply
#      exit 20 = incompatible running/stopped-registered driver; refused
#      exit 21 = nfdriver.sys hash mismatch
#      exit 22 = Redirector.bin or dependent DLL hash mismatch
#      exit 24 = staged copy hash mismatch
#      exit 25 = core-manifest.json missing/hash/declaration mismatch
#      exit 26 = core-manifest.json unreadable/invalid
#      exit 30 = installed but stopped (valid bytes); rerun elevated -Apply
#      other   = error
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CoreBinDir,

    [switch]$CheckOnly,

    [switch]$Apply,

    [string]$ResultFile,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedCoreManifestSha256,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedRedirectorSha256,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedNfDriverSha256,

    [string]$StageRoot = ''
)

$ErrorActionPreference = 'Stop'

function Out-Result([string]$Message) {
    Write-Output $Message
    if ($ResultFile) {
        try { Set-Content -LiteralPath $ResultFile -Value $Message -Encoding Ascii } catch {}
    }
}

function Get-Sha256([string]$Path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        return ([System.BitConverter]::ToString(
            $sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($stream) { $stream.Dispose() }
        if ($sha) { $sha.Dispose() }
    }
}

function Assert-Sha256([string]$Value, [string]$Name) {
    if ($Value -notmatch '^[0-9a-fA-F]{64}$') {
        Out-Result "FAIL: invalid pinned $Name"
        exit 2
    }
    return $Value.ToLowerInvariant()
}

$ExpectedCoreManifestSha256 = Assert-Sha256 $ExpectedCoreManifestSha256 'core-manifest.sha256'
$ExpectedRedirectorSha256 = Assert-Sha256 $ExpectedRedirectorSha256 'redirector.sha256'
$ExpectedNfDriverSha256 = Assert-Sha256 $ExpectedNfDriverSha256 'nfdriver.sha256'

if (-not $StageRoot) {
    $programData = $env:ProgramData
    if (-not $programData) { $programData = 'C:\ProgramData' }
    $StageRoot = Join-Path $programData 'NekoFamily\driver-stage'
}

$coreRoot = Split-Path -Parent $CoreBinDir
$manifestPath = Join-Path $coreRoot 'core-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    Out-Result "FAIL: core-manifest.json missing in $CoreBinDir"
    exit 25
}
if ((Get-Sha256 $manifestPath) -ne $ExpectedCoreManifestSha256) {
    Out-Result 'FAIL: core-manifest.json hash mismatch'
    exit 25
}
try {
    $manifest = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
} catch {
    Out-Result "FAIL: core-manifest.json unreadable: $($_.Exception.Message)"
    exit 26
}

$manifestHashes = @{}
if ($manifest.files -is [System.Array]) {
    foreach ($entry in $manifest.files) {
        $key = ([string]$entry.path -replace '/', '\').ToLowerInvariant()
        $manifestHashes[$key] = ([string]$entry.sha256).ToLowerInvariant()
    }
} elseif ($manifest.files) {
    foreach ($prop in $manifest.files.PSObject.Properties) {
        $key = ([string]$prop.Name -replace '/', '\').ToLowerInvariant()
        $manifestHashes[$key] = ([string]$prop.Value).ToLowerInvariant()
    }
}
if ($manifestHashes.Count -eq 0) {
    Out-Result 'FAIL: core-manifest.json declares no files'
    exit 26
}

function Get-ManifestHash([string]$RelativePath) {
    $key = ($RelativePath -replace '/', '\').ToLowerInvariant()
    if (-not $manifestHashes.ContainsKey($key)) { return $null }
    return $manifestHashes[$key]
}

function Assert-BundleFile(
    [string]$FileName,
    [string]$ExpectedHash,
    [string]$Label,
    [int]$ExitCode
) {
    $path = Join-Path $CoreBinDir $FileName
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Out-Result "FAIL: bundle $Label missing in $CoreBinDir"
        exit 2
    }
    $actual = Get-Sha256 $path
    if ($actual -ne $ExpectedHash) {
        Out-Result "FAIL: bundle $Label hash mismatch"
        exit $ExitCode
    }
    $manifestHash = Get-ManifestHash ('bin/' + $FileName)
    if (-not $manifestHash) {
        Out-Result "FAIL: $Label not declared in core-manifest.json"
        exit 25
    }
    if ($manifestHash -ne $ExpectedHash) {
        Out-Result "FAIL: $Label manifest hash mismatch"
        exit 25
    }
    return $path
}

$srcDriver = Assert-BundleFile 'nfdriver.sys' $ExpectedNfDriverSha256 'nfdriver.sys' 21
$srcRedirector = Assert-BundleFile 'Redirector.bin' $ExpectedRedirectorSha256 'Redirector.bin' 22
$bundleBytes = $ExpectedNfDriverSha256
$sysDriver = Join-Path $env:SystemRoot 'System32\drivers\netfilter2.sys'
$svcName = 'netfilter2'

function New-SecureStage([string]$Root) {
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    New-Item -ItemType Directory -Path $rootFull -Force | Out-Null
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sidValue in @('S-1-5-32-544', 'S-1-5-18')) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier($sidValue)
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $rootFull -AclObject $acl
    $stage = Join-Path $rootFull ([Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    return $stage
}

$service = Get-Service -Name $svcName -ErrorAction SilentlyContinue

# ---- classify current machine state ----------------------------------------
if (-not $service -and -not (Test-Path -LiteralPath $sysDriver)) {
    # clean machine -> registration required (elevated)
    if ($CheckOnly) { Write-Output 'netfilter2 absent; registration required'; exit 10 }
} else {
    if (Test-Path -LiteralPath $sysDriver -PathType Leaf) {
        $sysHash = Get-Sha256 $sysDriver
        if ($sysHash -ne $bundleBytes) {
            Out-Result ('incompatible netfilter2.sys present (hash differs from ' +
                'approved bundle); overwrite refused')
            exit 20
        }
    }
    if ($service -and $service.Status -eq 'Running') {
        Write-Output 'netfilter2 valid and RUNNING (verify-only)'
        exit 0
    }
    if ($service) {
        # registered but stopped, bytes valid -> start requires elevation
        if ($CheckOnly) { Write-Output 'netfilter2 present but stopped'; exit 30 }
    }
}
# falling through here (CheckOnly) should not happen
if ($CheckOnly) { Write-Output 'netfilter2 state unresolved'; exit 10 }

# ---- Apply (elevated): verify, stage, register, start, verify --------------
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Out-Result 'FAIL: -Apply requires elevation'
    exit 2
}

$stage = $null
$interopLoaded = $false
try {
    try {
        $stage = New-SecureStage $StageRoot
    } catch {
        Out-Result "FAIL: creating secure stage failed: $($_.Exception.Message)"
        exit 3
    }

    Copy-Item -LiteralPath $srcDriver -Destination (Join-Path $stage 'nfdriver.sys') -Force
    Copy-Item -LiteralPath $srcRedirector -Destination (Join-Path $stage 'Redirector.bin') -Force

    $binDlls = Get-ChildItem -LiteralPath $CoreBinDir -File -Filter '*.dll' -ErrorAction SilentlyContinue
    foreach ($dll in $binDlls) {
        $relative = 'bin/' + $dll.Name
        $expected = Get-ManifestHash $relative
        if (-not $expected) { continue }
        $actual = Get-Sha256 $dll.FullName
        if ($actual -ne $expected) {
            Out-Result "FAIL: $relative hash mismatch"
            exit 22
        }
        Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $stage $dll.Name) -Force
    }

    if ((Get-Sha256 (Join-Path $stage 'nfdriver.sys')) -ne $ExpectedNfDriverSha256) {
        Out-Result 'FAIL: staged nfdriver.sys hash mismatch'
        exit 24
    }
    if ((Get-Sha256 (Join-Path $stage 'Redirector.bin')) -ne $ExpectedRedirectorSha256) {
        Out-Result 'FAIL: staged Redirector.bin hash mismatch'
        exit 24
    }

    if (-not (Test-Path -LiteralPath $sysDriver -PathType Leaf)) {
        try {
            Copy-Item -LiteralPath (Join-Path $stage 'nfdriver.sys') -Destination $sysDriver -Force
        } catch {
            Out-Result "FAIL: copying nfdriver.sys failed: $($_.Exception.Message)"
            exit 4
        }
    }

    # Register through the proven Redirector.bin entry point (nf_registerDriver).
    $addType = @'
using System;
using System.Runtime.InteropServices;
public static class NfInterop {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool SetDllDirectory(string lpPathName);

    [DllImport("Redirector.bin", CallingConvention = CallingConvention.Cdecl)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool aio_register([MarshalAs(UnmanagedType.LPWStr)] string value);
}
'@
    try {
        Add-Type -TypeDefinition $addType -ErrorAction Stop | Out-Null
        $interopLoaded = $true
    } catch {
        Out-Result "FAIL: interop type load failed: $($_.Exception.Message)"
        exit 5
    }

    [NfInterop]::SetDllDirectory($stage) | Out-Null
    $registered = $false
    try {
        $registered = [NfInterop]::aio_register($svcName)
    } catch {
        Out-Result "FAIL: aio_register threw: $($_.Exception.Message)"
        exit 6
    }
    if (-not $registered) {
        Out-Result 'FAIL: Redirector aio_register(netfilter2) returned false'
        exit 7
    }
} finally {
    if ($interopLoaded) {
        try { [NfInterop]::SetDllDirectory($null) | Out-Null } catch {}
    }
    if ($stage -and (Test-Path -LiteralPath $stage)) {
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# Ensure the kernel service is running.
$service = Get-Service -Name $svcName -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -ne 'Running') {
        try {
            Start-Service -Name $svcName -ErrorAction Stop
        } catch {
            Out-Result "FAIL: starting netfilter2 service failed: $($_.Exception.Message)"
            exit 8
        }
    }
    $service.Refresh()
    if ($service.Status -eq 'Running') {
        Write-Output 'netfilter2 registered and RUNNING'
        exit 0
    }
    Out-Result ("FAIL: netfilter2 not running after registration (state: " +
        "$($service.Status))")
    exit 9
}
Out-Result 'FAIL: netfilter2 service absent after successful registration'
exit 9
