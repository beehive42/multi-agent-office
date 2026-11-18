<#
.SYNOPSIS
    取消 Gateway 登录自启任务。

.PARAMETER TaskName
    计划任务名称，默认 OpenClawGateway。

.EXAMPLE
    .\deploy\uninstall-autostart.ps1
#>
[CmdletBinding()]
param([string]$TaskName = 'OpenClawGateway')

$ErrorActionPreference = 'Continue'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "计划任务 '$TaskName' 不存在。" -ForegroundColor Yellow
    exit 0
}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "已取消计划任务 '$TaskName'。" -ForegroundColor Green
exit 0
