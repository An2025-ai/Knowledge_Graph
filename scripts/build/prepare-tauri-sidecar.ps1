$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

python (Join-Path $repo "scripts\build\create-tauri-icon.py")
& (Join-Path $repo "scripts\build\build-sidecar.ps1") -Clean

$hostLine = rustc -vV | Select-String "^host:"
if (-not $hostLine) { throw "Unable to determine the Rust target triple." }
$target = ($hostLine.ToString() -split ":", 2)[1].Trim()
$binaryDir = Join-Path $repo "desktop\src-tauri\binaries"
$source = Join-Path $repo "dist\knowledge-engine.exe"
$destination = Join-Path $binaryDir "knowledge-engine-$target.exe"

New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null

# Remove stale one-dir sidecar files from older builds. The one-file sidecar
# must be self-contained; Tauri should stage only the target-specific .exe.
Get-ChildItem -LiteralPath $binaryDir -Filter "knowledge-engine*.exe" -File -ErrorAction SilentlyContinue |
  Remove-Item -Force
$legacyInternal = Join-Path $binaryDir "_internal"
if (Test-Path -LiteralPath $legacyInternal) {
  Remove-Item -LiteralPath $legacyInternal -Recurse -Force
}

Copy-Item -LiteralPath $source -Destination $destination -Force
Write-Host "Tauri sidecar ready: $destination"
