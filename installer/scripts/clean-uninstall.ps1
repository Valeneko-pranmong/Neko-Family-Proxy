<#
.SYNOPSIS
    Cleanly uninstall NEKO FAMILY PROXY for the current user.

.DESCRIPTION
    Runs the official Inno Setup uninstaller, waits for it to finish, then
    removes only known NEKO leftovers:
      - %LOCALAPPDATA%\NEKO FAMILY
      - %LOCALAPPDATA%\NekoFamilyProxy
      - Start Menu / Desktop shortcuts
      - the NEKO uninstall registry key
      - the "Neko Family Launcher" Windows Credential Manager target

    The shared netfilter2 driver is intentionally PRESERVED. This script never
    stops, deletes, or re-registers netfilter2 and never touches other users'
    profiles.

.PARAMETER DryRun
    Show what would be removed and which uninstaller would run. No changes.

.PARAMETER Force
    Skip the typed confirmation. Also allows removing a version other than
    5.2.0 and running from an elevated shell.

.PARAMETER KeepLogs
    Copy launcher/support logs to a backup folder before uninstalling.

.PARAMETER LogBackupPath
    Destination for -KeepLogs. Defaults to Desktop\NekoUninstallLogs-<time>.

.PARAMETER TimeoutSeconds
    Maximum wait for the uninstaller process. Default: 180.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\clean-uninstall.ps1 -DryRun

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\clean-uninstall.ps1 -KeepLogs

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\clean-uninstall.ps1 -Force
#>

#Requires -Version 5.1

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Force,
    [switch]$KeepLogs,
    [string]$LogBackupPath,
    [int]$TimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$script:LogFile = Join-Path $env:TEMP ("neko-clean-uninstall-{0}.log" -f $script:Stamp)
$script:Problems = New-Object System.Collections.Generic.List[string]
$script:AppRoot = Join-Path $env:LOCALAPPDATA 'NEKO FAMILY'
$script:LogRoot = Join-Path $env:LOCALAPPDATA 'NekoFamilyProxy'
$script:KnownUninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{D4A7C182-6B3E-4F19-9C05-2E8AF7B31D64}_is1'
$script:AppDisplayName = 'NEKO FAMILY PROXY'
$script:CredentialTarget = 'Neko Family Launcher'

function Write-Log {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR')][string]$Level = 'INFO'
    )

    $line = '[{0}] [{1}] {2}' -f (Get-Date -Format 'HH:mm:ss'), $Level, $Message
    switch ($Level) {
        'WARN'  { Write-Host $line -ForegroundColor Yellow }
        'ERROR' { Write-Host $line -ForegroundColor Red }
        default { Write-Host $line }
    }

    try {
        Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
    }
    catch {
        # Logging must never make the uninstall fail.
    }
}

