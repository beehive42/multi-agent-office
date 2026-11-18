#!/usr/bin/env python3
"""Deterministic format checks used by CheckerAgent."""

from __future__ import annotations

import re
from typing import Any


def validate_markdown(markdown: str, required_terms: list[str]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    text = markdown.strip()
    if not text:
        issues.append({"severity": "error", "code": "empty", "message": "内容为空"})
        return {"ok": False, "issues": issues}

    if not text.startswith("# "):
        issues.append(
            {
                "severity": "error",
                "code": "missing-title",
                "message": "Markdown 必须以一级标题开始",
            }
        )
    if not re.search(r"^##\s+\S+", text, re.MULTILINE):
        issues.append(
            {
                "severity": "error",
                "code": "missing-sections",
                "message": "至少需要一个二级标题",
            }
        )
    for term in required_terms:
        if term and term not in text:
            issues.append(
                {
                    "severity": "warning",
                    "code": "missing-term",
                    "message": f"缺少关键信息: {term}",
                }
            )
    if "TODO" in text or "待补充" in text:
        issues.append(
            {
                "severity": "error",
                "code": "placeholder",
                "message": "内容包含未完成占位符",
            }
        )

    headings = re.findall(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
    for index, (level, title) in enumerate(headings):
        if not title.strip():
            issues.append(
                {
                    "severity": "error",
                    "code": "empty-heading",
                    "message": f"第 {index + 1} 个标题为空",
                }
            )

    return {"ok": not any(item["severity"] == "error" for item in issues), "issues": issues}


LIST_ITEM = re.compile(r"^\s{0,3}[-*+] ")


def ensure_list_spacing(text: str) -> str:
    """Insert the blank line Markdown requires before a list that follows prose.

    LLM output frequently writes ``附：数据来源`` followed immediately by
    ``- file`` lines. Without the blank line the list renders as plain text in
    both the Markdown preview and the PDF.
    """
    lines = text.split("\n")
    output: list[str] = []
    for line in lines:
        if LIST_ITEM.match(line) and output:
            previous = output[-1]
            if (
                previous.strip()
                and not LIST_ITEM.match(previous)
                and not previous.lstrip().startswith("|")
                and not previous.lstrip().startswith("#")
            ):
                output.append("")
        output.append(line)
    return "\n".join(output)


def normalize_markdown(markdown: str) -> str:
    """Apply safe formatting fixes without changing factual content."""
    text = markdown.replace("\r\n", "\n").strip()
    text = re.sub(r"^(#{1,6})([^\s#])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if text and not text.startswith("# "):
        first_line, separator, remainder = text.partition("\n")
        text = f"# {first_line.lstrip('# ').strip()}"
        if separator:
            text += "\n" + remainder
    text = ensure_list_spacing(text)
    return text.strip() + "\n"


FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．", "0123456789.")

DATA_NUMERIC_FIELDS = {
    "projects": ("progress",),
    "attendance": (
        "headcount",
        "expected_workdays",
        "actual_workdays",
        "leave_days",
        "overtime_hours",
        "satisfaction",
    ),
    "achievements": ("value", "target"),
}


def _numeric_variants(value: float) -> set[str]:
    """Accept the plausible ways a number may be written in prose."""
    variants: set[str] = set()
    if float(value).is_integer():
        variants.add(str(int(value)))
    variants.add(f"{value:g}")
    variants.add(f"{value:.1f}")
    return {item for item in variants if item}


def _normalize_numbers_in_text(text: str) -> str:
    text = text.translate(FULLWIDTH_DIGITS)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 2,730 -> 2730
    return text


def check_numeric_consistency(
    markdown: str,
    data: dict[str, Any],
    scopes: set[str] | None = None,
) -> dict[str, Any]:
    """Verify every verified figure in ``data`` also appears in the report.

    This is a deterministic cross-check so CheckerAgent cannot certify a report
    that silently dropped data. Only presence is asserted; the LLM review still
    owns semantic accuracy.

    ``scopes`` limits the check to the data dimensions the user actually asked
    for (``projects`` / ``attendance`` / ``achievements``). A report that omits
    an unrequested dimension is correct, not defective.
    """
    text = _normalize_numbers_in_text(markdown)
    missing: list[str] = []
    checked = 0
    seen: set[str] = set()
    active = set(scopes) if scopes else set(DATA_NUMERIC_FIELDS)

    for collection, fields in DATA_NUMERIC_FIELDS.items():
        if collection not in active:
            continue
        for row in data.get(collection) or []:
            if not isinstance(row, dict):
                continue
            for field in fields:
                raw = row.get(field)
                if raw is None or str(raw).strip() == "":
                    continue
                try:
                    number = float(str(raw).strip().replace("%", ""))
                except ValueError:
                    continue
                if number <= 0:
                    continue
                token = str(raw).strip()
                if token in seen:
                    continue
                seen.add(token)
                checked += 1
                if not any(variant in text for variant in _numeric_variants(number)):
                    missing.append(token)

    return {
        "ok": not missing,
        "checked": checked,
        "scopes": sorted(active),
        "missing": missing,
    }


SCOPE_KEYWORDS = {
    "projects": ("项目", "进度", "里程碑", "交付周期", "开发"),
    "attendance": ("考勤", "出勤", "请假", "加班", "人员", "人数", "工时"),
    "achievements": (
        "成果",
        "指标",
        "达成",
        "满意度",
        "交付率",
        "缺陷",
        "覆盖率",
        "响应",
        "办结",
        "活动",
    ),
}


def infer_data_scopes(*texts: Any) -> set[str]:
    """Map the user's wording to the data dimensions that must appear in the report."""
    haystack = " ".join(str(item) for item in texts if item)
    scopes = {
        scope
        for scope, keywords in SCOPE_KEYWORDS.items()
        if any(keyword in haystack for keyword in keywords)
    }
    return scopes or set(DATA_NUMERIC_FIELDS)
