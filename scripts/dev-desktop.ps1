param(
  [int]$BackendPort = 8787
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$token = if ($env:BRAND_ATLAS_TOKEN) { $env:BRAND_ATLAS_TOKEN } else { "dev-token" }

$backendProcess = Start-Process -PassThru -WindowStyle Hidden -FilePath "python" -ArgumentList @(
  "-m", "backend.main", "--host", "127.0.0.1", "--port", "$BackendPort", "--token", $token
) -WorkingDirectory $repo

try {
  # Keep this process alive so Tauri waits for Vite before opening its window.
  npm --prefix (Join-Path $repo "frontend") run dev -- --host 127.0.0.1 --port 5173
}
finally {
  if ($backendProcess -and -not $backendProcess.HasExited) {
    Stop-Process -Id $backendProcess.Id -Force
  }
}