function Test-SamePath {
    param([string]$Left, [string]$Right)
    if (-not $Left -or -not $Right) { return $false }
    try {
        $leftFull = [IO.Path]::GetFullPath($Left).TrimEnd('\')
        $rightFull = [IO.Path]::GetFullPath($Right).TrimEnd('\')
        return [string]::Equals($leftFull, $rightFull, [StringComparison]::OrdinalIgnoreCase)
    }
    catch {
        return $false
    }
}

function Test-UnderDirectory {
    param([string]$Path, [string]$Directory)
    try {
        $pathFull = [IO.Path]::GetFullPath($Path)
        $dirFull = [IO.Path]::GetFullPath($Directory).TrimEnd('\') + '\'
        return $pathFull.StartsWith($dirFull, [StringComparison]::OrdinalIgnoreCase)
    }
    catch {
        return $false
    }
}

function Remove-PathSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$Recurse
    )

    if (-not (Test-Path -LiteralPath $Path)) { return }

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($item -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Write-Log "Refusing to delete reparse point: $Path" 'ERROR'
        $script:Problems.Add("Reparse point not removed: $Path") | Out-Null
        return
    }

    if ($DryRun) {
        Write-Log "DRY-RUN would remove: $Path"
        return
    }

    try {
        Remove-Item -LiteralPath $Path -Recurse:$Recurse -Force -ErrorAction Stop
        Write-Log "Removed: $Path"
    }
    catch {
        Write-Log "Failed to remove $Path : $($_.Exception.Message)" 'ERROR'
        $script:Problems.Add("Could not remove: $Path") | Out-Null
    }
}

function Get-RegistryString {
    param(
        [object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Object) { return '' }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return '' }
    return [string]$property.Value
}

function Get-NekoUninstallEntries {
    $roots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    $found = New-Object System.Collections.Generic.List[object]

    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($child in (Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
            $props = Get-ItemProperty -LiteralPath $child.PSPath -ErrorAction SilentlyContinue
            if ($null -eq $props) { continue }

            $displayName = Get-RegistryString -Object $props -Name 'DisplayName'
            $installLocation = Get-RegistryString -Object $props -Name 'InstallLocation'
            $match = $displayName -match '(?i)NEKO FAMILY PROXY'
            if (-not $match -and $installLocation) {
                $match = Test-SamePath -Left $installLocation -Right $script:AppRoot
            }
            if (-not $match) { continue }

            $found.Add([pscustomobject]@{
                Key                  = $child.PSPath
                DisplayName          = $displayName
                DisplayVersion       = Get-RegistryString -Object $props -Name 'DisplayVersion'
                InstallLocation      = $installLocation
                UninstallString      = Get-RegistryString -Object $props -Name 'UninstallString'
                QuietUninstallString = Get-RegistryString -Object $props -Name 'QuietUninstallString'
            }) | Out-Null
        }
    }

    return $found
}

function Get-UninstallerPathFromString {
    param([string]$UninstallString)

    if (-not $UninstallString) { return $null }
    $trimmed = $UninstallString.Trim()
    if ($trimmed.StartsWith('"')) {
        $end = $trimmed.IndexOf('"', 1)
        if ($end -gt 1) { return $trimmed.Substring(1, $end - 1) }
        return $null
    }
    return ($trimmed -split '\s+')[0]
}

function Stop-NekoProcesses {
    $names = @('NekoLauncher', 'NekoUpdater', 'NekoProxyCore')
    foreach ($name in $names) {
        $procs = @(Get-Process -Name $name -ErrorAction SilentlyContinue)
        if ($procs.Count -eq 0) { continue }

        if ($DryRun) {
            Write-Log "DRY-RUN would stop $name (PID: $($procs.Id -join ', '))"
            continue
        }

        Write-Log "Stopping $name (PID: $($procs.Id -join ', '))"
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    }

    if ($DryRun) { return }

    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        $remaining = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -in $names
        })
        if ($remaining.Count -eq 0) { return }
        Start-Sleep -Milliseconds 500
    }

    $stillRunning = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -in $names
    })
    if ($stillRunning.Count -gt 0) {
        Write-Log "Some NEKO processes are still running: $($stillRunning.ProcessName -join ', ')" 'WARN'
    }
}

function Backup-NekoLogs {
    if (-not $KeepLogs) { return $null }

    $destination = $LogBackupPath
    if (-not $destination) {
        $desktop = [Environment]::GetFolderPath('Desktop')
        if (-not $desktop) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }
        $destination = Join-Path $desktop ("NekoUninstallLogs-{0}" -f $script:Stamp)
    }

    if ($DryRun) {
        Write-Log "DRY-RUN would back up logs to: $destination"
        return $destination
    }

    try {
        New-Item -ItemType Directory -Path $destination -Force -ErrorAction Stop | Out-Null
        if (Test-Path -LiteralPath $script:LogRoot) {
            Copy-Item -LiteralPath $script:LogRoot -Destination (Join-Path $destination 'NekoFamilyProxy') -Recurse -Force -ErrorAction Stop
        }
        if (Test-Path -LiteralPath $script:AppRoot) {
            $appLogs = @(Get-ChildItem -LiteralPath $script:AppRoot -Filter '*.log' -File -ErrorAction SilentlyContinue)
            foreach ($log in $appLogs) {
                Copy-Item -LiteralPath $log.FullName -Destination $destination -Force -ErrorAction SilentlyContinue
            }
        }
        Write-Log "Logs backed up to: $destination"
        return $destination
    }
    catch {
        Write-Log "Could not back up logs: $($_.Exception.Message)" 'WARN'
        return $null
    }
}

