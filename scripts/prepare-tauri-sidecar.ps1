$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

python (Join-Path $repo "scripts\create-tauri-icon.py")
& (Join-Path $repo "scripts\build-sidecar.ps1")

$hostLine = rustc -vV | Select-String "^host:"
if (-not $hostLine) { throw "Unable to determine the Rust target triple." }
$target = ($hostLine.ToString() -split ":", 2)[1].Trim()
$binaryDir = Join-Path $repo "desktop\src-tauri\binaries"
$source = Join-Path $repo "dist\knowledge-engine\knowledge-engine.exe"
$destination = Join-Path $binaryDir "knowledge-engine-$target.exe"

New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null
Copy-Item -LiteralPath $source -Destination $destination -Force
Write-Host "Tauri sidecar ready: $destination"
