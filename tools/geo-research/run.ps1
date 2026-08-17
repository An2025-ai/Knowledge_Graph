param(
  [ValidateSet('collect', 'search', 'browser', 'browser-diagnose', 'report', 'all')]
  [string]$Command = 'all',
  [ValidateSet('all', 'market', 'products', 'academic', 'user-voice')]
  [string]$Dataset = 'all'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($Command -in @('collect', 'all')) { python -m src.research collect }
if ($Command -eq 'search') { python -m src.research search }
if ($Command -eq 'browser') { & '.\.venv-browser\Scripts\python.exe' -m src.browser_collect collect --dataset $Dataset }
if ($Command -eq 'browser-diagnose') { & '.\.venv-browser\Scripts\python.exe' -m src.browser_collect diagnose }
if ($Command -in @('report', 'all')) { python -m src.research report }
