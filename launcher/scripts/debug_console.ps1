param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
$launcher = (Resolve-Path -LiteralPath $LauncherPath).Path
$logDirectory = Join-Path $env:LOCALAPPDATA "NEKO FAMILY\logs"
$logFile = Join-Path $logDirectory "debug.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$startOffset = if (Test-Path -LiteralPath $logFile) {
    (Get-Item -LiteralPath $logFile).Length
} else {
    0
}

Clear-Host
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " NEKO FAMILY - LIVE DEBUG CONSOLE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Launcher : $launcher"
Write-Host "Log file : $logFile"
Write-Host ""
Write-Host "The Core will not start until pso2.exe is detected." -ForegroundColor Yellow
Write-Host "Keep this window open. Press Ctrl+C to stop watching." -ForegroundColor DarkGray
Write-Host "------------------------------------------------------------"

$launcherProcess = Start-Process -FilePath $launcher -ArgumentList "--debug" -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds(15)
while (-not (Test-Path -LiteralPath $logFile) -and [DateTime]::UtcNow -lt $deadline) {
    if ($launcherProcess.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 200
    $launcherProcess.Refresh()
}

if (-not (Test-Path -LiteralPath $logFile)) {
    Write-Host "[ERROR] Debug log was not created." -ForegroundColor Red
    Write-Host "Close any Launcher already running in the system tray, then try again." -ForegroundColor Yellow
    exit 1
}

$stream = [System.IO.File]::Open(
    $logFile,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::ReadWrite
)
$null = $stream.Seek($startOffset, [System.IO.SeekOrigin]::Begin)
$reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)

try {
    while ($true) {
        $printed = $false
        while (($line = $reader.ReadLine()) -ne $null) {
            Write-Host $line
            $printed = $true
        }
        $launcherProcess.Refresh()
        if ($launcherProcess.HasExited) {
            Start-Sleep -Milliseconds 300
            while (($line = $reader.ReadLine()) -ne $null) {
                Write-Host $line
            }
            break
        }
        if (-not $printed) {
            Start-Sleep -Milliseconds 200
        }
    }
} finally {
    $reader.Dispose()
    $stream.Dispose()
}

Write-Host "------------------------------------------------------------"
Write-Host "Launcher exited with code $($launcherProcess.ExitCode)." -ForegroundColor Yellow
