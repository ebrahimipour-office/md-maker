"""Decide, page by page, how much help the local conversion needs.

Routes, cheapest first:
  local      the local draft is good enough
  polish     text-only cleanup of the draft (Persian half-spaces, headings)
  repair     page image + draft: tables, mixed scripts, columns, figures
  transcribe page image only: scans and unusable text layers
"""

import re
from dataclasses import dataclass, field

import pymupdf

from . import normalize as nz
from .pdf import OCR_MIN_CHARS

ROUTES = ("local", "polish", "repair", "transcribe")

# U+FFFD, private-use glyphs (unmapped symbol fonts) and "(cid:12)" escapes
_GARBAGE_RE = re.compile(r"[�-]|\(cid:\d+\)")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_ARABIC_WORD_RE = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]{2,}")


@dataclass
class PageReport:
    page: int  # 0-based
    chars: int
    rtl: float
    scanned: bool
    garbage: float
    tables: int
    figures: int
    mixed_lines: int
    columns: int
    reversed: bool
    route: str = "local"
    reasons: list[str] = field(default_factory=list)


def _columns(blocks, width: float) -> int:
    """2 when two wide-ish text blocks sit side by side, else 1."""
    boxes = [b["bbox"] for b in blocks if b.get("type") == 0 and b["bbox"][2] - b["bbox"][0] > 0.2 * width]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            side_by_side = a[2] <= b[0] or b[2] <= a[0]
            overlap = min(a[3], b[3]) - max(a[1], b[1])
            if side_by_side and overlap > 0.5 * min(a[3] - a[1], b[3] - b[1]) and overlap > 30:
                return 2
    return 1


def _figures(page) -> int:
    """Images big enough to be figures (not icons, not a full-page scan)."""
    area = page.rect.width * page.rect.height
    count = 0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        share = (x1 - x0) * (y1 - y0) / area
        if 0.03 < share < 0.8:
            count += 1
    return count


def analyze_page(page) -> PageReport:
    text = page.get_text("text")
    stripped = text.strip()
    blocks = page.get_text("dict", flags=pymupdf.TEXT_MEDIABOX_CLIP)["blocks"]
    try:
        tables = len(page.find_tables().tables)
    except Exception:
        tables = 0
    lines = [l for l in stripped.splitlines() if l.strip()]
    mixed = sum(bool(_LATIN_WORD_RE.search(l)) and bool(_ARABIC_WORD_RE.search(l)) for l in lines)
    return PageReport(
        page=page.number,
        chars=len(stripped),
        rtl=round(nz.rtl_ratio(text), 2),
        scanned=len(stripped) < OCR_MIN_CHARS and bool(page.get_images()),
        garbage=round(len(_GARBAGE_RE.findall(text)) / max(len(stripped), 1), 3),
        tables=tables,
        figures=_figures(page),
        mixed_lines=mixed,
        columns=_columns(blocks, page.rect.width),
        reversed=nz.looks_reversed(nz.clean_pdf_span(text)),
    )


def route(r: PageReport, settings) -> PageReport:
    """Fill r.route and r.reasons from the report and settings."""
    rt = settings.ai.routing
    transcribe, repair, polish = [], [], []
    if r.scanned:
        transcribe.append("scanned")
    if r.garbage > rt.garbage_ratio:
        transcribe.append(f"broken text layer ({r.garbage:.0%})")
    if r.tables:
        repair.append(f"{r.tables} table(s)")
    if r.mixed_lines >= rt.mixed_script_lines:
        repair.append(f"{r.mixed_lines} mixed Persian/Latin lines")
    if r.columns > 1:
        repair.append("multi-column")
    if r.reversed:
        repair.append("reversed text")
    if r.figures and rt.figures and settings.output.figure_notes:
        repair.append(f"{r.figures} figure(s)")
    if r.rtl > 0.5 and rt.polish_rtl:
        polish.append("Persian/Arabic text")

    if not r.chars and not r.scanned:
        r.route, r.reasons = "local", ["blank page"]
    elif transcribe:
        r.route, r.reasons = "transcribe", transcribe
    elif repair:
        r.route, r.reasons = "repair", repair
    elif settings.ai.mode == "max":
        r.route, r.reasons = "repair", ["mode = max"]
    elif polish:
        r.route, r.reasons = "polish", polish
    else:
        r.route, r.reasons = "local", ["clean text"]
    return r


def triage(doc, settings) -> list[PageReport]:
    return [route(analyze_page(page), settings) for page in doc]
