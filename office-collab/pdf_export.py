#!/usr/bin/env python3
"""Print-engine backend used by WriterAgent's document export.

This module is deliberately *not* the owner of the export capability — see
``agents/writer_agent.py``. It is the low-level renderer: Markdown → standalone
HTML → a print engine (LibreOffice / Chromium / Word).

Keeping the engine separate from the agent means the same Markdown always
produces the same PDF, and the engine can be tested without a model call.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ENGINE_ENV = "OFFICE_COLLAB_PDF_ENGINE"

CHROMIUM_CANDIDATES = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/microsoft-edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

SOFFICE_CANDIDATES = (
    "soffice",
    "libreoffice",
    r"%ProgramFiles%\LibreOffice\program\soffice.exe",
    r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)

FONT_STACK = (
    '"Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", '
    '"Source Han Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei", '
    '"Segoe UI", Arial, sans-serif'
)

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: %(font)s;
  font-size: 10.5pt; line-height: 1.7; color: #1c1c1e;
  margin: 0; padding: 0;
}
h1 {
  font-size: 19pt; line-height: 1.35; margin: 0 0 14pt 0;
  padding-bottom: 8pt; border-bottom: 2px solid #2f6feb; color: #14315c;
}
h2 {
  font-size: 14pt; margin: 18pt 0 8pt 0; padding-left: 8pt;
  border-left: 4px solid #2f6feb; color: #14315c;
  break-after: avoid; page-break-after: avoid;
}
h3 { font-size: 12pt; margin: 13pt 0 6pt 0; color: #243b53; }
h4 { font-size: 11pt; margin: 11pt 0 5pt 0; }
p { margin: 0 0 7pt 0; }
ul, ol { margin: 0 0 8pt 0; padding-left: 18pt; }
li { margin: 0 0 3pt 0; }
table {
  border-collapse: collapse; width: 100%%; margin: 8pt 0 12pt 0;
  font-size: 9.5pt; break-inside: avoid; page-break-inside: avoid;
}
th, td { border: 1px solid #c8d2e0; padding: 5pt 7pt; text-align: left; vertical-align: top; }
th { background: #eef3fb; font-weight: 600; color: #14315c; }
tr:nth-child(even) td { background: #fafbfd; }
code {
  font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
  font-size: 9.5pt; background: #f2f4f7; padding: 1pt 3pt; border-radius: 3px;
}
pre { background: #f6f8fa; border: 1px solid #e2e8f0; padding: 8pt; overflow-x: auto; }
pre code { background: none; padding: 0; }
blockquote { margin: 8pt 0; padding: 4pt 10pt; border-left: 3px solid #c8d2e0; color: #4a5568; }
hr { border: none; border-top: 1px solid #dfe6ef; margin: 12pt 0; }
.meta { color: #6b7785; font-size: 9pt; margin: -8pt 0 14pt 0; }
""" % {"font": FONT_STACK}


class PdfExportError(RuntimeError):
    """Raised when no usable print engine can produce a PDF."""


def _expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def _first_existing(candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        expanded = _expand(candidate)
        if os.sep in expanded or "/" in expanded or ":" in expanded:
            if Path(expanded).is_file():
                return expanded
        else:
            found = shutil.which(expanded)
            if found:
                return found
    return None


def discover_engines() -> dict[str, str]:
    """Return every print engine available on this machine."""
    engines: dict[str, str] = {}
    soffice = _first_existing(SOFFICE_CANDIDATES)
    if soffice:
        engines["soffice"] = soffice
    chromium = _first_existing((os.environ.get("OFFICE_COLLAB_CHROME_PATH") or "", *CHROMIUM_CANDIDATES))
    if chromium:
        engines["chromium"] = chromium
    word = _discover_word()
    if word:
        engines["word"] = word
    return engines


def _discover_word() -> str | None:
    if os.name != "nt":
        return None
    try:
        import win32com.client  # noqa: F401  (presence check only)
    except Exception:
        return None
    return "win32com"


def resolve_engine(preferred: str | None = None) -> tuple[str, str]:
    """Pick the engine to use and return ``(name, executable)``."""
    engines = discover_engines()
    requested = (preferred or os.environ.get(ENGINE_ENV) or "").strip().lower()
    if requested:
        if requested not in engines:
            available = ", ".join(sorted(engines)) or "none"
            raise PdfExportError(
                f"请求的 PDF 引擎 '{requested}' 不可用；当前可用引擎：{available}。"
            )
        return requested, engines[requested]
    for name in ("soffice", "chromium", "word"):
        if name in engines:
            return name, engines[name]
    raise PdfExportError(
        "未找到可用的 PDF 转换引擎。请安装 LibreOffice（soffice）或 "
        "Chrome/Edge/Chromium 任一浏览器，或设置环境变量 "
        f"{ENGINE_ENV}=soffice|chromium|word。"
    )


_LIST_ITEM = re.compile(r"^\s{0,3}[-*+] ")


def _ensure_list_spacing(text: str) -> str:
    """Markdown needs a blank line before a list that follows a prose line."""
    lines = text.split("\n")
    output: list[str] = []
    for line in lines:
        if _LIST_ITEM.match(line) and output:
            previous = output[-1]
            if (
                previous.strip()
                and not _LIST_ITEM.match(previous)
                and not previous.lstrip().startswith("|")
                and not previous.lstrip().startswith("#")
            ):
                output.append("")
        output.append(line)
    return "\n".join(output)


def markdown_to_html(markdown_text: str, title: str | None = None) -> str:
    """Render Markdown to a standalone, print-ready HTML document."""
    try:
        import markdown as markdown_lib
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise PdfExportError(
            "缺少 Markdown 依赖：请在虚拟环境执行 pip install markdown"
        ) from exc

    body = markdown_lib.markdown(
        _ensure_list_spacing(markdown_text),
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
        output_format="html5",
    )
    document_title = title or _infer_title(markdown_text)
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        f"<title>{html.escape(document_title)}</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def _infer_title(markdown_text: str) -> str:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or "工作汇报"
    return "工作汇报"


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )


