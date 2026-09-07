param(
  [int]$BackendPort = 8787
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$env:BRAND_ATLAS_TOKEN = if ($env:BRAND_ATLAS_TOKEN) { $env:BRAND_ATLAS_TOKEN } else { "dev-token" }
$env:BRAND_ATLAS_PORT = "$BackendPort"

Write-Host "Starting Brand Atlas backend on http://127.0.0.1:$BackendPort"
$backendProcess = Start-Process -PassThru -WindowStyle Hidden -FilePath "python" -ArgumentList "-m backend.main --host 127.0.0.1 --port $BackendPort --token $env:BRAND_ATLAS_TOKEN" -WorkingDirectory $repo

Write-Host "Starting frontend on http://127.0.0.1:5173"
Push-Location (Join-Path $repo "frontend")
try { npm run dev }
finally {
  Pop-Location
  if ($backendProcess -and -not $backendProcess.HasExited) {
    Stop-Process -Id $backendProcess.Id -Force
  }
}
