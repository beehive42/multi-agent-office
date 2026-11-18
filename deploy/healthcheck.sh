#!/usr/bin/env bash
# 容器健康检查：WebUI 可访问 + 5 个 Agent 全部注册。
set -uo pipefail

PORT="${GATEWAY_PORT:-8000}"
ROOT="${OPENCLAW_HOME:-/app}"

if ! curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/" >/dev/null; then
  echo "WebUI 不可访问（127.0.0.1:${PORT}）" >&2
  exit 1
fi

# 网关就绪后再确认 Agent 注册（首次启动时 Agent 数可能还在加载）
if [ -x "$ROOT/.venv/bin/python" ] && [ -f "$ROOT/office-collab/system.py" ]; then
  if ! "$ROOT/.venv/bin/python" "$ROOT/office-collab/system.py" health >/dev/null 2>&1; then
    echo "Agent 未全部就绪" >&2
    exit 1
  fi
fi

exit 0