def _print_with_chromium(executable: str, html_path: Path, pdf_path: Path, timeout: int) -> None:
    with tempfile.TemporaryDirectory(prefix="office-collab-pdf-") as profile:
        command = [
            executable,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--virtual-time-budget=4000",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}",
            "--no-pdf-header-footer",
            _file_url(html_path),
        ]
        completed = _run(command, timeout)
        if not pdf_path.exists():
            detail = (completed.stderr or completed.stdout).strip()[-1200:]
            raise PdfExportError(f"Chromium 未生成 PDF（exit={completed.returncode}）：{detail}")


def _print_with_soffice(executable: str, html_path: Path, pdf_path: Path, timeout: int) -> None:
    with tempfile.TemporaryDirectory(prefix="office-collab-pdf-") as out_dir:
        command = [
            executable,
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            out_dir,
            str(html_path),
        ]
        completed = _run(command, timeout)
        produced = Path(out_dir) / (html_path.stem + ".pdf")
        if not produced.exists():
            detail = (completed.stderr or completed.stdout).strip()[-1200:]
            raise PdfExportError(f"LibreOffice 未生成 PDF（exit={completed.returncode}）：{detail}")
        shutil.move(str(produced), str(pdf_path))


def _print_with_word(html_path: Path, pdf_path: Path) -> None:
    import win32com.client  # type: ignore[import-not-found]

    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    document = None
    try:
        document = word.Documents.Open(str(html_path.resolve()), ConfirmConversions=False)
        document.SaveAs(str(pdf_path.resolve()), FileFormat=17)  # 17 = wdFormatPDF
    finally:
        if document is not None:
            document.Close(False)
        word.Quit()


def _verify_pdf(pdf_path: Path, minimum_bytes: int = 800) -> None:
    if not pdf_path.exists():
        raise PdfExportError(f"PDF 未生成：{pdf_path}")
    size = pdf_path.stat().st_size
    if size < minimum_bytes:
        raise PdfExportError(f"PDF 体积异常（{size} 字节），可能只生成了空白页：{pdf_path}")
    with pdf_path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise PdfExportError(f"文件不是有效 PDF：{pdf_path}")


def export_pdf(
    markdown_text: str,
    pdf_path: Path,
    *,
    title: str | None = None,
    engine: str | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    """Convert Markdown text into ``pdf_path`` and return export metadata."""
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    engine_name, executable = resolve_engine(engine)
    document_html = markdown_to_html(markdown_text, title)

    with tempfile.TemporaryDirectory(prefix="office-collab-html-") as tmp:
        html_path = Path(tmp) / f"{pdf_path.stem}.html"
        html_path.write_text(document_html, encoding="utf-8")
        if engine_name == "chromium":
            _print_with_chromium(executable, html_path, pdf_path, timeout)
        elif engine_name == "soffice":
            _print_with_soffice(executable, html_path, pdf_path, timeout)
        elif engine_name == "word":
            _print_with_word(html_path, pdf_path)
        else:  # pragma: no cover - resolve_engine already guards this
            raise PdfExportError(f"未知的 PDF 引擎：{engine_name}")

    _verify_pdf(pdf_path)
    return {
        "engine": engine_name,
        "executable": executable,
        "pdf": str(pdf_path),
        "bytes": pdf_path.stat().st_size,
    }


def export_markdown_file(
    source: Path,
    target: Path | None = None,
    *,
    engine: str | None = None,
) -> dict[str, Any]:
    source = Path(source)
    text = source.read_text(encoding="utf-8")
    return export_pdf(text, target or source.with_suffix(".pdf"), engine=engine)


def main() -> int:
    parser = argparse.ArgumentParser(description="把 Markdown 汇报转换为 PDF")
    parser.add_argument("--input", help="输入 Markdown 文件")
    parser.add_argument("--output", help="输出 PDF 路径（默认与输入同名）")
    parser.add_argument("--engine", choices=("soffice", "chromium", "word"))
    parser.add_argument("--list-engines", action="store_true", help="只列出可用引擎")
    args = parser.parse_args()

    if args.list_engines:
        print({"available": discover_engines()})
        return 0
    if not args.input:
        parser.error("--input is required unless --list-engines is used")

    source = Path(args.input).resolve()
    if not source.is_file():
        print(f"输入文件不存在：{source}")
        return 1
    target = Path(args.output).resolve() if args.output else source.with_suffix(".pdf")
    try:
        result = export_markdown_file(source, target, engine=args.engine)
    except PdfExportError as exc:
        print(f"PDF 导出失败：{exc}")
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
