# 多 AI Agent 智能办公协作系统

基于 [OpenClaw](https://github.com/openclaw/openclaw) 网关的多 Agent 协作实验项目：五个角色 Agent
（manager / planner / data / writer / checker）按「规划 → 取数 → 撰写 → 校验」的链路协作，
把一份自然语言请求产出为 Markdown / PDF 工作汇报。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `office-collab/` | 核心代码：编排器 `system.py`、数据服务、WriterAgent 导出能力、PDF 引擎、稳定性测试 |
| `office-collab/data/` | 输入数据集（CSV / TXT / DOCX） |
| `office-collab/outputs/` | 已生成的示例报告（`.md` / `.pdf`） |
| `office-collab/agents/` | Agent 侧导出接口（`writer_agent.py`） |
| `deploy/` | 部署层：启动/停止/状态/自启/性能剖析脚本与部署手册 |
| `openclaw-workspace/` | Agent 工作区提示词（`AGENTS.md` / `SOUL.md` / `USER.md` 等） |
| `归档/` | 旧版脚本、历史日志与阶段性文档 |
| `运行截图/` | 运行效果截图 |
| `Dockerfile` · `docker-compose.yml` | 容器化部署定义（镜像内不含密钥） |
| `一键启动.cmd` · `一键停止.cmd` · `一键面板.cmd` | 演示用一键入口 |
| `搭建过程记录.md` | 完整搭建过程与踩坑记录 |
| `实验报告.docx` · `软件体系结构（研究生）实验指导.docx` | 实验报告与指导书 |

## 快速开始

```powershell
.\一键启动.cmd                  # 或 .\deploy\start-gateway.ps1
.\deploy\status.ps1            # 端口 8000 / WebUI / 5 个 Agent / PDF 引擎 自检

.\.venv\Scripts\python.exe .\office-collab\system.py run `
    --request "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计，格式为Markdown，导出为PDF" `
    --mode full --output-dir .\office-collab\outputs
```

容器化部署与故障排查见 [deploy/README.md](deploy/README.md)。

## 未纳入版本管理的内容

以下目录属于可再生成的运行时环境或含密钥，已写入 `.gitignore`：

- `tools/`（Node / Python 便携运行时、npm 与 pip 缓存）、`.venv/`、`.home/`、`.tmp-openclaw/`
- `.openclaw/`（网关配置、`deepseek-api-key.txt`、`gateway-token.txt` 等凭据）、`logs/`
- `openclaw-workspace/agents/`、`openclaw-workspace/hello-agent/`（各 Agent 工作区自成 git 仓库）
- `office-collab/state/`（运行期消息日志与稳定性测试记录）

新机器上请按 `搭建过程记录.md` 第一、二阶段重建运行时，并重新配置 `.openclaw/`。
