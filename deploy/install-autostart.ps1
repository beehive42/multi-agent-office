<#
.SYNOPSIS
    把 Gateway 注册为登录自启任务，使系统常驻热态，演示时无需等待冷启动。

.DESCRIPTION
    冷启动实测约 2 分钟，主要耗时在配置加载、状态快照与核心恢复。把网关
    变成常驻服务后，演示/答辩时的"启动"就是 0 秒。

    任务以当前用户身份运行，登录后延迟 30 秒执行 deploy\start-gateway.ps1
    的后台分支。

.PARAMETER TaskName
    计划任务名称，默认 OpenClawGateway。

.PARAMETER Port
    Gateway 端口，默认 8000。

.PARAMETER AtLogonDelaySeconds
    登录后延迟秒数，默认 30。

.EXAMPLE
    .\deploy\install-autostart.ps1
    .\deploy\uninstall-autostart.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'OpenClawGateway',
    [int]$Port = 8000,
    [int]$AtLogonDelaySeconds = 30
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot 'start-gateway.ps1'

if (-not (Test-Path $startScript)) {
    throw "找不到 $startScript"
}

$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -Port $Port"
$action = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = "PT${AtLogonDelaySeconds}S"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description 'OpenClaw Gateway 登录自启（多 AI Agent 智能办公协作系统）' | Out-Null

Write-Host "已注册计划任务 '$TaskName'：登录后 ${AtLogonDelaySeconds}s 自动启动 Gateway（端口 $Port）。" -ForegroundColor Green
Write-Host "立即生效：先执行 .\deploy\start-gateway.ps1" -ForegroundColor DarkGray
Write-Host "取消自启：.\deploy\uninstall-autostart.ps1" -ForegroundColor DarkGray
