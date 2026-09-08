param(
  [int]$BackendPort = 8787
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

try {
  # Tauri owns the Python backend now. Keeping only Vite here lets Tauri
  # terminate the complete development stack when its window closes.
  npm --prefix (Join-Path $repo "frontend") run dev -- --host 127.0.0.1 --port 5173
}
finally {
  # The Tauri CLI manages this beforeDevCommand process.
}
