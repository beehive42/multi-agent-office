#!/usr/bin/env python3
"""WriterAgent: report composition contract and **document export**.

Per the lab guide, WriterAgent owns two things: writing the report and exporting
it as a document (Markdown / PDF). This module implements the second half — the
part that turns finished Markdown into deliverable files.

Design note — why the model does not "print" the PDF itself
-----------------------------------------------------------
A language model returns text. Asking it to produce a PDF directly means asking
it to emit binary data, which is unreproducible, unverifiable, and fails on every
non-trivial document. The correct agent pattern is the same one used everywhere
in tool-using agents: the WriterAgent **owns the capability** and invokes a
deterministic tool to exercise it. So:

* ownership, contract, skill and CLI entry point live here (WriterAgent);
* the actual print engine (Chromium / LibreOffice / Word) lives in
  ``pdf_export.py`` and is called by this module, never by the model;
* the output is byte-verified (``%PDF-`` header + minimum size) before the
  WriterAgent reports the export as done.

That keeps the capability attributable to WriterAgent while remaining testable
and repeatable — the same Markdown always yields the same document.

CLI
---
    python agents/writer_agent.py formats
    python agents/writer_agent.py export \\
        --input ../outputs/report.md --formats markdown,pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow both `python system.py` (package dir on sys.path) and direct execution.
_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _PACKAGE_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from pdf_export import PdfExportError, discover_engines, export_pdf  # noqa: E402

SUPPORTED_FORMATS = ("markdown", "pdf")


class WriterAgent:
    """The WriterAgent's document-export capability.

    Composition of the prose is driven by the orchestrator, which supplies the
    prompt and records the message log; export is owned here because the
    deliverable artifact is the WriterAgent's responsibility.
    """

    agent_id = "writer"
    name = "WriterAgent"
    supported_formats = SUPPORTED_FORMATS

    # -- capability introspection -------------------------------------------

    def available_engines(self) -> dict[str, str]:
        """Which print engines this WriterAgent can reach on this machine."""
        return discover_engines()

    def capabilities(self) -> dict[str, Any]:
        engines = self.available_engines()
        return {
            "agent": self.name,
            "agent_id": self.agent_id,
            "formats": list(self.supported_formats),
            "pdf_engines": engines,
            "pdf_available": bool(engines),
        }

    # -- export ------------------------------------------------------------

    def export(
        self,
        markdown_text: str,
        output_dir: Path,
        name: str,
        formats: tuple[str, ...] = ("markdown",),
    ) -> dict[str, Any]:
        """Write every requested format and report exactly what was produced."""
        requested = tuple(dict.fromkeys(formats or ("markdown",)))
        unknown = [item for item in requested if item not in SUPPORTED_FORMATS]
        if unknown:
            raise ValueError(
                f"WriterAgent 不支持导出格式 {unknown}；可选：{list(SUPPORTED_FORMATS)}"
            )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        errors: list[str] = []
        engine: str | None = None

        markdown_path = output_dir / f"{name}.md"
        markdown_path.write_text(markdown_text, encoding="utf-8")
        files.append(str(markdown_path))

        if "pdf" in requested:
            pdf_path = output_dir / f"{name}.pdf"
            try:
                result = export_pdf(markdown_text, pdf_path)
                engine = result.get("engine")
                files.append(str(pdf_path))
            except PdfExportError as exc:
                errors.append(f"{self.name} PDF 导出失败：{exc}")

        return {
            "agent": self.name,
            "agent_id": self.agent_id,
            "name": name,
            "formats": list(requested),
            "files": files,
            "pdf_engine": engine,
            "errors": errors,
        }

    def export_file(
        self,
        markdown_path: Path,
        formats: tuple[str, ...] = ("pdf",),
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        markdown_path = Path(markdown_path)
        text = markdown_path.read_text(encoding="utf-8")
        return self.export(
            text,
            output_dir or markdown_path.parent,
            markdown_path.stem,
            formats,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WriterAgent 文档导出（Markdown / PDF）"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("formats", help="列出 WriterAgent 支持的导出格式与引擎")

    export_parser = subparsers.add_parser("export", help="导出汇报文档")
    export_parser.add_argument("--input", required=True, help="Markdown 源文件")
    export_parser.add_argument(
        "--formats", default="markdown,pdf", help="逗号分隔，默认 markdown,pdf"
    )
    export_parser.add_argument("--output-dir", help="输出目录（默认为源文件目录）")
    export_parser.add_argument("--name", help="输出文件名（不含扩展名）")

    args = parser.parse_args()
    agent = WriterAgent()

    if args.command == "formats":
        print(json.dumps(agent.capabilities(), ensure_ascii=False, indent=2))
        return 0

    source = Path(args.input)
    if not source.is_file():
        print(json.dumps({"ok": False, "error": f"输入文件不存在：{source}"}, ensure_ascii=False))
        return 1

    formats = tuple(item.strip() for item in args.formats.split(",") if item.strip())
    output_dir = Path(args.output_dir).resolve() if args.output_dir else source.parent
    name = args.name or source.stem
    result = agent.export(source.read_text(encoding="utf-8"), output_dir, name, formats)
    result["ok"] = not result["errors"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
