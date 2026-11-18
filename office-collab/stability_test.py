#!/usr/bin/env python3
"""Continuous stability test for the five-agent office collaboration system.

Runs the pipeline repeatedly for a requested duration, recording latency, exit
status, review rounds, and any error for every iteration. This is the evidence
the lab guide asks for under "连续运行系统 30 分钟，排查崩溃、异常退出".

Examples
--------
    # 30 minutes, cheap planning-only iterations every 2 minutes
    python stability_test.py --minutes 30 --interval 120

    # 3 iterations of the full pipeline including PDF export
    python stability_test.py --iterations 3 --mode full --format markdown,pdf
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import system  # noqa: E402

DEFAULT_REQUEST = (
    "生成2026年第二季度技术部工作汇报，包含项目进度、人员考勤、成果统计，格式为Markdown"
)
STATE_DIR = Path(__file__).resolve().parent / "state" / "stability"


def _append(result_path: Path, record: dict) -> None:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    with result_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_once(request: str, mode: str, formats: tuple[str, ...]) -> dict:
    started = time.monotonic()
    record: dict = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "mode": mode,
        "request": request,
    }
    try:
        if mode == "analysis":
            result = system.run_analysis(request)
            record["stages"] = sorted(result.keys())
        else:
            result = system.run_full(
                request,
                Path(__file__).resolve().parent / "outputs",
                formats=formats,
            )
            record["stages"] = ["manager", "planner", "data", "writer", "checker", "accept"]
            record["output_files"] = result.get("output_files", [])
            record["review_rounds"] = result.get("review_rounds")
            record["numeric_ok"] = (result.get("numeric_check") or {}).get("ok")
            record["export_errors"] = result.get("export_errors", [])
        record["ok"] = not record.get("export_errors")
    except Exception as exc:  # noqa: BLE001 - the point is to record every failure
        record["ok"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()[-2000:]
    record["elapsed_s"] = round(time.monotonic() - started, 2)
    return record


def summarize(records: list[dict]) -> dict:
    if not records:
        return {"iterations": 0}
    durations = [item["elapsed_s"] for item in records]
    failures = [item for item in records if not item.get("ok")]
    return {
        "iterations": len(records),
        "success": len(records) - len(failures),
        "failures": len(failures),
        "success_rate_percent": round((len(records) - len(failures)) / len(records) * 100, 1),
        "elapsed_total_s": round(sum(durations), 1),
        "elapsed_min_s": min(durations),
        "elapsed_max_s": max(durations),
        "elapsed_mean_s": round(statistics.fmean(durations), 2),
        "elapsed_p95_s": round(
            sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 2
        ),
        "failure_messages": [item.get("error") for item in failures],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="五 Agent 协作系统稳定性测试")
    parser.add_argument("--request", default=DEFAULT_REQUEST)
    parser.add_argument("--mode", choices=("analysis", "full"), default="analysis")
    parser.add_argument("--format", default="markdown,pdf")
    parser.add_argument("--minutes", type=float, default=0, help="运行时长（分钟）")
    parser.add_argument("--iterations", type=int, default=0, help="固定轮次数")
    parser.add_argument("--interval", type=float, default=120, help="轮次间隔秒数")
    parser.add_argument("--report", help="汇总 JSON 输出路径")
    args = parser.parse_args()

    if not args.minutes and not args.iterations:
        parser.error("请指定 --minutes 或 --iterations 之一")

    formats = tuple(item.strip() for item in args.format.split(",") if item.strip())
    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    result_path = STATE_DIR / (datetime.now().strftime("%Y%m%d-%H%M%S") + ".jsonl")
    records: list[dict] = []
    index = 0

    print(f"稳定性测试开始：mode={args.mode} formats={formats} log={result_path}")
    while True:
        index += 1
        record = run_once(args.request, args.mode, formats)
        record["iteration"] = index
        records.append(record)
        _append(result_path, record)
        status = "OK " if record["ok"] else "FAIL"
        print(f"  [{index:>3}] {status} {record['elapsed_s']:>6.1f}s  {record.get('error', '')}")

        if args.iterations and index >= args.iterations:
            break
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(args.interval, remaining))
        elif args.interval:
            time.sleep(args.interval)

    summary = summarize(records)
    summary["mode"] = args.mode
    summary["formats"] = list(formats)
    summary["log"] = str(result_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.report:
        Path(args.report).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0 if summary.get("failures", 1) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
