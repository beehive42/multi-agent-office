<#
.SYNOPSIS
    停止 OpenClaw Gateway（按端口定位监听进程，可靠且不留孤儿进程）。

.PARAMETER Port
    监听端口，默认 8000。

.EXAMPLE
    .\deploy\stop-gateway.ps1
#>
[CmdletBinding()]
param([int]$Port = 8000)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if (-not $listeners) {
    Write-Host "端口 $Port 上没有监听进程，Gateway 已是停止状态。" -ForegroundColor Yellow
} else {
    foreach ($listener in $listeners) {
        $processId = $listener.OwningProcess
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        Write-Host "停止 PID $processId（$($process.ProcessName)）…" -ForegroundColor Cyan
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

# 等端口真正释放
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 400
}

# 清理本网关遗留的 node 子进程（仅限本项目的 node 可执行文件）
$projectNode = Join-Path $root 'tools\node\node.exe'
$stale = @(Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$root*openclaw*" })
foreach ($item in $stale) {
    Write-Host "清理残留进程 PID $($item.ProcessId)" -ForegroundColor DarkGray
    Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath (Join-Path $root 'logs\gateway.pid') -Force -ErrorAction SilentlyContinue

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "端口 $Port 仍被占用。" -ForegroundColor Red
    exit 1
}
Write-Host "Gateway 已停止（端口 $Port 已释放）。" -ForegroundColor Green
exit 0
