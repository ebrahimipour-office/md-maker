"""md-maker: convert PDF/DOCX files to token-cheap Markdown, Persian included."""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from . import config, ocr
from .office import FORMATS, office_to_markdown
from .pdf import pdf_to_markdown

SUPPORTED = {".pdf", *FORMATS}


def tidy(md: str) -> str:
    """Drop whitespace and markup that cost tokens but carry no meaning."""
    md = re.sub(r"[ \t]+$", "", md, flags=re.M)
    md = re.sub(r"^(#+) \*\*(.+?)\*\*$", r"\1 \2", md, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def convert(path: Path, settings, pipeline=None, media: Path | None = None) -> tuple[str, dict | None]:
    """(Markdown, AI report or None)."""
    report = None
    if path.suffix.lower() == ".pdf" and pipeline:
        md, report = pipeline.convert(path)
    elif path.suffix.lower() == ".pdf":
        md = pdf_to_markdown(
            path,
            engine=settings.pdf.engine,
            ocr=settings.ocr.mode,
            lang=settings.ocr.lang,
            ocr_dpi=settings.ocr.dpi,
            spacing=settings.pdf.fix_spacing,
            page_markers=settings.pdf.page_markers,
        )
    else:
        md = office_to_markdown(path, media_dir=media / path.stem if media else None)
    md = tidy(md)
    if settings.output.rtl_wrap:
        md = f'<div dir="rtl">\n\n{md.strip()}\n\n</div>\n'
    return md, report


def _make_pipeline(settings, quiet: bool):
    """The AI pipeline, or None when AI is off or the CLI is missing."""
    if settings.ai.mode == "off":
        return None
    from .ai.backend import AIError
    from .ai.claude_cli import ClaudeCLI
    from .ai.pipeline import Budget, Pipeline, stderr_log
    from .cache import Cache

    try:
        backend = ClaudeCLI(settings)
    except AIError as e:
        print(f"md-maker: {e}; converting locally (use --ai off to hide this)", file=sys.stderr)
        return None
    cache = Cache(config.cache_dir(settings) if settings.cache.enabled else None)
    log = (lambda msg: None) if quiet else stderr_log
    return Pipeline(settings, backend, Budget(settings.ai.budget_usd), cache, log)


def _print_plan(path: Path, settings):
    import pymupdf

    from .pdf import resolve_engine
    from .triage import triage

    doc = pymupdf.open(path)
    reports = triage(doc, settings)
    print(f"{path}  ({len(doc)} pages, engine: {resolve_engine(doc, settings.pdf.engine, settings.ocr.lang)})")
    models = settings.ai.models
    for r in reports:
        model = getattr(models, r.route, "") if settings.ai.mode != "off" else ""
        print(f"  page {r.page + 1:<4} {r.route:<10} {model:<8} {', '.join(r.reasons)}")
    counts = Counter(r.route for r in reports)
    parts = []
    for route in ("local", "polish", "repair", "transcribe"):
        if counts[route]:
            model = f" ({getattr(models, route)})" if route != "local" else ""
            parts.append(f"{counts[route]} {route}{model}")
    print("  -> " + ", ".join(parts))
    if settings.ai.mode == "off":
        print("  ai.mode is off: every page will be converted locally")


def _toml(d: dict, prefix: str = "") -> str:
    """Minimal TOML writer for the settings (scalars and nested tables)."""
    scalars = [f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in d.items() if not isinstance(v, dict)]
    out = ([f"[{prefix}]"] if prefix and scalars else []) + scalars
    for k, v in d.items():
        if isinstance(v, dict):
            out += ["", _toml(v, f"{prefix}.{k}" if prefix else k)]
    return "\n".join(out).strip()


def _overrides(args) -> dict:
    """Settings given on the command line."""
    o: dict = {}

    def put(section: str, key: str, value):
        if value is not None:
            node = o
            for part in section.split("."):
                node = node.setdefault(part, {})
            node[key] = value

    put("ai", "mode", args.ai)
    put("ai", "budget_usd", args.budget)
    put("pdf", "engine", args.engine)
    put("pdf", "fix_spacing", False if args.no_fix_spacing else None)
    put("pdf", "page_markers", True if args.page_markers else None)
    put("ocr", "mode", args.ocr)
    put("ocr", "lang", args.lang)
    put("ocr", "dpi", args.ocr_dpi)
    put("output", "rtl_wrap", True if args.rtl_wrap else None)
    put("cache", "enabled", False if args.no_cache else None)
    return o


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


def _launched_from_explorer() -> bool:
    """True on Windows when md-maker.exe got its own console window, i.e. a
    file was dropped onto it or it was double-clicked, not run in a terminal."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return ctypes.windll.kernel32.GetConsoleProcessList((ctypes.c_uint * 2)(), 2) == 1
    except Exception:
        return False


def main(argv=None) -> int:
    if not _launched_from_explorer():
        return _main(argv)
    try:
        return _main(argv)
    except SystemExit as e:  # argparse errors / --help
        return e.code if isinstance(e.code, int) else 1
    finally:
        input("\nPress Enter to close...")


def _main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="md-maker",
        description="Convert PDF and DOCX (also ODT, RTF, EPUB, HTML) to Markdown. "
        "Handles Persian/Arabic text and OCRs scanned PDFs; hard PDF pages are "
        "repaired by Claude through the installed `claude` CLI. Defaults come "
        "from the settings file (see --show-config).",
    )
    p.add_argument("inputs", nargs="*", type=Path, help="files or folders")
    p.add_argument("-o", "--output", type=Path, help="output .md file (one input) or folder")
    p.add_argument("--stdout", action="store_true", help="print Markdown instead of writing files")

    ai = p.add_argument_group("AI")
    ai.add_argument("--ai", choices=config.AI_MODES,
                    help="smart = AI only on pages that need it, max = every PDF page, off = local only")
    ai.add_argument("--budget", type=float, metavar="USD", help="stop sending pages to AI after this cost (0 = no limit)")
    ai.add_argument("--plan", action="store_true", help="show how each PDF page would be handled, without converting")
    ai.add_argument("--report", action="store_true", help="also write <name>.report.json: route, model, score, cost per page")
    ai.add_argument("--no-cache", action="store_true", help="don't reuse or store AI results")

    pdf = p.add_argument_group("local conversion")
    pdf.add_argument("--engine", choices=["auto", "rtl", "layout"],
                     help="PDF engine: rtl = Persian-aware, layout = pymupdf4llm (default: auto-detect)")
    pdf.add_argument("--ocr", choices=["auto", "always", "never"],
                     help="OCR scanned pages locally (needs OCR data, see --install-ocr; default: auto)")
    pdf.add_argument("--lang", help="tesseract OCR languages (default: fas+eng)")
    pdf.add_argument("--ocr-dpi", type=int, help="render resolution for OCR; try 150-400 if results are poor")
    pdf.add_argument("--no-fix-spacing", action="store_true",
                     help="don't restore Persian half-spaces (می‌شود, کتاب‌ها) in PDFs")
    pdf.add_argument("--page-markers", action="store_true", help="mark page boundaries in PDF output")
    pdf.add_argument("--rtl-wrap", action="store_true", help='wrap output in <div dir="rtl"> for viewers')
    pdf.add_argument("--media", type=Path, help="extract DOCX images into this folder")

    setup = p.add_argument_group("setup")
    setup.add_argument("--config", type=Path, help="settings file to use on top of the user and project files")
    setup.add_argument("--init-config", action="store_true",
                       help=f"write a commented settings file to {config.user_config()} and exit")
    setup.add_argument("--show-config", action="store_true", help="print the effective settings and exit")
    setup.add_argument("--install-ocr", action="store_true",
                       help=f"download OCR data for --lang into {ocr.user_tessdata()} and exit")
    p.add_argument("-q", "--quiet", action="store_true")
    args = p.parse_args(argv)

    # Windows consoles default to a legacy code page that can't print Persian.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.init_config:
        dest = args.config or config.user_config()
        if dest.exists():
            print(f"md-maker: {dest} already exists", file=sys.stderr)
            return 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(config.template(), encoding="utf-8")
        print(f"settings written to {dest}")
        return 0
    try:
        settings = config.load(args.config, _overrides(args))
    except config.ConfigError as e:
        print(f"md-maker: {e}", file=sys.stderr)
        return 2
    if args.show_config:
        files = config.sources(args.config)
        print(f"# user file: {config.user_config()}{'' if config.user_config().exists() else ' (missing)'}")
        print(f"# read: {', '.join(map(str, files)) or 'defaults only'}\n")
        print(_toml(config.as_dict(settings)))
        return 0
    if args.install_ocr:
        print(f"OCR data ready in {ocr.install(settings.ocr.lang.split('+'))}")
        return 0
    if not args.inputs:
        p.error("give at least one file or folder")

    files = collect(args.inputs)
    if not files:
        print("md-maker: no supported files found", file=sys.stderr)
        return 1
    if args.plan:
        for src, _ in files:
            if src.suffix.lower() == ".pdf":
                _print_plan(src, settings)
            else:
                print(f"{src}  (converted locally with pandoc)")
        return 0

    has_pdf = any(src.suffix.lower() == ".pdf" for src, _ in files)
    pipeline = _make_pipeline(settings, args.quiet) if has_pdf else None
    stems = Counter(target(src, rel, args.output, False, False) for src, rel in files)
    failed = 0
    for src, rel in files:
        try:
            md, report = convert(src, settings, pipeline, args.media)
        except Exception as e:
            failed += 1
            print(f"md-maker: {src}: {e}", file=sys.stderr)
            continue
        if args.stdout:
            sys.stdout.write(md)
            dest = src.with_suffix(".md")  # only names the report
        else:
            clash = stems[target(src, rel, args.output, False, False)] > 1
            dest = target(src, rel, args.output, len(files) == 1, clash)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(md, encoding="utf-8")
            if not args.quiet:
                print(f"{src} -> {dest}  ({_size(src.stat().st_size)} -> {_size(len(md.encode()))})")
        if args.report and report:
            rpath = dest.with_suffix(".report.json")
            rpath.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            if not args.quiet:
                print(f"report: {rpath}", file=sys.stderr)
    if pipeline and pipeline.usage and not args.quiet:
        print("AI usage by stage and model:", *pipeline.usage_lines(), sep="\n", file=sys.stderr)
    if pipeline and pipeline.budget.spent and not args.quiet:
        limit = f" of ${settings.ai.budget_usd:.2f} budget" if settings.ai.budget_usd else ""
        print(f"AI cost: ${pipeline.budget.spent:.3f}{limit}", file=sys.stderr)
    return 1 if failed else 0
