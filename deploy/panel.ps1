<#
.SYNOPSIS
    图形化控制面板：用按钮启动 / 停止 / 体检 / 演示。

.DESCRIPTION
    双击项目根目录的「一键面板.cmd」即可打开。面板只做调度，实际动作在独立
    的 PowerShell 窗口里执行，因此长任务不会卡住界面。

    面板会自动刷新网关状态（每 2 秒探测一次 8000 端口与 WebUI）。

.PARAMETER SelfTest
    只构建界面并校验控件，随即退出（用于自动化验证，不显示窗口）。

.EXAMPLE
    .\deploy\panel.ps1
    .\deploy\panel.ps1 -SelfTest
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$systemPy = Join-Path $root 'office-collab\system.py'
$outputs = Join-Path $root 'office-collab\outputs'

function Get-PowerShellHost {
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($pwsh) { return $pwsh.Source }
    return (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
}

function Test-Gateway {
    param([int]$Port)
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        $connected = $task.Wait(400) -and $client.Connected
        $client.Dispose()
        return $connected
    } catch {
        return $false
    }
}

function Start-InNewWindow {
    param([string]$ScriptPath, [string[]]$Arguments = @(), [switch]$KeepOpen)
    $host_ = Get-PowerShellHost
    $quoted = ($Arguments | ForEach-Object { "'" + ($_ -replace "'", "''") + "'" }) -join ' '
    $command = "& '$ScriptPath' $quoted"
    if ($KeepOpen) {
        $command += "; Write-Host ''; Write-Host '按 Enter 关闭…'; Read-Host | Out-Null"
    }
    Start-Process -FilePath $host_ -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $command
    ) | Out-Null
}

# ---------------------------------------------------------------- 界面构建
$form = [System.Windows.Forms.Form]::new()
$form.Text = '多 AI Agent 智能办公协作系统 — 控制面板'
$form.Size = [System.Drawing.Size]::new(560, 430)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(246, 248, 251)
$form.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 9)

$title = [System.Windows.Forms.Label]::new()
$title.Text = '多 AI Agent 智能办公协作系统'
$title.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 14, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(20, 49, 92)
$title.Location = [System.Drawing.Point]::new(24, 18)
$title.Size = [System.Drawing.Size]::new(500, 32)
$form.Controls.Add($title)

$subtitle = [System.Windows.Forms.Label]::new()
$subtitle.Text = 'ManagerAgent · PlannerAgent · DataAgent · WriterAgent · CheckerAgent'
$subtitle.ForeColor = [System.Drawing.Color]::FromArgb(107, 119, 133)
$subtitle.Location = [System.Drawing.Point]::new(26, 52)
$subtitle.Size = [System.Drawing.Size]::new(500, 20)
$form.Controls.Add($subtitle)

$statusBox = [System.Windows.Forms.Panel]::new()
$statusBox.Location = [System.Drawing.Point]::new(24, 84)
$statusBox.Size = [System.Drawing.Size]::new(500, 56)
$statusBox.BackColor = [System.Drawing.Color]::White
$statusBox.BorderStyle = 'FixedSingle'
$form.Controls.Add($statusBox)

$statusDot = [System.Windows.Forms.Label]::new()
$statusDot.Text = '●'
$statusDot.Font = [System.Drawing.Font]::new('Segoe UI', 16)
$statusDot.ForeColor = [System.Drawing.Color]::Gray
$statusDot.Location = [System.Drawing.Point]::new(12, 12)
$statusDot.Size = [System.Drawing.Size]::new(24, 30)
$statusBox.Controls.Add($statusDot)

$statusText = [System.Windows.Forms.Label]::new()
$statusText.Text = '正在检测…'
$statusText.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 10, [System.Drawing.FontStyle]::Bold)
$statusText.Location = [System.Drawing.Point]::new(40, 10)
$statusText.Size = [System.Drawing.Size]::new(440, 22)
$statusBox.Controls.Add($statusText)

$statusHint = [System.Windows.Forms.Label]::new()
$statusHint.Text = "http://127.0.0.1:$Port/"
$statusHint.ForeColor = [System.Drawing.Color]::FromArgb(107, 119, 133)
$statusHint.Location = [System.Drawing.Point]::new(42, 32)
$statusHint.Size = [System.Drawing.Size]::new(440, 18)
$statusBox.Controls.Add($statusHint)

function New-PanelButton {
    param([string]$Text, [int]$X, [int]$Y, [int]$Width = 160, [switch]$Primary)
    $button = [System.Windows.Forms.Button]::new()
    $button.Text = $Text
    $button.Location = [System.Drawing.Point]::new($X, $Y)
    $button.Size = [System.Drawing.Size]::new($Width, 44)
    $button.FlatStyle = 'Flat'
    $button.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 10)
    $button.Cursor = [System.Windows.Forms.Cursors]::Hand
    if ($Primary) {
        $button.BackColor = [System.Drawing.Color]::FromArgb(47, 111, 235)
        $button.ForeColor = [System.Drawing.Color]::White
    } else {
        $button.BackColor = [System.Drawing.Color]::White
        $button.ForeColor = [System.Drawing.Color]::FromArgb(20, 49, 92)
    }
    $button.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(200, 210, 224)
    $form.Controls.Add($button)
    return $button
}

