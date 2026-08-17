$ErrorActionPreference = 'Stop'
$docker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'

if (-not (Test-Path $docker)) {
  throw 'Docker CLI is not installed.'
}

Set-Location $PSScriptRoot
& $docker compose up -d
& $docker compose ps
Write-Output 'SearXNG: http://127.0.0.1:8080'
