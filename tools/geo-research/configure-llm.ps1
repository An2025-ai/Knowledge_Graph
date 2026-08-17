param(
  [Parameter(Mandatory = $true)]
  [string]$BaseUrl,
  [Parameter(Mandatory = $true)]
  [string]$Model,
  [string]$Endpoint = '',
  [bool]$ApiKeyRequired = $true,
  [switch]$StoreApiKey
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$configPath = Join-Path $PSScriptRoot 'llm-config.local.json'
$storedApiKey = $null
if (Test-Path -LiteralPath $configPath) {
  $existingConfig = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($existingConfig.api_key) { $storedApiKey = [string]$existingConfig.api_key }
}

if ($StoreApiKey) {
  $secureKey = Read-Host '请输入要保存到本机配置文件的模型 API Key（输入不会显示）' -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
  try {
    $storedApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($storedApiKey)) { throw 'API Key 不能为空。' }
  }
  finally {
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
  }
}

$config = [ordered]@{
  base_url = $BaseUrl.TrimEnd('/')
  model = $Model
  endpoint = if ($Endpoint) { $Endpoint } else { $null }
  api_key = $storedApiKey
  api_key_env = 'BRAND_ATLAS_LLM_API_KEY'
  api_key_required = $ApiKeyRequired
  timeout_seconds = 120
  max_output_tokens = 6000
  temperature = 0.2
}

$config | ConvertTo-Json | Set-Content -Encoding UTF8 $configPath
Write-Host '已保存 llm-config.local.json。该文件已被 .gitignore 排除。'
if ($storedApiKey) {
  Write-Host 'API Key 已保存到本机配置文件；后续运行无需重复输入。'
} else {
  Write-Host '当前未保存 API Key；运行 run-research-report.ps1 时会安全提示输入。'
}
