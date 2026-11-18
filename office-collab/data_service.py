#!/usr/bin/env python3
"""Local data interface used by DataAgent and the collaboration orchestrator."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

DEPARTMENT_ALIASES = {
    "技术": "技术部",
    "研发": "技术部",
    "tech": "技术部",
    "行政": "行政部",
    "admin": "行政部",
}


def normalize_quarter(value: str) -> str:
    value = value.strip()
    match = re.search(r"(20\d{2}).*?(?:Q([1-4])|第([一二三四])季度|([1-4])季度)", value, re.I)
    if not match:
        return value
    numerals = {"一": "1", "二": "2", "三": "3", "四": "4"}
    quarter = match.group(2) or numerals.get(match.group(3) or "", match.group(4))
    return f"{match.group(1)}-Q{quarter}"


def infer_request_context(request: str) -> tuple[str | None, str | None]:
    department = None
    for alias, canonical in DEPARTMENT_ALIASES.items():
        if alias.lower() in request.lower():
            department = canonical
            break
    quarter_match = re.search(
        r"20\d{2}.*?(?:Q[1-4]|第[一二三四]季度|[1-4]季度)", request, re.I
    )
    period = normalize_quarter(quarter_match.group(0)) if quarter_match else None
    return department, period


def _read_csv(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_text_notes() -> list[dict[str, str]]:
    path = DATA_DIR / "notes.txt"
    if not path.exists():
        return []
    notes: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "|" not in line:
            continue
        department, period, text = line.split("|", 2)
        notes.append(
            {
                "department": department.strip(),
                "period": normalize_quarter(period),
                "text": text.strip(),
                "source": str(path),
            }
        )
    return notes


def _read_docx_notes() -> list[dict[str, str]]:
    """Read pipe-delimited paragraphs or tables from an optional notes.docx."""
    path = DATA_DIR / "notes.docx"
    if not path.exists():
        return []
    try:
        from docx import Document
    except ImportError:
        return [
            {
                "department": "",
                "period": "",
                "text": "python-docx unavailable; notes.docx was not read",
                "source": str(path),
                "error": True,
            }
        ]

    document = Document(path)
    candidates: list[str] = [paragraph.text.strip() for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            candidates.append(" | ".join(cell.text.strip() for cell in row.cells))

    notes: list[dict[str, str]] = []
    for value in candidates:
        if "|" not in value:
            continue
        parts = [part.strip() for part in value.split("|", 2)]
        if len(parts) != 3:
            continue
        notes.append(
            {
                "department": parts[0],
                "period": normalize_quarter(parts[1]),
                "text": parts[2],
                "source": str(path),
            }
        )
    return notes


def _filter(rows: list[dict[str, Any]], department: str, period: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("department") == department and normalize_quarter(str(row.get("period", ""))) == period
    ]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _validate(
    projects: list[dict[str, Any]],
    attendance: list[dict[str, Any]],
    achievements: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    for project in projects:
        progress = _number(project.get("progress"), -1)
        if not 0 <= progress <= 100:
            issues.append(
                {
                    "severity": "error",
                    "field": "progress",
                    "message": f"项目进度超出范围: {project.get('project', '')}={progress}",
                }
            )
    for item in attendance:
        headcount = _number(item.get("headcount"), -1)
        if headcount <= 0:
            issues.append(
                {
                    "severity": "error",
                    "field": "headcount",
                    "message": "部门人数必须大于 0",
                }
            )
        expected = _number(item.get("expected_workdays"), 0)
        actual = _number(item.get("actual_workdays"), 0)
        leave = _number(item.get("leave_days"), 0)
        if expected <= 0 or actual > expected or leave > expected:
            issues.append(
                {
                    "severity": "error",
                    "field": "attendance",
                    "message": "出勤工作日数据不自洽",
                }
            )
    for item in achievements:
        target = _number(item.get("target"), 0)
        value = _number(item.get("value"), 0)
        if target > 0 and value < 0:
            issues.append(
                {
                    "severity": "error",
                    "field": "achievement",
                    "message": f"成果指标异常: {item.get('metric', '')}",
                }
            )
    if not projects:
        issues.append({"severity": "warning", "field": "projects", "message": "未找到项目数据"})
    if not achievements:
        issues.append({"severity": "warning", "field": "achievements", "message": "未找到成果数据"})
    return {"ok": not any(issue["severity"] == "error" for issue in issues), "issues": issues}


def collect(department: str, period: str) -> dict[str, Any]:
    period = normalize_quarter(period)
    project_rows = _read_csv("projects.csv")
    attendance_rows = _read_csv("attendance.csv")
    achievement_rows = _read_csv("achievements.csv")
    note_rows = _read_text_notes() + _read_docx_notes()

    projects = _filter(project_rows, department, period)
    attendance = _filter(attendance_rows, department, period)
    achievements = _filter(achievement_rows, department, period)
    notes = _filter(note_rows, department, period)
    validation = _validate(projects, attendance, achievements)

    completed = sum(1 for item in projects if item.get("status") == "已完成")
    in_progress = sum(1 for item in projects if item.get("status") == "进行中")
    attendance_rate = None
    if attendance:
        expected = sum(_number(item.get("expected_workdays")) for item in attendance)
        actual = sum(_number(item.get("actual_workdays")) for item in attendance)
        attendance_rate = round(actual / expected * 100, 1) if expected else None

    sources = sorted(
        {
            str(DATA_DIR / "projects.csv"),
            str(DATA_DIR / "attendance.csv"),
            str(DATA_DIR / "achievements.csv"),
            *[item.get("source", "") for item in notes if item.get("source")],
        }
    )
    return {
        "department": department,
        "period": period,
        "sources": sources,
        "projects": projects,
        "attendance": attendance,
        "achievements": achievements,
        "notes": notes,
        "summary": {
            "project_count": len(projects),
            "completed": completed,
            "in_progress": in_progress,
            "attendance_rate_percent": attendance_rate,
        },
        "validation": validation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--department")
    parser.add_argument("--period")
    parser.add_argument("--request")
    args = parser.parse_args()

    department = args.department
    period = args.period
    if args.request:
        inferred_department, inferred_period = infer_request_context(args.request)
        department = department or inferred_department
        period = period or inferred_period
    if not department or not period:
        parser.error("--department and --period are required when they cannot be inferred")

    print(json.dumps(collect(department, normalize_quarter(period)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
