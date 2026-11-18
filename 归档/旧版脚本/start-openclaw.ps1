# 启动 OpenClaw Gateway（兼容旧入口）
#
# 现在只是 deploy\start-gateway.ps1 的薄包装：后台运行、等待就绪、输出启动耗时。
# 想前台调试请用： .\deploy\start-gateway.ps1 -Foreground
$startScript = Join-Path $PSScriptRoot 'deploy\start-gateway.ps1'
& $startScript @args
exit $LASTEXITCODE
