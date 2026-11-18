# 停止本实验的 OpenClaw Gateway
$root = $PSScriptRoot
$env:Path = "$root\tools\node;$root\tools\npm-global;$env:Path"
$env:OPENCLAW_HOME = $root
$env:TMP = "$root\.tmp-openclaw"
$env:TEMP = "$root\.tmp-openclaw"
$env:TMPDIR = "$root\.tmp-openclaw"
& "$root\tools\npm-global\openclaw.cmd" gateway stop
