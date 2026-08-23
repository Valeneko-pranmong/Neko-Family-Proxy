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
#    * An already-valid RUNNING driver is verified only - nothing is touched,
#      no elevation requested.
#    * A RUNNING driver whose on-disk bytes DIFFER from this bundle's approved
#      nfdriver.sys is treated as INCOMPATIBLE and is never silently
#      overwritten (exit 20).
#    * Registration/start requires admin rights; run under elevation when
#      changes are needed (the installer requests UAC only for this step).
#    * The driver is a SHARED MACHINE PREREQUISITE: this script never deletes
#      or unregisters an existing working installation.
#
#  Usage:
#    ensure-netfilter2.ps1 -CoreBinDir <path> -CheckOnly
#      exit 0  = valid and running (nothing to do)
#      exit 10 = changes required (missing or stopped-without-file); rerun
#                elevated with -Apply
#      exit 20 = incompatible running/stopped-registered driver; refused
#      exit 30 = installed but stopped (valid bytes); rerun elevated -Apply
#                to start it
#      other   = error
#    ensure-netfilter2.ps1 -CoreBinDir <path> -Apply [-ResultFile <path>]
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CoreBinDir,

    [switch]$CheckOnly,

    [switch]$Apply,

    [string]$ResultFile
)

$ErrorActionPreference = 'Stop'

function Out-Result([string]$Message) {
    Write-Output $Message
    if ($ResultFile) {
        try { Set-Content -LiteralPath $ResultFile -Value $Message -Encoding UTF8 } catch {}
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

$sysDriver   = Join-Path $env:SystemRoot 'System32\drivers\netfilter2.sys'
$svcName     = 'netfilter2'
$bundleBytes = $null

$srcDriver = Join-Path $CoreBinDir 'nfdriver.sys'
if (Test-Path -LiteralPath $srcDriver -PathType Leaf) {
    $bundleBytes = Get-Sha256 $srcDriver
} else {
    Out-Result "FAIL: bundle nfdriver.sys missing in $CoreBinDir"
    exit 2
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

# ---- Apply (elevated): copy-if-needed, register, start, verify -------------
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Out-Result 'FAIL: -Apply requires elevation'
    exit 2
}

if (-not (Test-Path -LiteralPath $sysDriver -PathType Leaf)) {
    try {
        Copy-Item -LiteralPath $srcDriver -Destination $sysDriver -Force
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
} catch {
    Out-Result "FAIL: interop type load failed: $($_.Exception.Message)"
    exit 5
}

[NfInterop]::SetDllDirectory($CoreBinDir) | Out-Null
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
