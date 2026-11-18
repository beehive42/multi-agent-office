# 部署手册（模块 5）

本目录提供两种部署方式，二者共用同一套代码：**本地便携部署**（Windows，答辩现场用）和 **容器化部署**（Docker，移植用）。

---

## 一、本地便携部署（推荐用于现场演示）

### 1. 前置检查

```powershell
.\deploy\status.ps1
```

`status.ps1` 会依次检查：端口 8000、WebUI 的 HTTP 响应、5 个 Agent 是否注册、PDF 引擎是否可用、五段协作链路是否完整。

### 2. 启动 / 停止

```powershell
.\deploy\start-gateway.ps1          # 后台启动，等到 WebUI 真正返回 200 才退出
.\deploy\start-gateway.ps1 -Foreground   # 前台运行，便于看日志
.\deploy\stop-gateway.ps1           # 按端口定位进程，不留孤儿
```

`start-gateway.ps1` 与旧版 `start-openclaw.ps1`（已归档至 `归档\旧版脚本\`）的区别：

| 行为 | 旧版 `start-openclaw.ps1` | `deploy\start-gateway.ps1` |
|---|---|---|
| 重复启动 | 会因端口占用失败 | 已在监听则 0 秒返回 |
| 就绪判断 | 无，靠人工等 | 轮询 TCP + HTTP/200 |
| 运行方式 | 前台，关窗口即停 | 默认后台，日志落 `logs\gateway.log` |
| 启动耗时 | 不输出 | 输出冷启动秒数 |
| 编译缓存 | 默认临时目录 | 固定到 `.tmp-openclaw\node-compile-cache`，跨启动复用 |

### 3. 让网关常驻（消除演示时的冷启动）

冷启动实测约 **2 分钟**，瓶颈在配置加载、状态快照、核心恢复三块（用 `.\deploy\gateway-profile.ps1` 可看到逐阶段耗时）。演示时不应该等这个。

```powershell
.\deploy\install-autostart.ps1      # 注册登录自启计划任务（延迟 30s）
.\deploy\uninstall-autostart.ps1    # 取消
```

注册后网关随登录常驻热态，**演示时的启动耗时为 0**。

### 4. 看启动瓶颈

```powershell
.\deploy\gateway-profile.ps1
```

输出最近一次启动的阶段表（按耗时排序），以及"已记录阶段合计 / 未记录部分"。优化前后各跑一次即可对比。

### 5. 跑一次完整任务

```powershell
.\.venv\Scripts\python.exe .\office-collab\system.py run `
    --request "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计，格式为Markdown，导出为PDF" `
    --mode full --output-dir .\office-collab\outputs
```

请求里出现 "PDF" 会自动同时导出 `.md` 与 `.pdf`；也可用 `--format markdown,pdf` 强制指定。

导出的归属是 **WriterAgent**（指导书要求"WriterAgent 实现文档导出"）：

```powershell
# 查看 WriterAgent 支持的格式与可用打印引擎
.\.venv\Scripts\python.exe .\office-collab\agents\writer_agent.py formats

# 单独导出某个已完成的 Markdown
.\.venv\Scripts\python.exe .\office-collab\agents\writer_agent.py export `
    --input .\office-collab\outputs\tech-department-2026-Q2.md --formats markdown,pdf
```

职责划分：`agents/writer_agent.py` 是 WriterAgent 的导出能力（对外接口、格式校验、产物校验），
`pdf_export.py` 只是它调用的打印引擎（LibreOffice / Chromium / Word）。模型只负责撰写正文，
永远不直接输出 PDF 字节。

### 6. 稳定性测试（对应"连续运行 30 分钟"）

```powershell
# 30 分钟，每 2 分钟跑一轮规划阶段
.\.venv\Scripts\python.exe .\office-collab\stability_test.py --minutes 30 --interval 120

# 3 轮完整流程（含 PDF），适合答辩前快速回归
.\.venv\Scripts\python.exe .\office-collab\stability_test.py --iterations 3 --mode full
```

每轮结果实时写入 `office-collab\state\stability\<时间戳>.jsonl`，结束时打印成功率、均值/P95 耗时、失败原因。

---

## 二、容器化部署（Docker）

