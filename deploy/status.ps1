<#
.SYNOPSIS
    一站式体检：端口、WebUI、5 个 Agent、PDF 引擎、Python 环境、日志。

.PARAMETER Port
    Gateway 端口，默认 8000。

.EXAMPLE
    .\deploy\status.ps1
#>
[CmdletBinding()]
param([int]$Port = 8000)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$systemPy = Join-Path $root 'office-collab\system.py'

function Write-Section {
    param([string]$Title)
    Write-Host ''
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

$failures = 0

Write-Section "Gateway"
$listening = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listening) {
    $owner = $listening[0].OwningProcess
    $proc = Get-Process -Id $owner -ErrorAction SilentlyContinue
    Write-Host ("  端口 {0}：监听中（PID {1}，{2}）" -f $Port, $owner, $proc.ProcessName) -ForegroundColor Green
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 5 -UseBasicParsing
        Write-Host ("  WebUI：HTTP {0}，{1} 字节" -f $response.StatusCode, $response.RawContentLength) -ForegroundColor Green
    } catch {
        Write-Host "  WebUI：无法访问（$($_.Exception.Message)）" -ForegroundColor Red
        $failures++
    }
} else {
    Write-Host "  未运行。启动：.\deploy\start-gateway.ps1" -ForegroundColor Yellow
    $failures++
}

Write-Section "Agents"
if ($listening -and (Test-Path $python)) {
    $health = & $python $systemPy health 2>&1 | Out-String
    try {
        $parsed = $health | ConvertFrom-Json
        if ($parsed.ok) {
            foreach ($agent in $parsed.agents) {
                Write-Host ("  {0,-8} {1}" -f $agent.id, $agent.model) -ForegroundColor Green
            }
        } else {
            Write-Host "  缺少：$($parsed.missing -join ', ')" -ForegroundColor Red
            $failures++
        }
    } catch {
        Write-Host "  健康检查输出无法解析：$health" -ForegroundColor Red
        $failures++
    }
} else {
    Write-Host "  跳过（网关未运行或缺少 .venv）" -ForegroundColor DarkGray
}

Write-Section "PDF 引擎"
if (Test-Path $python) {
    $engines = & $python $systemPy pdf-engines 2>&1 | Out-String
    try {
        $parsed = $engines | ConvertFrom-Json
        if ($parsed.ok) {
            $parsed.available.PSObject.Properties | ForEach-Object {
                Write-Host ("  {0}: {1}" -f $_.Name, $_.Value) -ForegroundColor Green
            }
        } else {
            Write-Host "  未找到任何 PDF 引擎（需要 LibreOffice 或 Chrome/Edge/Chromium）" -ForegroundColor Red
            $failures++
        }
    } catch {
        Write-Host "  $engines" -ForegroundColor Red
    }
}

Write-Section "协作链路"
if (Test-Path $python) {
    $route = & $python $systemPy verify-route 2>&1 | Out-String
    try {
        $parsed = $route | ConvertFrom-Json
        if ($parsed.ok) {
            Write-Host "  五段链路静态检查通过，网关可达" -ForegroundColor Green
        } else {
            foreach ($problem in $parsed.problems) { Write-Host "  - $problem" -ForegroundColor Yellow }
            $failures++
        }
    } catch {
        Write-Host "  $route" -ForegroundColor Red
    }
}

Write-Section "日志"
$logPath = Join-Path $root 'logs\gateway.log'
if (Test-Path $logPath) {
    $info = Get-Item $logPath
    Write-Host ("  {0}（{1:N1} KB，更新于 {2}）" -f $info.Name, ($info.Length / 1KB), $info.LastWriteTime)
} else {
    Write-Host "  尚无 logs\gateway.log" -ForegroundColor DarkGray
}

Write-Host ''
if ($failures -eq 0) {
    Write-Host "全部检查通过。" -ForegroundColor Green
    exit 0
}
Write-Host "$failures 项检查未通过。" -ForegroundColor Yellow
exit 1
