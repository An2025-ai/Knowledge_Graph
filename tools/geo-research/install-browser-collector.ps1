param(
  [switch]$ForceRecreate,
  [switch]$InstallChromium
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$venv = Join-Path $PSScriptRoot '.venv-browser'

if ($ForceRecreate -and (Test-Path -LiteralPath $venv)) {
  throw 'Remove .venv-browser explicitly before using -ForceRecreate; automatic recursive deletion is disabled.'
}
if (-not (Test-Path -LiteralPath $venv)) {
  python -m venv $venv
}

$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install --disable-pip-version-check -r requirements-browser.txt
if ($InstallChromium) {
  & $python -m playwright install chromium
}
& $python -m src.browser_collect diagnose
