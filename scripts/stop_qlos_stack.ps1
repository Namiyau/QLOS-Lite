param(
    [switch]$KeepQQ
)

$ErrorActionPreference = "Continue"

$targets = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @("python.exe", "pythonw.exe") -and $_.CommandLine -like "*qlos_lite.onebot_server*") -or
    ($_.Name -eq "hermes.exe" -and $_.CommandLine -like "*gateway*") -or
    $_.Name -in @("NapCatWinBootMain.exe") -or
    (-not $KeepQQ -and $_.Name -in @("QQ.exe", "QQEX.exe"))
}

foreach ($proc in $targets) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Write-Host "stopped $($proc.Name) $($proc.ProcessId)"
    } catch {
        Write-Host "failed $($proc.Name) $($proc.ProcessId): $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 1
foreach ($port in 3000, 8642, 8766) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $port)
        Write-Host "port $port open"
    } catch {
        Write-Host "port $port closed"
    } finally {
        $client.Close()
    }
}