function Get-NekoCredentialTargets {
    $cmdkey = Join-Path $env:SystemRoot 'System32\cmdkey.exe'
    if (-not (Test-Path -LiteralPath $cmdkey)) { return @() }

    try {
        $listing = (& $cmdkey /list 2>&1 | Out-String)
    }
    catch {
        Write-Log "Could not list Windows credentials: $($_.Exception.Message)" 'WARN'
        return @()
    }

    $targets = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($listing -split "`r?`n")) {
        if ($line -match 'target=(.+?)\s*$') {
            $target = $Matches[1].Trim()
            if ($target -like '*Neko Family Launcher*') {
                $targets.Add($target) | Out-Null
            }
        }
    }
    if ($targets.Count -eq 0 -and $listing -match [regex]::Escape($script:CredentialTarget)) {
        $targets.Add($script:CredentialTarget) | Out-Null
    }
    return @($targets | Sort-Object -Unique)
}

function Remove-NekoCredentialTarget {
    $targets = @(Get-NekoCredentialTargets)
    if ($targets.Count -eq 0) {
        Write-Log "Credential target not present: $($script:CredentialTarget)"
        return
    }

    foreach ($target in $targets) {
        if ($DryRun) {
            Write-Log "DRY-RUN would delete credential target: $target"
            continue
        }
        try {
            $null = & $env:ComSpec /c ('cmdkey /delete:"{0}"' -f $target) 2>&1
            Write-Log "Requested credential target deletion: $target"
        }
        catch {
            Write-Log "Could not delete credential target '$target': $($_.Exception.Message)" 'WARN'
            $script:Problems.Add("Credential target could not be deleted: $target") | Out-Null
        }
    }

    if (-not $DryRun) {
        $remaining = @(Get-NekoCredentialTargets)
        if ($remaining.Count -gt 0) {
            Write-Log "Credential target still present: $($remaining -join ', ')" 'ERROR'
            $script:Problems.Add("Credential target remains: $($remaining -join ', ')") | Out-Null
        }
    }
}

function Get-Netfilter2Status {
    try {
        $sc = Join-Path $env:SystemRoot 'System32\sc.exe'
        if (-not (Test-Path -LiteralPath $sc)) { return 'unknown' }
        $output = (& $sc query netfilter2 2>&1 | Out-String)
        if ($output -match 'STATE\s*:\s*\d+\s+([A-Z_]+)') { return $Matches[1] }
        if ($output -match 'FAILED\s+1060') { return 'not installed' }
        return 'unknown'
    }
    catch {
        return 'unknown'
    }
}

function Show-UninstallSummary {
    param([string]$Version, [string]$Uninstaller, [string]$LogBackup)

    Write-Log '------------------------------------------------------------'
    Write-Log "NEKO clean uninstall summary ($($script:Stamp))"
    Write-Log "Installed version : $(if ($Version) { $Version } else { 'unknown' })"
    Write-Log "App root          : $($script:AppRoot)"
    Write-Log "Uninstaller       : $(if ($Uninstaller) { $Uninstaller } else { 'not found' })"
    Write-Log "Log backup        : $(if ($LogBackup) { $LogBackup } else { 'not requested' })"
    Write-Log "netfilter2        : $(Get-Netfilter2Status) (preserved by design)"
    Write-Log "Script log        : $($script:LogFile)"
    Write-Log '------------------------------------------------------------'
}

