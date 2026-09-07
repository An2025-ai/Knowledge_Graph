param(
  [switch]$Clean
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if ($Clean) {
  foreach ($path in @((Join-Path $repo "build"), (Join-Path $repo "dist"))) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
  }
}

Push-Location $repo
try {
  python -m PyInstaller --noconfirm --clean --onedir --noconsole `
    --name knowledge-engine `
    --exclude-module PyQt5 `
    --exclude-module PySide6 `
    --exclude-module IPython `
    --exclude-module matplotlib `
    --add-data "$repo\backend\app\schema.sql;backend\app" `
    --add-data "$repo\common_knowledge;common_knowledge" `
    "$repo\backend\main.py"
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
  if (-not (Test-Path -LiteralPath "$repo\dist\knowledge-engine\knowledge-engine.exe")) {
    throw "PyInstaller did not produce the sidecar executable."
  }
  Write-Host "Sidecar ready: $repo\dist\knowledge-engine\knowledge-engine.exe"
}
finally { Pop-Location }
