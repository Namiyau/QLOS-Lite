param(
    [int]$Seconds = 180,
    [string]$MessageId = "",
    [string]$UserId = "",
    [string]$Text = "",
    [string]$NapCatLogDir = ""
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs\qlos_lite"
$StateDir = Join-Path $Root "state"
if (-not $NapCatLogDir -and $env:NAPCAT_LOG_DIR) {
    $NapCatLogDir = $env:NAPCAT_LOG_DIR
}
if (-not $NapCatLogDir) {
    $NapCatLogDir = Join-Path $Root "external\NapCat\logs"
}

if ($MessageId -or $UserId -or $Text) {
    Push-Location $Root
    try {
        $argsList = @("-m", "qlos_lite.diagnostics", "trace")
        if ($MessageId) {
            $argsList += $MessageId
        }
        if ($UserId) {
            $argsList += @("--user-id", $UserId)
        }
        if ($Text) {
            $argsList += @("--text", $Text)
        }
        python @argsList
        exit $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

function Get-LatestNapCatLog {
    Get-ChildItem -LiteralPath $NapCatLogDir -Filter "*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Get-ServiceRows {
    foreach ($port in 3000, 8642, 8766) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            [pscustomobject]@{Port = $port; State = "Listen"; PID = $conn.OwningProcess}
        } else {
            [pscustomobject]@{Port = $port; State = "Closed"; PID = ""}
        }
    }
}

function Read-NewText([string]$Path, [hashtable]$Offsets) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }
    $length = (Get-Item -LiteralPath $Path).Length
    if (-not $Offsets.ContainsKey($Path)) {
        $Offsets[$Path] = $length
        return ""
    }
    if ($length -lt $Offsets[$Path]) {
        $Offsets[$Path] = 0
    }
    if ($length -eq $Offsets[$Path]) {
        return ""
    }
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $stream.Seek($Offsets[$Path], [System.IO.SeekOrigin]::Begin) | Out-Null
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8, $true)
        $text = $reader.ReadToEnd()
        $Offsets[$Path] = $stream.Position
        return $text
    } finally {
        $stream.Close()
    }
}

$napcat = Get-LatestNapCatLog
$files = @(
    @{Name = "QLOS_HTTP"; Path = (Join-Path $LogDir "gateway_http.jsonl")},
    @{Name = "QLOS_GATE"; Path = (Join-Path $LogDir "gateway.jsonl")},
    @{Name = "QLOS_IN"; Path = (Join-Path $LogDir "inbound.jsonl")},
    @{Name = "QLOS_OUT"; Path = (Join-Path $LogDir "outbound.jsonl")},
    @{Name = "QLOS_ERR"; Path = (Join-Path $LogDir "errors.jsonl")},
    @{Name = "QLOS_STDERR"; Path = (Join-Path $StateDir "qlos_lite.err.log")},
    @{Name = "HERMES_ERR"; Path = (Join-Path $StateDir "hermes_gateway.err.log")}
)
if ($napcat) {
    $files += @{Name = "NAPCAT"; Path = $napcat.FullName}
}

$offsets = @{}
foreach ($file in $files) {
    if (Test-Path -LiteralPath $file.Path) {
        $offsets[$file.Path] = (Get-Item -LiteralPath $file.Path).Length
    }
}

Write-Host "QLOS trace start. Seconds=$Seconds"
Write-Host "Ports:"
Get-ServiceRows | Format-Table -AutoSize
if ($napcat) {
    Write-Host "NapCat log: $($napcat.FullName)"
}
Write-Host "Send QQ message now."

$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline) {
    foreach ($file in $files) {
        $text = Read-NewText $file.Path $offsets
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }
        $lines = $text -split "`r?`n" | Where-Object { $_ }
        foreach ($line in $lines) {
            Write-Host ("[{0}] {1}" -f $file.Name, $line)
        }
    }
    Start-Sleep -Milliseconds 500
}

Write-Host "QLOS trace done."