try {
    Write-Log "NEKO clean uninstall started. DryRun=$DryRun Force=$Force KeepLogs=$KeepLogs"

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $isElevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isElevated) {
        Write-Log 'Running elevated. This is a per-user install; run as the installing user, not as Administrator.' 'WARN'
        if (-not $Force) {
            Write-Log 'Aborting. Re-run without elevation, or pass -Force if this is intentional.' 'ERROR'
            exit 2
        }
    }

    $entries = @(Get-NekoUninstallEntries)
    if ($entries.Count -eq 0 -and (Test-Path -LiteralPath $script:KnownUninstallKey)) {
        $props = Get-ItemProperty -LiteralPath $script:KnownUninstallKey -ErrorAction SilentlyContinue
        $entries = @([pscustomobject]@{
            Key                  = $script:KnownUninstallKey
            DisplayName          = Get-RegistryString -Object $props -Name 'DisplayName'
            DisplayVersion       = Get-RegistryString -Object $props -Name 'DisplayVersion'
            InstallLocation      = Get-RegistryString -Object $props -Name 'InstallLocation'
            UninstallString      = Get-RegistryString -Object $props -Name 'UninstallString'
            QuietUninstallString = Get-RegistryString -Object $props -Name 'QuietUninstallString'
        })
    }

    $entry = $null
    if ($entries.Count -gt 0) {
        $entry = $entries | Where-Object { Test-SamePath -Left $_.InstallLocation -Right $script:AppRoot } | Select-Object -First 1
        if ($null -eq $entry) { $entry = $entries | Select-Object -First 1 }
    }

    $version = if ($null -ne $entry) { [string]$entry.DisplayVersion } else { '' }
    if ($version -and -not $Force -and $version -ne '5.2.0' -and -not $DryRun) {
        Write-Log "Installed version is '$version', not 5.2.0. Pass -Force to remove this version." 'WARN'
        exit 2
    }

    $uninstaller = $null
    if ($null -ne $entry) {
        $uninstaller = Get-UninstallerPathFromString -UninstallString $entry.UninstallString
    }
    if (-not $uninstaller -and (Test-Path -LiteralPath $script:AppRoot)) {
        $candidate = Get-ChildItem -LiteralPath $script:AppRoot -Filter 'unins*.exe' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -ne $candidate) { $uninstaller = $candidate.FullName }
    }

    if ($uninstaller -and -not (Test-Path -LiteralPath $uninstaller)) {
        Write-Log "Registered uninstaller does not exist: $uninstaller" 'WARN'
        $uninstaller = $null
    }
    if ($uninstaller -and -not (Test-UnderDirectory -Path $uninstaller -Directory $script:AppRoot)) {
        Write-Log "Refusing uninstaller outside the app root: $uninstaller" 'ERROR'
        $uninstaller = $null
    }

    if ($null -eq $entry -and -not (Test-Path -LiteralPath $script:AppRoot) -and -not (Test-Path -LiteralPath $script:LogRoot)) {
        Write-Log 'No NEKO installation or known leftovers were found for this user.'
        Remove-NekoCredentialTarget
        Show-UninstallSummary -Version $version -Uninstaller $null -LogBackup $null
        if (-not $DryRun -and $script:Problems.Count -gt 0) {
            exit 1
        }
        exit 0
    }

    Show-UninstallSummary -Version $version -Uninstaller $uninstaller -LogBackup $null

    if (-not $Force -and -not $DryRun) {
        Write-Host ''
        Write-Host 'This removes the NEKO app, its local state, logs, shortcuts, uninstall entry, and stored launcher credential.'
        Write-Host 'The shared netfilter2 driver is preserved.'
        $answer = Read-Host 'Type UNINSTALL to continue'
        if ($answer -cne 'UNINSTALL') {
            Write-Log 'Aborted by user.' 'WARN'
            exit 1
        }
    }

    $logBackup = Backup-NekoLogs
    Stop-NekoProcesses

    if ($uninstaller) {
        if ($DryRun) {
            Write-Log "DRY-RUN would run official uninstaller: $uninstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
        }
        else {
            $innoLog = Join-Path $env:TEMP ("neko-inno-uninstall-{0}.log" -f $script:Stamp)
            $arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="{0}"' -f $innoLog
            Write-Log "Running official uninstaller: $uninstaller"
            try {
                $process = Start-Process -FilePath $uninstaller -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
                Write-Log "Official uninstaller exit code: $($process.ExitCode)"
                if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
                    Write-Log "Uninstaller returned $($process.ExitCode); continuing with known-leftover cleanup." 'WARN'
                }
            }
            catch {
                Write-Log "Official uninstaller failed to start: $($_.Exception.Message)" 'ERROR'
                $script:Problems.Add('Official uninstaller could not be started.') | Out-Null
            }

            $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
            while ((Get-Date) -lt $deadline) {
                $running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
                    $_.ProcessName -like 'unins*'
                })
                if ($running.Count -eq 0) { break }
                Start-Sleep -Seconds 1
            }
        }
    }
    else {
        Write-Log 'No official uninstaller found; removing known NEKO paths only.' 'WARN'
    }

    Remove-PathSafe -Path $script:AppRoot -Recurse
    Remove-PathSafe -Path $script:LogRoot -Recurse

    $programs = [Environment]::GetFolderPath('Programs')
    $desktop = [Environment]::GetFolderPath('Desktop')
    foreach ($shortcut in @(
        (Join-Path $programs ($script:AppDisplayName + '.lnk')),
        (Join-Path $desktop ($script:AppDisplayName + '.lnk'))
    )) {
        if ($shortcut) { Remove-PathSafe -Path $shortcut }
    }

    foreach ($candidate in $entries) {
        if (-not $candidate.Key) { continue }
        if ($candidate.Key -notmatch '\\Uninstall\\') { continue }
        if (Test-Path -LiteralPath $candidate.Key) {
            if ($DryRun) {
                Write-Log "DRY-RUN would remove registry key: $($candidate.Key)"
            }
            else {
                try {
                    Remove-Item -LiteralPath $candidate.Key -Recurse -Force -ErrorAction Stop
                    Write-Log "Removed registry key: $($candidate.Key)"
                }
                catch {
                    Write-Log "Could not remove registry key $($candidate.Key): $($_.Exception.Message)" 'ERROR'
                    $script:Problems.Add("Registry key remains: $($candidate.Key)") | Out-Null
                }
            }
        }
    }

    if (Test-Path -LiteralPath $script:KnownUninstallKey) {
        if ($DryRun) {
            Write-Log "DRY-RUN would remove known uninstall key: $($script:KnownUninstallKey)"
        }
        else {
            try {
                Remove-Item -LiteralPath $script:KnownUninstallKey -Recurse -Force -ErrorAction Stop
                Write-Log "Removed known uninstall key: $($script:KnownUninstallKey)"
            }
            catch {
                Write-Log "Could not remove known uninstall key: $($_.Exception.Message)" 'ERROR'
                $script:Problems.Add('Known uninstall registry key remains.') | Out-Null
            }
        }
    }

    Remove-NekoCredentialTarget

    if (-not $DryRun) {
        if (Test-Path -LiteralPath $script:AppRoot) { $script:Problems.Add("App root remains: $($script:AppRoot)") | Out-Null }
        if (Test-Path -LiteralPath $script:LogRoot) { $script:Problems.Add("Log root remains: $($script:LogRoot)") | Out-Null }
        if (Test-Path -LiteralPath $script:KnownUninstallKey) { $script:Problems.Add('Known uninstall registry key remains.') | Out-Null }
        $remaining = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -in @('NekoLauncher', 'NekoUpdater', 'NekoProxyCore')
        })
        if ($remaining.Count -gt 0) { $script:Problems.Add("NEKO process remains: $($remaining.ProcessName -join ', ')") | Out-Null }
    }

    Show-UninstallSummary -Version $version -Uninstaller $uninstaller -LogBackup $logBackup

    if ($DryRun) {
        Write-Log 'Dry run complete. No changes were made.'
        exit 0
    }

    if ($script:Problems.Count -gt 0) {
        foreach ($problem in $script:Problems) {
            Write-Log "REMAINING: $problem" 'WARN'
        }
        Write-Log 'Clean uninstall completed with leftovers. Review the warnings above.' 'WARN'
        exit 1
    }

    Write-Log 'Clean uninstall verified: NEKO app data, shortcuts, registry entry, and credential target are gone.'
    Write-Log "netfilter2 is $(Get-Netfilter2Status) and was preserved."
    exit 0
}
catch {
    Write-Log "Unexpected failure: $($_.Exception.Message)" 'ERROR'
    Write-Log "Script log: $($script:LogFile)" 'ERROR'
    exit 1
}
