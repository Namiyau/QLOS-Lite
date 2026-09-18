param(
    [string]$BotQQ = "",
    [string]$HermesExe = "",
    [string]$NapCatDir = "",
    [switch]$NoStopFirst,
    [switch]$NoMonitor
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $Root "state"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Import-LocalEnv([string]$Path) {
    if (-not (Test-Path $Path)) {
        return
    }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($name) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

function Resolve-HermesExe([string]$ExplicitPath) {
    $candidates = @()
    if ($ExplicitPath) {
        $candidates += $ExplicitPath
    }
    if ($env:HERMES_EXE) {
        $candidates += $env:HERMES_EXE
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\hermes.exe")
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    $cmd = Get-Command "hermes" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    throw "Hermes exe not found. Set HERMES_EXE or pass -HermesExe."
}

function Resolve-PythonExe([string]$ResolvedHermesExe) {
    $hermesScripts = Split-Path -Parent $ResolvedHermesExe
    $venvPython = Join-Path $hermesScripts "python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    $cmd = Get-Command "python" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "Python not found. Install Python or keep Hermes venv intact."
}

Import-LocalEnv (Join-Path $Root "secrets.local.env")
if (-not $NapCatDir -and $env:NAPCAT_ROOT) {
    $NapCatDir = Join-Path $env:NAPCAT_ROOT "shell"
}
if (-not $env:API_SERVER_KEY -and $env:QLOS_HERMES_API_KEY) {
    $env:API_SERVER_KEY = $env:QLOS_HERMES_API_KEY
}
if (-not $env:AUXILIARY_VISION_PROVIDER) {
    $env:AUXILIARY_VISION_PROVIDER = "gemini"
}
if (-not $env:AUXILIARY_VISION_MODEL -or $env:AUXILIARY_VISION_MODEL -eq "gemini-2.0-flash-exp") {
    $env:AUXILIARY_VISION_MODEL = "gemini-3.5-flash"
}
if (-not $env:QLOS_MEDIA_DIR) {
    $env:QLOS_MEDIA_DIR = Join-Path (Split-Path -Parent $Root) "Hermi资料\media"
}

function Stop-ExistingStack {
    $selfPid = $PID
    $targets = Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $selfPid -and (
            ($_.Name -in @("python.exe", "pythonw.exe") -and $_.CommandLine -like "*qlos_lite.onebot_server*") -or
            ($_.Name -eq "hermes.exe" -and $_.CommandLine -like "*gateway*") -or
            $_.Name -in @("NapCatWinBootMain.exe")
        )
    }
    foreach ($proc in $targets) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Host "stopped $($proc.Name) $($proc.ProcessId)"
        } catch {
            Write-Host "skip stopped process $($proc.ProcessId)"
        }
    }
}

function Test-PortOpen([int]$Port) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-Port([int]$Port, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen $Port) {
            Write-Host "port $Port open"
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "port $Port closed after ${Seconds}s"
    return $false
}

function Get-ServiceStatus {
    [pscustomobject]@{
        Hermes = Test-PortOpen 8642
        QLOS = Test-PortOpen 8766
        NapCat = Test-PortOpen 3000
    }
}

function Show-Monitor([string]$HermesErr, [string]$QlosErr, [string]$NapCatErr) {
    while ($true) {
        $status = Get-ServiceStatus
        Clear-Host
        Write-Host "QLOS Stack monitor"
        Write-Host "Root: $Root"
        Write-Host ""
        Write-Host ("Hermes API  8642: {0}" -f $status.Hermes)
        Write-Host ("QLOS-Lite   8766: {0}" -f $status.QLOS)
        Write-Host ("NapCat      3000: {0}" -f $status.NapCat)
        Write-Host ""
        Write-Host "logs:"
        Write-Host "Hermes: $HermesErr"
        Write-Host "QLOS:   $QlosErr"
        Write-Host "NapCat: $NapCatErr"
        Write-Host ""
        Write-Host "Close this window to hide monitor. Services keep running."
        Write-Host "Use Stop_QLOS_Stack.bat to stop services."
        Start-Sleep -Seconds 5
    }
}

if (-not $NoStopFirst) {
    Stop-ExistingStack
    Start-Sleep -Seconds 1
}

$HermesExe = Resolve-HermesExe $HermesExe
$PythonExe = Resolve-PythonExe $HermesExe
if (-not $NapCatDir -or -not (Test-Path (Join-Path $NapCatDir "launcher.bat"))) {
    throw "External NapCat launcher not found. Set NAPCAT_ROOT or pass -NapCatDir."
}

$hermesOut = Join-Path $StateDir "hermes_gateway.out.log"
$hermesErr = Join-Path $StateDir "hermes_gateway.err.log"
$qlosOut = Join-Path $StateDir "qlos_lite.out.log"
$qlosErr = Join-Path $StateDir "qlos_lite.err.log"
$napcatOut = Join-Path $StateDir "napcat.out.log"
$napcatErr = Join-Path $StateDir "napcat.err.log"

Write-Host "starting Hermes gateway..."
Start-Process -FilePath $HermesExe `
    -ArgumentList @("gateway") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $hermesOut `
    -RedirectStandardError $hermesErr

Write-Host "starting QLOS-Lite..."
Start-Process -FilePath $PythonExe `
    -ArgumentList @("-m", "qlos_lite.onebot_server") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $qlosOut `
    -RedirectStandardError $qlosErr

Write-Host "starting NapCat for QQ $BotQQ..."
Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "launcher.bat -q $BotQQ") `
    -WorkingDirectory $NapCatDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $napcatOut `
    -RedirectStandardError $napcatErr

Write-Host ""
Write-Host "waiting for services..."
$okHermes = Wait-Port 8642 30
$okQlos = Wait-Port 8766 30
$okNapCat = Wait-Port 3000 60

Write-Host ""
Write-Host "stack status:"
Write-Host "Hermes 8642: $okHermes"
Write-Host "QLOS-Lite 8766: $okQlos"
Write-Host "NapCat 3000: $okNapCat"
Write-Host ""
Write-Host "logs:"
Write-Host $hermesErr
Write-Host $qlosErr
Write-Host $napcatErr

if (-not ($okHermes -and $okQlos -and $okNapCat)) {
    exit 1
}

if (-not $NoMonitor) {
    Show-Monitor $hermesErr $qlosErr $napcatErr
}

