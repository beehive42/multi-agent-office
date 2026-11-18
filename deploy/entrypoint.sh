#!/usr/bin/env bash
# 容器入口：准备配置 → 启动 Gateway（前台，作为容器的 1 号进程树）。
set -euo pipefail

export OPENCLAW_HOME="${OPENCLAW_HOME:-/app}"
export GATEWAY_PORT="${GATEWAY_PORT:-8000}"
export GATEWAY_BIND="${GATEWAY_BIND:-lan}"
export TMP="${TMP:-/app/.tmp-openclaw}"
export TEMP="$TMP"
export TMPDIR="$TMP"
export HOME="${HOME:-/app/.home}"

mkdir -p "$OPENCLAW_HOME/.openclaw" "$OPENCLAW_HOME/logs" "$TMP" "$HOME"

CONFIG="$OPENCLAW_HOME/.openclaw/openclaw.json"
KEY_FILE="$OPENCLAW_HOME/.openclaw/deepseek-api-key.txt"

# 允许通过环境变量注入 API Key（与 compose 的 DEEPSEEK_API_KEY 对应）
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  umask 077
  printf '%s' "$DEEPSEEK_API_KEY" > "$KEY_FILE"
fi

if [ ! -f "$CONFIG" ]; then
  cat >&2 <<'EOF'
[entrypoint] 缺少 /app/.openclaw/openclaw.json。
请在宿主机上先完成 OpenClaw 初始化（运行 deploy/start-gateway.ps1，或执行 openclaw onboard），
然后用 docker compose 启动，让 ./.openclaw 挂载进容器。
EOF
  exit 1
fi

if [ ! -f "$KEY_FILE" ] && [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "[entrypoint] 警告：未提供 DeepSeek API Key，模型调用会失败。" >&2
fi

echo "[entrypoint] OpenClaw $(openclaw --version 2>/dev/null || echo '?')"
echo "[entrypoint] PDF 引擎: ${OFFICE_COLLAB_PDF_ENGINE:-auto} (${OFFICE_COLLAB_CHROME_PATH:-auto})"
echo "[entrypoint] 监听: 0.0.0.0:${GATEWAY_PORT}"

# Gateway 是长驻前台进程；tini 负责信号转发与僵尸回收。
exec openclaw gateway run --port "$GATEWAY_PORT" --bind "$GATEWAY_BIND"
