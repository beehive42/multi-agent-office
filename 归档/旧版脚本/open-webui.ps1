# 用本机保存的 Gateway Token 打开 OpenClaw 控制台
$root = $PSScriptRoot
$tokenPath = "$root\.openclaw\gateway-token.txt"
if (-not (Test-Path $tokenPath)) {
    Write-Error "未找到 Gateway Token：$tokenPath"
    exit 1
}
$token = (Get-Content $tokenPath -Raw).Trim()
Start-Process "http://127.0.0.1:8000/#token=$token"
