# syntax=docker/dockerfile:1
#
# 多 AI Agent 智能办公协作系统 —— 容器化部署
#
#   docker compose up -d --build
#   docker compose exec office-collab ./deploy/healthcheck.sh
#
# 说明：
#   * 基础镜像自带 Node 24，用于 OpenClaw CLI；
#   * 额外安装 Python 3 与 Chromium：Chromium 既是 PDF 打印引擎，
#     也避免再拉一个 LibreOffice（镜像小 400MB 左右）；
#   * 中文字体来自 fonts-noto-cjk，否则 PDF 会出现方块；
#   * .openclaw 配置通过卷挂载进来，镜像里不烘焙任何 API Key 或 token。

FROM node:24-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENCLAW_HOME=/app \
    OFFICE_COLLAB_PDF_ENGINE=chromium \
    OFFICE_COLLAB_CHROME_PATH=/usr/bin/chromium \
    GATEWAY_PORT=8000

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      python3-venv \
      python3-pip \
      chromium \
      fonts-noto-cjk \
      fontconfig \
      ca-certificates \
      curl \
      git \
      tini \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f

# 与实验环境一致的 OpenClaw 版本
ARG OPENCLAW_VERSION=2026.10.9
RUN npm install --global "openclaw@${OPENCLAW_VERSION}" \
 && npm cache clean --force

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /app/.venv \
 && /app/.venv/bin/python -m pip install --upgrade pip \
 && /app/.venv/bin/python -m pip install -r /app/requirements.txt

COPY office-collab /app/office-collab
COPY openclaw-workspace /app/openclaw-workspace
COPY deploy /app/deploy

RUN mkdir -p /app/.openclaw /app/logs /app/.home /app/.tmp-openclaw \
 && chmod +x /app/deploy/entrypoint.sh /app/deploy/healthcheck.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=240s --retries=6 \
    CMD /app/deploy/healthcheck.sh

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/deploy/entrypoint.sh"]
