#!/usr/bin/env python3
"""Five-agent office collaboration orchestrator for OpenClaw."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.writer_agent import WriterAgent
from data_service import collect, infer_request_context
from markdown_checks import (
    check_numeric_consistency,
    infer_data_scopes,
    normalize_markdown,
    validate_markdown,
)
from pdf_export import discover_engines


ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(__file__).resolve().parent / "state"
LOCAL_NODE = ROOT / "tools" / "node" / "node.exe"
LOCAL_OPENCLAW = (
    ROOT / "tools" / "npm-global" / "node_modules" / "openclaw" / "openclaw.mjs"
)
MODEL = "deepseek/deepseek-v4-pro"
AGENT_IDS = ("manager", "planner", "data", "writer", "checker")
ALL_AGENT_IDS = AGENT_IDS + ("main",)
GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = int(os.environ.get("OPENCLAW_GATEWAY_PORT", "8000"))
SUPPORTED_FORMATS = WriterAgent.supported_formats
WRITER_AGENT = WriterAgent()


class AgentFailure(RuntimeError):
    def __init__(self, agent: str, message: str) -> None:
        super().__init__(f"{agent}: {message}")
        self.agent = agent


@dataclass
class AgentReply:
    text: str
    metadata: dict[str, Any]


def openclaw_command() -> list[str]:
    """Return the argv prefix used to invoke the OpenClaw CLI.

    Supports three layouts so the same code runs on the lab Windows install and
    inside the Linux container:

    1. ``OFFICE_COLLAB_OPENCLAW_CMD`` — explicit override, shell-split.
    2. Local portable install under ``tools/`` (this repository's lab setup).
    3. A global ``openclaw`` executable on ``PATH`` (container image).
    """
    override = os.environ.get("OFFICE_COLLAB_OPENCLAW_CMD", "").strip()
    if override:
        return shlex.split(override)
    if LOCAL_NODE.is_file() and LOCAL_OPENCLAW.is_file():
        return [str(LOCAL_NODE), str(LOCAL_OPENCLAW)]
    executable = shutil.which("openclaw")
    if executable:
        return [executable]
    raise RuntimeError(
        "找不到 OpenClaw CLI：本地 tools/ 安装不存在，PATH 中也没有 openclaw。"
        "请设置 OFFICE_COLLAB_OPENCLAW_CMD 或安装 OpenClaw。"
    )


def _environment() -> dict[str, str]:
    """Build a hermetic environment so OpenClaw state stays inside the project."""
    env = os.environ.copy()
    home = ROOT / ".home"
    tmp = ROOT / ".tmp-openclaw"
    for directory in (
        tmp,
        home / "AppData" / "Local",
        home / "AppData" / "Roaming",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "OPENCLAW_HOME": str(ROOT),
            "HOME": str(home),
            "TMP": str(tmp),
            "TEMP": str(tmp),
            "TMPDIR": str(tmp),
        }
    )
    if os.name == "nt":
        env.update(
            {
                "USERPROFILE": str(home),
                "LOCALAPPDATA": str(home / "AppData" / "Local"),
                "APPDATA": str(home / "AppData" / "Roaming"),
            }
        )
    return env


def gateway_reachable(timeout: float = 1.0) -> bool:
    """Cheap TCP probe so callers fail fast instead of waiting on a dead gateway."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((GATEWAY_HOST, GATEWAY_PORT)) == 0


def require_gateway() -> None:
    if not gateway_reachable():
        raise RuntimeError(
            f"OpenClaw Gateway 未运行（{GATEWAY_HOST}:{GATEWAY_PORT}）。"
            "请先执行 deploy/start-gateway.ps1（或 deploy/entrypoint.sh）启动网关。"
        )


def _extract_payload(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if "payloads" in data:
        payloads = data.get("payloads") or []
        metadata = data.get("meta") or {}
    else:
        result = data.get("result") or {}
        payloads = result.get("payloads") or []
        metadata = result.get("meta") or {}
    if not payloads:
        return "", metadata
    return str(payloads[0].get("text", "")), metadata


def _call_agent_once(agent: str, prompt: str, *, log_path: Path | None = None) -> AgentReply:
    if agent not in ALL_AGENT_IDS:
        raise ValueError(f"Unknown agent: {agent}")
    temp_path: Path | None = None
    started = time.monotonic()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            dir=ROOT / ".tmp-openclaw",
            delete=False,
        ) as handle:
            handle.write(prompt)
            temp_path = Path(handle.name)

        command = [
            *openclaw_command(),
            "agent",
            "--agent",
            agent,
            "--model",
            MODEL,
            "--message-file",
            str(temp_path),
            "--json",
            "--timeout",
            "240",
            "--thinking",
            "off",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=_environment(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=280,
        )
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise AgentFailure(agent, f"exit={completed.returncode}; {detail}")
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AgentFailure(agent, f"invalid JSON response: {completed.stdout[-2000:]}") from exc
        text, metadata = _extract_payload(data)
        if log_path:
            event = {
                "timestamp": datetime.now().astimezone().isoformat(),
                "agent": agent,
                "elapsed_ms": elapsed_ms,
                "prompt_chars": len(prompt),
                "reply_chars": len(text),
                "metadata": {
                    "provider": metadata.get("agentMeta", {}).get("provider"),
                    "model": metadata.get("agentMeta", {}).get("model"),
                    "session": metadata.get("agentMeta", {}).get("sessionId"),
                    "cost": metadata.get("agentMeta", {}).get("costUsd"),
                },
            }
            _append_jsonl(log_path, event)
        return AgentReply(text=text, metadata=metadata)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def call_agent(
    agent: str,
    prompt: str,
    *,
    log_path: Path | None = None,
    attempts: int = 2,
    allow_fallback: bool = True,
) -> AgentReply:
    """Run an agent with bounded retry and temporary reassignment to main."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _call_agent_once(agent, prompt, log_path=log_path)
        except (AgentFailure, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if log_path:
                _append_jsonl(
                    log_path,
                    {
                        "timestamp": datetime.now().astimezone().isoformat(),
                        "stage": "retry",
                        "agent": agent,
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "error": str(exc),
                    },
                )
            if attempt < attempts:
                time.sleep(2)

    if allow_fallback and agent != "main":
        fallback_prompt = (
            f"你被 ManagerAgent 临时改派为 {agent}。必须遵守该角色的输出格式和边界。\n\n"
            + prompt
        )
        if log_path:
            _append_jsonl(
                log_path,
                {
                    "timestamp": datetime.now().astimezone().isoformat(),
                    "stage": "reassign",
                    "from": agent,
                    "to": "main",
                    "reason": str(last_error),
                },
            )
        try:
            return _call_agent_once("main", fallback_prompt, log_path=log_path)
        except (AgentFailure, subprocess.TimeoutExpired) as exc:
            last_error = exc

    raise AgentFailure(agent, f"all attempts failed: {last_error}")


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("Response does not contain a JSON object")


def _request_context(request: str) -> tuple[str, str]:
    department, period = infer_request_context(request)
    if not department or not period:
        raise ValueError(
            "请求中必须包含部门和季度，例如“技术部 2026年第二季度”。"
            f"当前解析结果：department={department!r}, period={period!r}"
        )
    return department, period


def infer_exports(request: str) -> list[str]:
    """Decide the export formats from the request text (Markdown is always built)."""
    exports = ["markdown"]
    lowered = request.lower()
    if "pdf" in lowered or "导出为pdf" in lowered or "生成pdf" in lowered:
        exports.append("pdf")
    return exports


def manager_parse(request: str, log_path: Path | None = None) -> dict[str, Any]:
    prompt = f"""
你是 ManagerAgent。解析用户的部门工作汇报需求，只做任务拆解，不要撰写正文。
必须只输出一个 JSON 对象，不要 Markdown 代码块，不要解释。

用户需求：
{request}

输出字段：
{{
  "request_summary": "需求摘要",
  "department": "部门全称",
  "period": "YYYY-QN",
  "format": "Markdown",
  "exports": ["markdown"] 或 ["markdown", "pdf"],
  "focus": ["重点"],
  "tasks": [
    {{"id": "plan", "agent": "planner", "instruction": "任务"}},
    {{"id": "data", "agent": "data", "instruction": "任务"}},
    {{"id": "write", "agent": "writer", "instruction": "任务"}},
    {{"id": "review", "agent": "checker", "instruction": "任务"}}
  ],
  "data_requirements": ["数据项"],
  "acceptance_criteria": ["验收条件"]
}}

如果用户要求“导出为 PDF”，exports 必须包含 "pdf"。
""".strip()
    reply = call_agent("manager", prompt, log_path=log_path)
    parsed = extract_json(reply.text)
    parsed.setdefault("exports", ["markdown"])
    if "pdf" in infer_exports(request) and "pdf" not in parsed["exports"]:
        parsed["exports"] = list(dict.fromkeys([*parsed["exports"], "pdf"]))
    return parsed


def planner_outline(manager: dict[str, Any], log_path: Path | None = None) -> dict[str, Any]:
    prompt = f"""
你是 PlannerAgent。根据 ManagerAgent 的任务拆解生成汇报大纲。
只输出一个 JSON 对象，不要正文。

任务拆解：
{json.dumps(manager, ensure_ascii=False, indent=2)}

输出字段：
{{
  "title": "汇报标题",
  "sections": [
    {{"heading": "章节标题", "points": ["内容要点"], "data_fields": ["需要的数据字段"]}}
  ],
  "format_rules": ["Markdown 格式要求"]
}}
""".strip()
    reply = call_agent("planner", prompt, log_path=log_path)
    return extract_json(reply.text)


def data_stage(manager: dict[str, Any], log_path: Path | None = None) -> dict[str, Any]:
    department, period = _request_context(
        f"{manager.get('department', '')} {manager.get('period', '')}"
    )
    local_data = collect(department, period)
    prompt = f"""
你是 DataAgent。下面的数据来自本地 DataService，已读取 CSV、TXT、DOCX。
请校验并浓缩为后续写作所需的结构化数据。只输出一个 JSON 对象。

数据需求：
{json.dumps(manager.get("data_requirements", []), ensure_ascii=False)}

本地数据：
{json.dumps(local_data, ensure_ascii=False, indent=2)}

输出必须包含：
"department", "period", "projects", "attendance", "achievements", "notes",
"highlights", "risks", "validation", "sources"
不得添加数据中不存在的事实。
""".strip()
    reply = call_agent("data", prompt, log_path=log_path)
    parsed = extract_json(reply.text)
    if not parsed.get("projects") and local_data.get("projects"):
        parsed["projects"] = local_data["projects"]
    parsed.setdefault("validation", local_data.get("validation", {}))
    parsed.setdefault("sources", local_data.get("sources", []))
    parsed["_local_data"] = local_data
    return parsed


def writer_draft(
    manager: dict[str, Any],
    outline: dict[str, Any],
    data: dict[str, Any],
    log_path: Path | None = None,
) -> str:
    prompt = f"""
你是 WriterAgent。根据大纲和已核验数据撰写完整的中文工作汇报。
只输出 Markdown 正文，不添加解释或代码块（PDF 由编排器统一导出）。
标题使用一级标题，章节使用二级标题。数据必须与输入一致，不得编造。
项目中列出的每个项目都必须在正文中逐项出现，并写明状态、进度、负责人和风险。

ManagerAgent：
{json.dumps(manager, ensure_ascii=False, indent=2)}

PlannerAgent：
{json.dumps(outline, ensure_ascii=False, indent=2)}

DataAgent：
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()
    return call_agent("writer", prompt, log_path=log_path).text


def checker_review(
    markdown: str,
    data: dict[str, Any],
    log_path: Path | None = None,
    scopes: set[str] | None = None,
    numeric_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required_terms = [str(data.get("department", ""))]
    deterministic = validate_markdown(markdown, [term for term in required_terms if term])
    numbers = check_numeric_consistency(markdown, numeric_source or data, scopes)
    prompt = f"""
你是 CheckerAgent。审核汇报的完整性、数据一致性、准确性和 Markdown 格式。
发现可安全修正的格式、标题或遗漏项时，必须直接修改 corrected_markdown，
并在 corrections 中记录修改，不能只报告问题。
只输出一个 JSON 对象，不要正文或代码块。

确定性格式检查：
{json.dumps(deterministic, ensure_ascii=False)}

确定性数值一致性检查（正文缺失的数据值，必须补全或说明原因）：
{json.dumps(numbers, ensure_ascii=False)}

数据：
{json.dumps(data, ensure_ascii=False)}

待审核 Markdown：
{markdown}

输出字段：
{{
  "passed": true,
  "issues": [{{"severity": "error|warning", "message": "问题"}}],
  "corrections": ["修正说明"],
  "corrected_markdown": "修正后的完整 Markdown；无需修正时原样返回"
}}
""".strip()
    reply = call_agent("checker", prompt, log_path=log_path)
    result = extract_json(reply.text)
    issues = list(result.get("issues") or [])
    if not deterministic["ok"]:
        result["passed"] = False
        issues.extend(item for item in deterministic["issues"] if item["severity"] == "error")
    if numbers["missing"]:
        result["passed"] = False
        issues.extend(
            {"severity": "error", "message": f"正文缺失已核验数据值：{value}"}
            for value in numbers["missing"]
        )
    result["issues"] = issues
    result["numeric_check"] = numbers
    return result


def repair_draft(
    manager: dict[str, Any],
    outline: dict[str, Any],
    data: dict[str, Any],
    markdown: str,
    review: dict[str, Any],
    log_path: Path | None = None,
) -> str:
    prompt = f"""
你是 WriterAgent。请根据 CheckerAgent 的问题修订 Markdown，只输出修订后的完整正文。
不得遗漏 DataAgent 中 projects 的任一项目；必须保留全部已核验数字和来源。
不要添加解释或代码块（PDF 由编排器统一导出）。

ManagerAgent：
{json.dumps(manager, ensure_ascii=False)}

PlannerAgent：
{json.dumps(outline, ensure_ascii=False)}

DataAgent：
{json.dumps(data, ensure_ascii=False)}

CheckerAgent 问题：
{json.dumps(review.get("issues", []), ensure_ascii=False)}

当前 Markdown：
{markdown}
""".strip()
    return call_agent("writer", prompt, log_path=log_path).text


def data_coverage_issues(markdown: str, data: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for project in data.get("projects", []):
        name = str(project.get("project", "")).strip()
        if name and name not in markdown:
            issues.append(
                {
                    "severity": "warning",
                    "message": f"正文遗漏项目“{name}”的进度信息",
                }
            )
    return issues


def manager_accept(
    manager: dict[str, Any],
    checker_result: dict[str, Any],
    log_path: Path | None = None,
) -> dict[str, Any]:
    prompt = f"""
你是 ManagerAgent。根据验收标准判断任务是否完成，只输出 JSON。

ManagerAgent 计划：
{json.dumps(manager, ensure_ascii=False)}

CheckerAgent 结果：
{json.dumps(checker_result, ensure_ascii=False)}

输出字段：
{{"accepted": true, "reason": "验收理由", "remaining_issues": ["未解决问题"]}}
""".strip()
    reply = call_agent("manager", prompt, log_path=log_path)
    return extract_json(reply.text)


def run_analysis(request: str) -> dict[str, Any]:
    manager = manager_parse(request)
    outline = planner_outline(manager)
    data = data_stage(manager)
    return {"manager": manager, "planner": outline, "data": data}


def _default_output_name(manager: dict[str, Any], run_id: str) -> str:
    department = str(manager.get("department") or "report").strip()
    period = str(manager.get("period") or "").strip()
    if department and period:
        return f"{department}-{period}"
    return run_id


def export_report(
    markdown_text: str,
    output_dir: Path,
    name: str,
    formats: tuple[str, ...] = ("markdown",),
) -> dict[str, Any]:
    """Delegate document export to WriterAgent, which owns that capability."""
    return WRITER_AGENT.export(markdown_text, output_dir, name, formats)


def run_full(
    request: str,
    output_dir: Path | None = None,
    *,
    formats: tuple[str, ...] | None = None,
    output_name: str | None = None,
) -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = STATE_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "messages.jsonl"
    manager = manager_parse(request, log_path)
    outline = planner_outline(manager, log_path)
    data = data_stage(manager, log_path)
    scopes = infer_data_scopes(request, " ".join(map(str, manager.get("focus") or [])))
    # Ground truth for the numeric gate is the raw DataService payload, not the
    # LLM's distillation: an agent that quietly drops rows must not pass.
    truth = data.get("_local_data") or data
    draft = writer_draft(manager, outline, data, log_path)
    review = checker_review(draft, data, log_path, scopes, truth)
    review_rounds = 1

    issues = list(review.get("issues", [])) + data_coverage_issues(
        str(review.get("corrected_markdown") or draft),
        data,
    )
    if issues:
        revised = repair_draft(
            manager,
            outline,
            data,
            str(review.get("corrected_markdown") or draft),
            {"issues": issues},
            log_path,
        )
        review = checker_review(revised, data, log_path, scopes, truth)
        review_rounds = 2

    corrected = normalize_markdown(str(review.get("corrected_markdown") or draft))
    final_check = validate_markdown(
        corrected,
        [str(data.get("department", ""))],
    )
    if not final_check["ok"]:
        raise RuntimeError(f"Final Markdown validation failed: {final_check['issues']}")
    final_numbers = check_numeric_consistency(corrected, truth, scopes)
    if not final_numbers["ok"]:
        raise RuntimeError(
            "Final numeric consistency check failed: 正文缺失数据值 "
            f"{final_numbers['missing']}"
        )
    acceptance = manager_accept(manager, review, log_path)

    requested_formats = tuple(dict.fromkeys(formats or ("markdown",)))
    unknown = [item for item in requested_formats if item not in SUPPORTED_FORMATS]
    if unknown:
        raise ValueError(f"不支持的导出格式：{unknown}；可选：{list(SUPPORTED_FORMATS)}")

    report: dict[str, Any] = {
        "run_id": run_id,
        "ok": True,
        "request": request,
        "manager": manager,
        "planner": outline,
        "data": data,
        "checker": review,
        "numeric_check": final_numbers,
        "review_rounds": review_rounds,
        "acceptance": acceptance,
        "formats": list(requested_formats),
        "output_files": [],
        "message_log": str(log_path),
    }
    if output_dir:
        name = output_name or _default_output_name(manager, run_id)
        export = export_report(corrected, output_dir, name, requested_formats)
        report["output_files"] = export["files"]
        report["pdf_engine"] = export["pdf_engine"]
        report["exported_by"] = export["agent"]
        report["export_errors"] = export["errors"]
        if export["errors"]:
            report["ok"] = False

    (run_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def verify_route() -> dict[str, Any]:
    stages = [
        ("ManagerAgent", "PlannerAgent", "planning_request", planner_outline),
        ("PlannerAgent", "DataAgent", "data_request", data_stage),
        ("DataAgent", "WriterAgent", "verified_data", writer_draft),
        ("WriterAgent", "CheckerAgent", "draft_review", checker_review),
        ("CheckerAgent", "ManagerAgent", "review_result", manager_accept),
    ]
    return {
        "ok": True,
        "chain": [
            {"from": source, "to": target, "message_type": message_type, "handler": handler.__name__}
            for source, target, message_type, handler in stages
        ],
    }


def verify_route(live: bool = False) -> dict[str, Any]:
    """Verify the collaboration chain for real instead of asserting a constant.

    Static mode proves every stage handler exists, is callable, and covers all
    five agents. Live mode additionally executes one minimal request end to end.
    """
    import inspect

    stages = [
        ("ManagerAgent", "PlannerAgent", "planning_request", planner_outline),
        ("PlannerAgent", "DataAgent", "data_request", data_stage),
        ("DataAgent", "WriterAgent", "verified_data", writer_draft),
        ("WriterAgent", "CheckerAgent", "draft_review", checker_review),
        ("CheckerAgent", "ManagerAgent", "review_result", manager_accept),
    ]
    problems: list[str] = []
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source, target, message_type, handler in stages:
        callable_ok = inspect.isfunction(handler) and callable(handler)
        if not callable_ok:
            problems.append(f"{source}→{target} 的处理器不可调用")
        if handler.__module__ != __name__:
            problems.append(f"{handler.__name__} 未在当前模块实现")
        chain.append(
            {
                "from": source,
                "to": target,
                "message_type": message_type,
                "handler": handler.__name__,
                "callable": callable_ok,
            }
        )
        seen.add(source)
        seen.add(target)

    expected_agents = {"ManagerAgent", "PlannerAgent", "DataAgent", "WriterAgent", "CheckerAgent"}
    missing_agents = sorted(expected_agents - seen)
    if missing_agents:
        problems.append(f"链路未覆盖 Agent：{missing_agents}")

    gateway_up = gateway_reachable()
    if gateway_up:
        try:
            agents = verify_agents()
            if not agents["ok"]:
                problems.append(f"网关缺少 Agent：{agents['missing']}")
        except Exception as exc:  # noqa: BLE001 - surfaced as a problem string
            problems.append(f"无法读取 Agent 列表：{exc}")
    else:
        problems.append("OpenClaw Gateway 未运行，无法验证 Agent 注册状态")

    live_result: dict[str, Any] | None = None
    if live:
        try:
            probe = run_analysis("生成 2026 年第二季度技术部工作汇报，重点说明项目进度。")
            live_result = {
                "manager_ok": bool(probe["manager"].get("department")),
                "planner_ok": bool(probe["planner"].get("sections")),
                "data_ok": bool(probe["data"].get("projects")),
            }
            if not all(live_result.values()):
                problems.append(f"实时链路自检未通过：{live_result}")
        except Exception as exc:  # noqa: BLE001
            live_result = {"error": str(exc)}
            problems.append(f"实时链路自检失败：{exc}")

    return {
        "ok": not problems,
        "mode": "live" if live else "static",
        "chain": chain,
        "gateway_reachable": gateway_up,
        "problems": problems,
        "live": live_result,
    }


def verify_agents() -> dict[str, Any]:
    require_gateway()
    command = [*openclaw_command(), "agents", "list", "--json"]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=_environment(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "读取 Agent 列表超时（60s）。请确认网关已就绪且版本匹配。"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip()[-1500:])
    agents = json.loads(completed.stdout)
    present = {item["id"]: item for item in agents}
    missing = [agent for agent in AGENT_IDS if agent not in present]
    return {
        "ok": not missing,
        "missing": missing,
        "agents": [
            {
                "id": agent,
                "name": present.get(agent, {}).get("name"),
                "model": present.get(agent, {}).get("model"),
            }
            for agent in AGENT_IDS
        ],
    }


def role_test(agent: str) -> dict[str, Any]:
    """Run one role against a fixed test case, logging to state/agents/<role>.jsonl."""
    log_path = STATE_DIR / "agents" / f"{agent}.jsonl"
    request = "生成 2026 年第二季度技术部工作汇报，重点说明项目进度。"
    if agent == "manager":
        result = manager_parse(request, log_path)
    elif agent == "planner":
        result = planner_outline(manager_parse(request, log_path), log_path)
    elif agent == "data":
        result = data_stage(manager_parse(request, log_path), log_path)
    elif agent == "writer":
        manager = manager_parse(request, log_path)
        outline = planner_outline(manager, log_path)
        data = data_stage(manager, log_path)
        markdown = writer_draft(manager, outline, data, log_path)
        result = {
            "test_case": request,
            "markdown": markdown,
            "format_ok": validate_markdown(
                markdown, [str(data.get("department", ""))]
            )["ok"],
            "export": WRITER_AGENT.export(
                normalize_markdown(markdown),
                STATE_DIR / "agents" / "exports",
                f"writer-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                ("markdown", "pdf"),
            ),
        }
    elif agent == "checker":
        sample = (
            "# 技术部2026年第二季度工作汇报\n\n"
            "## 一、项目进度\n\n"
            "本季度技术部共有 5 个项目，其中 3 个已完成。\n\n"
            "## 二、待补充\n\n待补充\n"
        )
        result = checker_review(
            sample,
            {
                "department": "技术部",
                "period": "2026-Q2",
                "projects": [{"project": "智能审批平台", "progress": 100}],
            },
            log_path,
            {"projects"},
        )
        result["test_case"] = "含占位符与缺失数值的样例，应判为不合格"
    else:
        raise ValueError(f"Unknown agent: {agent}")
    return {"agent": agent, "log": str(log_path), "result": result}


def main() -> int:
    parser = argparse.ArgumentParser(description="五 Agent 智能办公协作系统编排器")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="检查网关与 5 个 Agent 是否就绪")
    route_parser = subparsers.add_parser("verify-route", help="验证五段协作链路")
    route_parser.add_argument(
        "--live", action="store_true", help="额外执行一次真实的最小链路自检（会产生模型调用）"
    )
    engines_parser = subparsers.add_parser("pdf-engines", help="列出可用的 PDF 转换引擎")
    role_parser = subparsers.add_parser("test-agent", help="按固定测试用例验证单个 Agent")
    role_parser.add_argument("agent", choices=AGENT_IDS)
    run_parser = subparsers.add_parser("run", help="执行协作流程")
    run_parser.add_argument("--request", required=True)
    run_parser.add_argument("--mode", choices=("analysis", "full"), default="analysis")
    run_parser.add_argument("--output-dir")
    run_parser.add_argument("--output-name", help="输出文件名（不含扩展名）")
    run_parser.add_argument(
        "--format",
        default=None,
        help="导出格式，逗号分隔：markdown,pdf。省略时按需求文本自动判断",
    )
    parser.add_argument("--debug", action="store_true", help="出错时输出完整堆栈")
    args = parser.parse_args()

    if args.command == "health":
        result = verify_agents()
    elif args.command == "verify-route":
        result = verify_route(live=args.live)
    elif args.command == "pdf-engines":
        capabilities = WRITER_AGENT.capabilities()
        result = {
            "ok": capabilities["pdf_available"],
            "owner": capabilities["agent"],
            "formats": capabilities["formats"],
            "available": capabilities["pdf_engines"],
        }
    elif args.command == "test-agent":
        result = role_test(args.agent)
    elif args.mode == "analysis":
        result = run_analysis(args.request)
    else:
        if args.format:
            formats = tuple(
                item.strip().lower() for item in args.format.split(",") if item.strip()
            )
        else:
            formats = tuple(infer_exports(args.request))
        output_dir = (
            Path(args.output_dir).resolve()
            if args.output_dir
            else (Path(__file__).resolve().parent / "outputs")
        )
        result = run_full(
            args.request,
            output_dir,
            formats=formats,
            output_name=args.output_name,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


def cli() -> int:
    try:
        return main()
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        if "--debug" in sys.argv:
            raise
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
