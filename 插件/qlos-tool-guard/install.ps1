$ErrorActionPreference = "Stop"

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$hermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:USERPROFILE ".hermes" }
$target = Join-Path $hermesHome "plugins\qlos-tool-guard"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
if (Test-Path $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
}
Copy-Item -LiteralPath $source -Destination $target -Recurse

Write-Host "Installed to $target"
Write-Host "Next: hermes plugins enable qlos-tool-guard"
Write-Host "Then restart Hermes gateway."
