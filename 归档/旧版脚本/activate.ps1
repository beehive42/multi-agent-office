# 在当前 PowerShell 会话中启用本实验环境（点号运行）：
#   . .\activate.ps1
$root = $PSScriptRoot
$env:Path = "$root\tools\node;$root\tools\npm-global;$root\.venv\Scripts;$env:Path"
$env:OPENCLAW_HOME = $root
$env:TMP = "$root\.tmp-openclaw"
$env:TEMP = "$root\.tmp-openclaw"
$env:TMPDIR = "$root\.tmp-openclaw"
$env:PYTHONPATH = "$root\tools\pyshim"
New-Item -ItemType Directory -Force $env:TMP | Out-Null

Write-Host "OpenClaw / Python 实验环境已启用" -ForegroundColor Green
Write-Host ("  node      : " + (& node --version))
Write-Host ("  openclaw  : " + (& openclaw --version))
Write-Host ("  python    : " + (& "$root\.venv\Scripts\python.exe" --version))
Write-Host ("  WebUI     : http://127.0.0.1:8000/")