$startButton = New-PanelButton -Text '▶  启动系统' -X 24 -Y 158 -Primary
$stopButton = New-PanelButton -Text '■  停止系统' -X 194 -Y 158
$statusButton = New-PanelButton -Text '🩺  状态体检' -X 364 -Y 158
$webButton = New-PanelButton -Text '🌐  打开控制台' -X 24 -Y 210
$demoButton = New-PanelButton -Text '📄  生成演示汇报' -X 194 -Y 210 -Width 160
$folderButton = New-PanelButton -Text '📂  打开输出目录' -X 364 -Y 210

$hint = [System.Windows.Forms.Label]::new()
$hint.Text = '长任务会在独立窗口执行，本面板不会卡住。'
$hint.ForeColor = [System.Drawing.Color]::FromArgb(107, 119, 133)
$hint.Location = [System.Drawing.Point]::new(26, 268)
$hint.Size = [System.Drawing.Size]::new(500, 20)
$form.Controls.Add($hint)

$footer = [System.Windows.Forms.Label]::new()
$footer.Text = '提示：首次启动冷启动约 1-2 分钟；之后重复启动 0 秒返回。安装自启任务可在演示时省掉这段等待。'
$footer.ForeColor = [System.Drawing.Color]::FromArgb(140, 150, 163)
$footer.Location = [System.Drawing.Point]::new(26, 292)
$footer.Size = [System.Drawing.Size]::new(500, 40)
$form.Controls.Add($footer)

# ---------------------------------------------------------------- 行为绑定
$startButton.Add_Click({
    Start-InNewWindow -ScriptPath (Join-Path $PSScriptRoot 'launch.ps1') -Arguments @() -KeepOpen
})
$stopButton.Add_Click({
    Start-InNewWindow -ScriptPath (Join-Path $PSScriptRoot 'stop-gateway.ps1') -Arguments @() -KeepOpen
})
$statusButton.Add_Click({
    Start-InNewWindow -ScriptPath (Join-Path $PSScriptRoot 'status.ps1') -Arguments @() -KeepOpen
})
$webButton.Add_Click({
    Start-Process "http://127.0.0.1:$Port/"
})
$demoButton.Add_Click({
    $request = '生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计，格式为Markdown，导出为PDF'
    $host_ = Get-PowerShellHost
    $command = "& '$python' '$systemPy' run --request '$request' --mode full --output-dir '$outputs'; Write-Host ''; Write-Host '按 Enter 关闭…'; Read-Host | Out-Null"
    Start-Process -FilePath $host_ -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $command
    ) | Out-Null
})
$folderButton.Add_Click({
    if (Test-Path $outputs) { Start-Process explorer.exe $outputs }
    else { [System.Windows.Forms.MessageBox]::Show('输出目录还不存在，先跑一次演示。', '提示') | Out-Null }
})

$timer = [System.Windows.Forms.Timer]::new()
$timer.Interval = 2000
$timer.Add_Tick({
    if (Test-Gateway -Port $Port) {
        $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(46, 160, 67)
        $statusText.Text = '运行中 — WebUI 可访问'
        $statusText.ForeColor = [System.Drawing.Color]::FromArgb(20, 49, 92)
        $statusHint.Text = "http://127.0.0.1:$Port/    5 个 Agent 已加载"
    } else {
        $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(211, 84, 0)
        $statusText.Text = '已停止'
        $statusText.ForeColor = [System.Drawing.Color]::FromArgb(211, 84, 0)
        $statusHint.Text = '点击「启动系统」开始（冷启动约 1-2 分钟）'
    }
})

$form.Add_Shown({
    $timer.Start()
    if (Test-Gateway -Port $Port) {
        $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(46, 160, 67)
        $statusText.Text = '运行中 — WebUI 可访问'
        $statusHint.Text = "http://127.0.0.1:$Port/    5 个 Agent 已加载"
    } else {
        $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(211, 84, 0)
        $statusText.Text = '已停止'
        $statusHint.Text = '点击「启动系统」开始（冷启动约 1-2 分钟）'
    }
})
$form.Add_FormClosed({ $timer.Stop() })

# ---------------------------------------------------------------- 自检 / 运行
if ($SelfTest) {
    $expected = 11
    $count = $form.Controls.Count
    Write-Output "窗体控件数：$count"
    Write-Output "按钮数：$(($form.Controls | Where-Object { $_ -is [System.Windows.Forms.Button] }).Count)"
    Write-Output "状态文本：$($statusText.Text)"
    Write-Output "网关探测：$(Test-Gateway -Port $Port)"
    $form.Dispose()
    if ($count -lt $expected) {
        Write-Output '自检失败：控件数量不足'
        exit 1
    }
    Write-Output '自检通过'
    exit 0
}

[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::Run($form)
