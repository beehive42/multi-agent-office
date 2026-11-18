<#
.SYNOPSIS
    分析 Gateway 冷启动各阶段耗时，找出启动瓶颈。

.DESCRIPTION
    OpenClaw 启动时会输出形如
        [gateway] startup phase: <name> <ms>ms total=<total>ms
    的日志。本脚本解析最近一次启动，列出最耗时的 15 个阶段与总耗时，
    便于在优化前后做对比。

.PARAMETER LogPath
    日志路径，默认 logs\gateway.log。

.PARAMETER Top
    显示前 N 个最慢阶段，默认 15。

.EXAMPLE
    .\deploy\gateway-profile.ps1
#>
[CmdletBinding()]
param(
    [string]$LogPath,
    [int]$Top = 15
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
if (-not $LogPath) { $LogPath = Join-Path $root 'logs\gateway.log' }

if (-not (Test-Path $LogPath)) {
    Write-Host "日志不存在：$LogPath" -ForegroundColor Red
    exit 1
}

$pattern = [regex]'startup phase:\s+(?<phase>\S+)\s+(?<ms>\d+(?:\.\d+)?)ms\s+total=(?<total>\d+(?:\.\d+)?)ms'
$phases = @()
$maxTotal = 0.0

foreach ($line in Get-Content $LogPath -Encoding UTF8) {
    $match = $pattern.Match($line)
    if (-not $match.Success) { continue }
    $ms = [double]$match.Groups['ms'].Value
    $total = [double]$match.Groups['total'].Value
    if ($total -gt $maxTotal) { $maxTotal = $total }
    $phases += [pscustomobject]@{
        Phase = $match.Groups['phase'].Value
        Ms    = $ms
        Total = $total
    }
}

# 只保留最近一次启动：从 total 回落的点之后开始
if ($phases.Count -eq 0) {
    Write-Host "日志中没有 startup phase 记录。请先执行 .\deploy\start-gateway.ps1 生成一次启动日志。" -ForegroundColor Yellow
    exit 1
}

$lastStart = 0
for ($i = 1; $i -lt $phases.Count; $i++) {
    if ($phases[$i].Total -lt $phases[$i - 1].Total) { $lastStart = $i }
}
$current = $phases[$lastStart..($phases.Count - 1)]

Write-Host ''
Write-Host "最近一次启动：$($current.Count) 个阶段，累计 $([math]::Round($maxTotal/1000,1))s" -ForegroundColor Cyan
Write-Host ''
Write-Host ("{0,-46} {1,10} {2,12}" -f '阶段', '本阶段(ms)', '累计(ms)') -ForegroundColor DarkGray
foreach ($item in ($current | Sort-Object Ms -Descending | Select-Object -First $Top)) {
    Write-Host ("{0,-46} {1,10:N0} {2,12:N0}" -f $item.Phase, $item.Ms, $item.Total)
}

$unaccounted = [math]::Round($maxTotal - ($current | Measure-Object -Property Ms -Sum).Sum, 0)
Write-Host ''
Write-Host ("已记录阶段合计 {0:N0} ms，未记录部分 {1:N0} ms" -f ($current | Measure-Object -Property Ms -Sum).Sum, $unaccounted) -ForegroundColor DarkGray
Write-Host '提示：process.bootstrap、sidecars.subagent-recovery、config.auth 通常是最大的三块；' -ForegroundColor DarkGray
Write-Host '      保持网关常驻（install-autostart.ps1）可以让演示时的"启动耗时"直接归零。' -ForegroundColor DarkGray
Write-Host ''
