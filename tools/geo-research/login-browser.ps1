param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('zhihu', 'xiaohongshu')]
  [string]$Platform
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$urls = @{
  zhihu       = 'https://www.zhihu.com/signin'
  xiaohongshu = 'https://www.xiaohongshu.com/'
}

& '.\.venv-browser\Scripts\python.exe' -m src.browser_collect login `
  --url $urls[$Platform] `
  --profile '.browser-profile' `
  --browser-channel msedge
