param(
  [Parameter(Mandatory = $true)]
  [string]$Request,
  [switch]$IncludeLogin,
  [switch]$ShowBrowser,
  [ValidateSet('auto', 'general', 'geo')]
  [string]$QueryProfile = 'auto',
  [string]$Config = 'llm-config.local.json'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv-browser\Scripts\python.exe'
$configPath = Join-Path $PSScriptRoot $Config
if (-not (Test-Path -LiteralPath $python)) {
  throw '未找到浏览器采集环境，请先运行 .\install-browser-collector.ps1'
}
if (-not (Test-Path -LiteralPath $configPath)) {
  throw '未找到 llm-config.local.json，请先运行 .\configure-llm.ps1 配置 URL 和模型名。'
}

$configObject = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$keyEnvName = if ($configObject.api_key_env) { [string]$configObject.api_key_env } else { 'BRAND_ATLAS_LLM_API_KEY' }
$keyRequired = if ($null -eq $configObject.api_key_required) { $true } else { [bool]$configObject.api_key_required }
$configKeyPresent = -not [string]::IsNullOrWhiteSpace([string]$configObject.api_key)
$previousKey = [Environment]::GetEnvironmentVariable($keyEnvName, 'Process')
$temporaryKeySet = $false

try {
  if ($keyRequired -and -not $configKeyPresent -and [string]::IsNullOrWhiteSpace($previousKey)) {
    $secureKey = Read-Host '请输入模型 API Key（输入不会显示，且不会写入文件）' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
      $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
      if ([string]::IsNullOrWhiteSpace($plainKey)) { throw 'API Key 不能为空。' }
      [Environment]::SetEnvironmentVariable($keyEnvName, $plainKey, 'Process')
      $temporaryKeySet = $true
    }
    finally {
      if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
      $plainKey = $null
    }
  }

  $arguments = @('-m', 'src.llm_report', '--config', $configPath, 'run', '--request', $Request, '--query-profile', $QueryProfile)
  if ($IncludeLogin) {
    $arguments += @('--include-login', '--profile', (Join-Path $PSScriptRoot '.browser-profile'))
  }
  if ($ShowBrowser) { $arguments += '--headed' }

  & $python @arguments
  if ($LASTEXITCODE -ne 0) { throw "研究报告生成失败，退出码：$LASTEXITCODE" }
}
finally {
  if ($temporaryKeySet) {
    [Environment]::SetEnvironmentVariable($keyEnvName, $null, 'Process')
  }
}
