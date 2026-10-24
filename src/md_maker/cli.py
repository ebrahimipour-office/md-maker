"""md-maker: convert PDF/DOCX files to token-cheap Markdown, Persian included."""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from .office import FORMATS, office_to_markdown
from .pdf import pdf_to_markdown

SUPPORTED = {".pdf", *FORMATS}


def tidy(md: str) -> str:
    """Drop whitespace and markup that cost tokens but carry no meaning."""
    md = re.sub(r"[ \t]+$", "", md, flags=re.M)
    md = re.sub(r"^(#+) \*\*(.+?)\*\*$", r"\1 \2", md, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def convert(path: Path, args) -> str:
    if path.suffix.lower() == ".pdf":
        md = pdf_to_markdown(
            path,
            engine=args.engine,
            ocr=args.ocr,
            lang=args.lang,
            spacing=not args.no_fix_spacing,
            page_markers=args.page_markers,
        )
    else:
        media = args.media / path.stem if args.media else None
        md = office_to_markdown(path, media_dir=media)
    md = tidy(md)
    if args.rtl_wrap:
        md = f'<div dir="rtl">\n\n{md.strip()}\n\n</div>\n'
    return md


def collect(inputs: list[Path]) -> list[tuple[Path, Path]]:
    """(file, path relative to its input root) for every supported file."""
    found = []
    for item in inputs:
        if item.is_dir():
            for f in sorted(item.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED:
                    found.append((f, f.relative_to(item)))
        elif item.is_file():
            found.append((item, Path(item.name)))
        else:
            print(f"md-maker: not found: {item}", file=sys.stderr)
    return found


def target(src: Path, rel: Path, out: Path | None, single: bool, clash: bool) -> Path:
    # report.pdf + report.docx in one run -> report.pdf.md / report.docx.md
    suffix = src.suffix + ".md" if clash else ".md"
    if out is None:
        return src.with_suffix(suffix)
    if single and out.suffix.lower() == ".md":
        return out
    return out / rel.with_suffix(suffix)


def _size(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="md-maker",
        description="Convert PDF and DOCX (also ODT, RTF, EPUB, HTML) to Markdown. "
        "Handles Persian/Arabic text and OCRs scanned PDFs.",
    )
    p.add_argument("inputs", nargs="+", type=Path, help="files or folders")
    p.add_argument("-o", "--output", type=Path, help="output .md file (one input) or folder")
    p.add_argument("--stdout", action="store_true", help="print Markdown instead of writing files")
    p.add_argument("--engine", choices=["auto", "rtl", "layout"], default="auto",
                   help="PDF engine: rtl = Persian-aware, layout = pymupdf4llm (default: auto-detect)")
    p.add_argument("--ocr", choices=["auto", "always", "never"], default="auto",
                   help="OCR scanned pages (needs tesseract; default: auto)")
    p.add_argument("--lang", default="fas+eng", help="tesseract OCR languages (default: fas+eng)")
    p.add_argument("--no-fix-spacing", action="store_true",
                   help="don't restore Persian half-spaces (می‌شود, کتاب‌ها) in PDFs")
    p.add_argument("--page-markers", action="store_true", help="mark page boundaries in PDF output")
    p.add_argument("--rtl-wrap", action="store_true", help='wrap output in <div dir="rtl"> for viewers')
    p.add_argument("--media", type=Path, help="extract DOCX images into this folder")
    p.add_argument("-q", "--quiet", action="store_true")
    args = p.parse_args(argv)

    files = collect(args.inputs)
    if not files:
        print("md-maker: no supported files found", file=sys.stderr)
        return 1
    stems = Counter(target(src, rel, args.output, False, False) for src, rel in files)
    failed = 0
    for src, rel in files:
        try:
            md = convert(src, args)
        except Exception as e:
            failed += 1
            print(f"md-maker: {src}: {e}", file=sys.stderr)
            continue
        if args.stdout:
            sys.stdout.write(md)
            continue
        clash = stems[target(src, rel, args.output, False, False)] > 1
        dest = target(src, rel, args.output, len(files) == 1, clash)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(md, encoding="utf-8")
        if not args.quiet:
            print(f"{src} -> {dest}  ({_size(src.stat().st_size)} -> {_size(len(md.encode()))})")
    return 1 if failed else 0
