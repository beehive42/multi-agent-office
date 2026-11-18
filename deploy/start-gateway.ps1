<#
.SYNOPSIS
    启动 OpenClaw Gateway，并等到真正可服务为止。

.DESCRIPTION
    与旧版 start-openclaw.ps1（已归档到 归档\旧版脚本\）的区别：
      * 幂等——网关已在监听时 0 秒返回，不会重复拉起进程；
      * 默认后台运行（-WindowStyle Hidden），日志写入 logs\gateway.log；
      * 启动后轮询 TCP + HTTP，直到 WebUI 返回 200 才返回，避免"启动了但没就绪"；
      * 输出冷启动耗时，便于对比优化效果；
      * 自动准备临时目录与编译缓存，缩短后续启动。

.PARAMETER Foreground
    前台运行（Ctrl+C 停止），用于调试。

.PARAMETER Port
    监听端口，默认 8000。

.PARAMETER TimeoutSeconds
    等待就绪的最长时间，默认 240 秒。

.EXAMPLE
    .\deploy\start-gateway.ps1
    .\deploy\start-gateway.ps1 -Foreground
#>
[CmdletBinding()]
param(
    [switch]$Foreground,
    [int]$Port = 8000,
    [int]$TimeoutSeconds = 240
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Set-OpenClawEnvironment {
    param([string]$Root)

    $env:Path = "$Root\tools\node;$Root\tools\npm-global;$env:Path"
    $env:OPENCLAW_HOME = $Root
    $env:USERPROFILE = "$Root\.home"
    $env:HOME = "$Root\.home"
    $env:LOCALAPPDATA = "$Root\.home\AppData\Local"
    $env:APPDATA = "$Root\.home\AppData\Roaming"
    $env:TMP = "$Root\.tmp-openclaw"
    $env:TEMP = $env:TMP
    $env:TMPDIR = $env:TMP
    # 让 Node 的编译缓存落在项目内，跨启动复用，减少每次冷启动的解析开销
    $env:NODE_COMPILE_CACHE = "$Root\.tmp-openclaw\node-compile-cache"

    foreach ($dir in @(
        "$Root\.home\AppData\Local",
        "$Root\.home\AppData\Roaming",
        "$Root\.tmp-openclaw",
        "$Root\.tmp-openclaw\node-compile-cache",
        "$Root\logs"
    )) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

function Test-GatewayPort {
    param([int]$Port, [int]$TimeoutMs = 800)
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $task.Wait($TimeoutMs)) { $client.Dispose(); return $false }
        $ok = $client.Connected
        $client.Dispose()
        return $ok
    } catch {
        return $false
    }
}

function Test-GatewayHttp {
    param([int]$Port)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

Set-OpenClawEnvironment -Root $root

if (Test-GatewayPort -Port $Port) {
    Write-Host "Gateway 已在 127.0.0.1:$Port 监听，跳过启动。" -ForegroundColor Green
    exit 0
}

$logPath = Join-Path $root 'logs\gateway.log'
$openclaw = Join-Path $root 'tools\npm-global\openclaw.cmd'
if (-not (Test-Path $openclaw)) {
    throw "找不到 OpenClaw 入口：$openclaw（请先运行安装步骤）"
}

$arguments = @('gateway', 'run', '--port', $Port, '--bind', 'loopback')

if ($Foreground) {
    Write-Host "前台启动 Gateway：http://127.0.0.1:$Port/ （Ctrl+C 停止）" -ForegroundColor Cyan
    & $openclaw @arguments
    exit $LASTEXITCODE
}

$startedAt = Get-Date
Write-Host "后台启动 Gateway（日志：logs\gateway.log）…" -ForegroundColor Cyan
$process = Start-Process -FilePath $openclaw -ArgumentList $arguments `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $logPath -RedirectStandardError "$logPath.err"

$deadline = $startedAt.AddSeconds($TimeoutSeconds)
$ready = $false
$dots = 0
while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
        Write-Host ''
        Write-Host "Gateway 进程提前退出（exit=$($process.ExitCode)）。日志末尾：" -ForegroundColor Red
        Get-Content $logPath -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" }
        exit 1
    }
    if (Test-GatewayPort -Port $Port) {
        if (Test-GatewayHttp -Port $Port) { $ready = $true; break }
    }
    Start-Sleep -Milliseconds 700
    $dots++
    if ($dots % 10 -eq 0) { Write-Host -NoNewline '.' }
}

$elapsed = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
Write-Host ''
if (-not $ready) {
    Write-Host "等待就绪超时（${TimeoutSeconds}s）。请检查 logs\gateway.log。" -ForegroundColor Red
    exit 1
}

$pidFile = Join-Path $root 'logs\gateway.pid'
$listenerPid = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty OwningProcess
if (-not $listenerPid) { $listenerPid = $process.Id }
Set-Content -LiteralPath $pidFile -Value $listenerPid -Encoding ascii
Write-Host "Gateway 就绪：http://127.0.0.1:$Port/  冷启动耗时 ${elapsed}s（监听 PID $listenerPid）" -ForegroundColor Green
Write-Host "停止：.\deploy\stop-gateway.ps1    状态：.\deploy\status.ps1    阶段耗时：.\deploy\gateway-profile.ps1" -ForegroundColor DarkGray
exit 0
