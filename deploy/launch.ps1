<#
.SYNOPSIS
    一键启动：启动网关 → 等待就绪 → 健康检查 → 打开控制台。

.DESCRIPTION
    这是"一键启动"按钮背后的实现。双击项目根目录的「一键启动.cmd」即可运行。

    默认行为：
      1. 检查 Python 虚拟环境与 OpenClaw 是否就位；
      2. 启动 Gateway（已在运行则跳过，0 秒返回）；
      3. 等到 WebUI 真正返回 200；
      4. 打印 5 个 Agent / PDF 引擎 / 协作链路状态；
      5. 自动打开浏览器进入控制台。

.PARAMETER Demo
    启动后立刻跑一遍默认演示需求（行政部 2026-Q1），产出 Markdown + PDF。

.PARAMETER Request
    自定义演示需求，配合 -Demo 使用。

.PARAMETER NoBrowser
    不自动打开浏览器。

.PARAMETER Port
    Gateway 端口，默认 8000。

.EXAMPLE
    .\deploy\launch.ps1
    .\deploy\launch.ps1 -Demo
    .\deploy\launch.ps1 -Demo -Request "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计，导出为PDF"
#>
[CmdletBinding()]
param(
    [switch]$Demo,
    [string]$Request,
    [switch]$NoBrowser,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$systemPy = Join-Path $root 'office-collab\system.py'

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host "▶ $Text" -ForegroundColor Cyan
}

function Test-Prerequisites {
    $missing = @()
    if (-not (Test-Path $python)) { $missing += '.venv\Scripts\python.exe（Python 虚拟环境）' }
    if (-not (Test-Path (Join-Path $root 'tools\npm-global\openclaw.cmd'))) {
        $missing += 'tools\npm-global\openclaw.cmd（OpenClaw 安装）'
    }
    if (-not (Test-Path $systemPy)) { $missing += 'office-collab\system.py' }
    if ($missing.Count -gt 0) {
        Write-Host '缺少必要组件：' -ForegroundColor Red
        $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        Write-Host '请先按 安装记录.md 完成安装。' -ForegroundColor Yellow
        return $false
    }
    return $true
}

function Get-ControlConsoleUrl {
    param(
        [string]$Root,
        [int]$Port
    )

    $baseUrl = "http://127.0.0.1:$Port/"
    $configPath = Join-Path $Root '.openclaw\openclaw.json'
    $tokenPath = Join-Path $Root '.openclaw\gateway-token.txt'

    try {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        if ($config.gateway.auth.mode -ne 'token') {
            return $baseUrl
        }

        $token = $null
        if (Test-Path -LiteralPath $tokenPath) {
            $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
        }
        if (-not $token -and $config.gateway.auth.token) {
            $token = [string]$config.gateway.auth.token
        }
        if ($token) {
            return "$baseUrl#token=$([uri]::EscapeDataString($token))"
        }
        Write-Host '  未找到网关令牌，将打开普通登录页。' -ForegroundColor Yellow
    } catch {
        Write-Host "  读取网关令牌失败：$($_.Exception.Message)" -ForegroundColor Yellow
    }

    return $baseUrl
}

Write-Host '========================================' -ForegroundColor White
Write-Host '  多 AI Agent 智能办公协作系统  一键启动' -ForegroundColor White
Write-Host '========================================' -ForegroundColor White

Write-Step '前置检查'
if (-not (Test-Prerequisites)) { exit 1 }
Write-Host '  Python 虚拟环境、OpenClaw、系统代码均就位' -ForegroundColor Green

Write-Step '启动 Gateway'
& (Join-Path $PSScriptRoot 'start-gateway.ps1') -Port $Port
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Gateway 启动失败，请查看 logs\gateway.log' -ForegroundColor Red
    exit 1
}

Write-Step '健康检查'
$healthOk = $false
try {
    $health = & $python $systemPy health 2>&1 | Out-String
    $parsed = $health | ConvertFrom-Json
    if ($parsed.ok) {
        $healthOk = $true
        Write-Host '  5 个 Agent 全部在线：' -ForegroundColor Green
        foreach ($agent in $parsed.agents) {
            Write-Host ("    {0,-8} {1}" -f $agent.id, $agent.model) -ForegroundColor Green
        }
    } else {
        Write-Host "  缺少 Agent：$($parsed.missing -join ', ')" -ForegroundColor Red
    }
} catch {
    Write-Host "  健康检查失败：$($_.Exception.Message)" -ForegroundColor Red
}
if (-not $healthOk) {
    Write-Host '继续启动，但功能可能不完整。' -ForegroundColor Yellow
}

$engines = & $python $systemPy pdf-engines 2>&1 | Out-String
try {
    $engineInfo = $engines | ConvertFrom-Json
    if ($engineInfo.ok) {
        Write-Host ("  PDF 引擎（{0}）：{1}" -f $engineInfo.owner, (($engineInfo.available.PSObject.Properties | ForEach-Object { $_.Name }) -join ', ')) -ForegroundColor Green
    } else {
        Write-Host '  未找到 PDF 引擎，导出将只有 Markdown。' -ForegroundColor Yellow
    }
} catch { }

Write-Step '控制台'
$url = Get-ControlConsoleUrl -Root $root -Port $Port
Write-Host "  http://127.0.0.1:$Port/" -ForegroundColor Green
if (-not $NoBrowser) {
    Start-Process $url
    Write-Host '  已在浏览器中打开（已自动携带网关令牌）' -ForegroundColor DarkGray
}

if ($Demo) {
    Write-Step '演示：生成工作汇报'
    if (-not $Request) {
        $Request = '生成2026年第一季度行政部工作汇报，重点突出行政服务满意度，格式为Markdown，导出为PDF'
    }
    Write-Host "  需求：$Request" -ForegroundColor DarkGray
    Write-Host '  正在跑五段协作链（约 1 分钟）…' -ForegroundColor DarkGray
    & $python $systemPy run --request $Request --mode full `
        --output-dir (Join-Path $root 'office-collab\outputs')
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  演示未能完成，请查看上面的错误信息。' -ForegroundColor Red
        exit 1
    }
}

Write-Host ''
Write-Host '就绪。' -ForegroundColor Green
Write-Host '  停止：双击「一键停止.cmd」或运行 .\deploy\stop-gateway.ps1' -ForegroundColor DarkGray
Write-Host '  体检：.\deploy\status.ps1' -ForegroundColor DarkGray
exit 0