### 1. 准备

Docker 主机上必须先有一份可用的 `.openclaw` 配置（内含 DeepSeek 凭据与网关认证设置）。**镜像里不烘焙任何密钥**，`.openclaw` 通过卷挂载进来。

> 注意：本机为免去演示时粘贴令牌，本地网关用的是 `gateway.auth.mode: "none"`（仅回环监听）。容器内 `entrypoint.sh` 绑定的是 `0.0.0.0`，**不要把无认证配置直接搬进容器**；容器部署前请把 `.openclaw/openclaw.json` 的 `gateway.auth` 改回 `token` 或 `password` 模式。


```powershell
# 先在宿主机完成一次初始化（本机已有则跳过）
.\deploy\start-gateway.ps1
.\deploy\stop-gateway.ps1
```

### 2. 启动

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."     # 或预先写入 .openclaw\deepseek-api-key.txt
docker compose up -d --build
docker compose ps
```

WebUI：<http://127.0.0.1:8000/>

### 3. 验证

```powershell
docker compose exec office-collab /app/deploy/healthcheck.sh
docker compose exec office-collab /app/.venv/bin/python /app/office-collab/system.py health
docker compose exec office-collab /app/.venv/bin/python /app/office-collab/system.py pdf-engines
```

### 4. 镜像构成

| 层 | 内容 | 作用 |
|---|---|---|
| `node:24-bookworm-slim` | Node 24 | OpenClaw CLI 运行时 |
| `openclaw@2026.10.9` | 全局 npm 包 | 与实验环境版本对齐 |
| `python3` + `/app/.venv` | `requirements.txt` | 编排器与数据管道 |
| `chromium` | 浏览器内核 | **PDF 打印引擎**（headless `--print-to-pdf`） |
| `fonts-noto-cjk` | 中文字体 | 避免 PDF 中文变方块 |
| `tini` | init | 信号转发、回收僵尸进程 |

`HEALTHCHECK` 会同时验证 WebUI 可访问与 5 个 Agent 已注册，`start_period` 设为 240 秒以适应冷启动。

### 5. 与本地部署的路径差异

`office-collab/system.py` 通过 `openclaw_command()` 自动选择 CLI 调用方式：

1. 环境变量 `OFFICE_COLLAB_OPENCLAW_CMD`（显式覆盖）；
2. 仓库内 `tools\node\node.exe` + `tools\npm-global\...\openclaw.mjs`（本地便携安装）；
3. `PATH` 上的 `openclaw`（容器镜像）。

镜像内走第 3 条，因此不需要把 Node 便携包打进镜像。

---

## 三、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `system.py health` 立即报"Gateway 未运行" | 网关没起来 | `.\deploy\start-gateway.ps1` |
| 启动卡在 `config-ready` 很久 | Windows 首次加载配置 + 杀软扫描 | 正常，冷启动约 2 分钟；用自启任务消除 |
| PDF 导出报"未找到可用的 PDF 转换引擎" | 没有 LibreOffice / Chrome / Edge | 装任一浏览器，或设 `OFFICE_COLLAB_PDF_ENGINE` |
| PDF 中文变方块 | 缺 CJK 字体 | 装 `fonts-noto-cjk`（Linux）或确认系统有微软雅黑 |
| `docker compose up` 后立即退出 | 缺 `.openclaw/openclaw.json` | 先完成宿主机初始化再挂载 |
| 端口 8000 被占用 | 旧网关未停 | `.\deploy\stop-gateway.ps1` |

---

## 四、目录与日志

| 路径 | 内容 |
|---|---|
| `logs\gateway.log` | Gateway 运行日志（`start-gateway.ps1` 重定向） |
| `logs\gateway.pid` | 最近一次后台启动的进程号 |
| `office-collab\state\runs\<run_id>\` | 每次运行的 `messages.jsonl`（五段消息）与 `result.json` |
| `office-collab\state\agents\<role>.jsonl` | `test-agent` 产生的单 Agent 调用日志 |
| `office-collab\state\stability\<时间戳>.jsonl` | 稳定性测试逐轮记录 |
| `office-collab\outputs\` | 最终报告 `.md` / `.pdf` |
