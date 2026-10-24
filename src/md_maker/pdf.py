"""PDF -> Markdown.

Two engines:
- "rtl": our own extractor for Persian/Arabic documents. Generic tools order
  line fragments left-to-right, which scrambles mixed Persian/English lines,
  and read table cells character by character in visual order.
- "layout": pymupdf4llm, best for left-to-right documents (columns, tables).
"""

import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from . import normalize as nz

OCR_MIN_CHARS = 20  # a page with less text than this is treated as scanned


@dataclass
class Block:
    page: int
    bbox: tuple
    lines: list[str]
    size: float
    bold: bool
    heading: int = 0


@dataclass
class Table:
    page: int
    bbox: tuple
    rows: list[list[str]] = field(default_factory=list)


def has_tesseract() -> bool:
    return shutil.which("tesseract") is not None


def _warn(msg: str):
    print(f"md-maker: {msg}", file=sys.stderr)


def _center_in(bbox, rect) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def _fragment_text(line: dict) -> str:
    return "".join(nz.clean_pdf_span(s["text"]) for s in line["spans"])


def _visual_lines(lines: list[dict]) -> list[str]:
    """Merge pymupdf line fragments that share a baseline, ordered by direction.

    pymupdf splits a visual line wherever the script changes; for RTL text
    the fragments must be read right to left.
    """
    groups: list[list[dict]] = []
    for line in sorted(lines, key=lambda l: l["bbox"][1]):
        y0, y1 = line["bbox"][1], line["bbox"][3]
        mid = (y0 + y1) / 2
        for g in groups:
            gy0, gy1 = g[0]["bbox"][1], g[0]["bbox"][3]
            if gy0 <= mid <= gy1:
                g.append(line)
                break
        else:
            groups.append([line])
    out = []
    for g in groups:
        texts = [(l["bbox"][0], _fragment_text(l)) for l in g]
        rtl = nz.is_rtl("".join(t for _, t in texts))
        texts.sort(key=lambda t: t[0], reverse=rtl)
        text = re.sub(r"\s+", " ", " ".join(t for _, t in texts)).strip()
        if text:
            out.append(text)
    return out


def _ocr_textpage(page, lang: str, dpi: int):
    try:
        return page.get_textpage_ocr(language=lang, dpi=dpi, full=True)
    except Exception as e:  # missing language data, bad tessdata path, ...
        _warn(f"OCR failed on page {page.number + 1}: {e}")
        return None


def _page_dict(page, ocr: str, lang: str):
    textpage = None
    scanned = len(page.get_text("text").strip()) < OCR_MIN_CHARS
    if ocr == "always" or (ocr == "auto" and scanned):
        if has_tesseract():
            textpage = _ocr_textpage(page, lang, 300)
        elif scanned and page.get_images():
            _warn(
                f"page {page.number + 1} looks scanned but tesseract is not installed "
                "(sudo apt install tesseract-ocr tesseract-ocr-fas)"
            )
    flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
    raw = page.get_text("rawdict", flags=flags, textpage=textpage)
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                s["text"] = "".join(c["c"] for c in s["chars"])
    return raw


def _filter_chars(lines: list[dict], rect, inside: bool) -> list[dict]:
    """Keep only the characters whose centre is inside (or outside) rect.

    A table row is often a single text line spanning every cell, so cells
    must be filled, and tables cut out of the text, character by character.
    """
    out = []
    for l in lines:
        spans = []
        for s in l["spans"]:
            chars = [c for c in s["chars"] if _center_in(c["bbox"], rect) == inside]
            if chars:
                spans.append({**s, "chars": chars, "text": "".join(c["c"] for c in chars)})
        if spans:
            boxes = [c["bbox"] for s in spans for c in s["chars"]]
            bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes))
            out.append({**l, "spans": spans, "bbox": bbox})
    return out


def _extract_tables(page, words_dict, page_no) -> list[Table]:
    try:
        found = page.find_tables().tables
    except Exception:
        return []
    lines = [l for b in words_dict["blocks"] for l in b.get("lines", [])]
    tables = []
    for t in found:
        table = Table(page_no, tuple(t.bbox))
        for row in t.rows:
            cells = []
            for cell in row.cells:
                if cell is None:  # merged cell
                    cells.append("")
                    continue
                cells.append(" ".join(_visual_lines(_filter_chars(lines, cell, True))))
            table.rows.append(cells)
        if table.rows and nz.is_rtl(" ".join(table.rows[0])):
            table.rows = [r[::-1] for r in table.rows]
        tables.append(table)
    return tables


def _extract_blocks(words_dict, tables, page_no) -> list[Block]:
    blocks = []
    for b in words_dict["blocks"]:
        if b.get("type") != 0:
            continue
        lines = b["lines"]
        for t in tables:
            lines = _filter_chars(lines, t.bbox, False)
        spans = [s for l in lines for s in l["spans"] if s["text"].strip()]
        if not spans:
            continue
        sizes = Counter()
        bold_chars = 0
        for s in spans:
            sizes[round(s["size"] * 2) / 2] += len(s["text"])
            if s["flags"] & pymupdf.TEXT_FONT_BOLD or "bold" in s["font"].lower():
                bold_chars += len(s["text"])
        total = sum(sizes.values())
        text_lines = _visual_lines(lines)
        if text_lines:
            blocks.append(
                Block(page_no, tuple(b["bbox"]), text_lines, sizes.most_common(1)[0][0],
                      bold_chars > 0.8 * total)
            )
    return blocks


_PAGE_NUMBER_RE = re.compile(r"^[-–\s]*(صفحه|page)?\s*[0-9۰-۹]+(\s*(از|of|/)\s*[0-9۰-۹]+)?[-–\s]*$", re.I)


def _drop_running_heads(blocks: list[Block], n_pages: int) -> list[Block]:
    """Remove page numbers and headers/footers repeated on many pages."""
    edge = Counter()
    by_page: dict[int, list[Block]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    for page_blocks in by_page.values():
        for b in {id(x): x for x in (page_blocks[0], page_blocks[-1])}.values():
            edge[_key(b)] += 1
    threshold = max(3, n_pages // 2)
    return [
        b for b in blocks
        if not _PAGE_NUMBER_RE.match(" ".join(b.lines)) and edge[_key(b)] < threshold
    ]


def _key(b: Block) -> str:
    return re.sub(r"[0-9۰-۹]+", "#", " ".join(b.lines))


def _assign_headings(blocks: list[Block]):
    body = Counter()
    for b in blocks:
        body[b.size] += sum(len(l) for l in b.lines)
    if not body:
        return
    body_size = body.most_common(1)[0][0]
    heading_sizes = sorted({b.size for b in blocks if b.size >= body_size * 1.2}, reverse=True)
    level = {s: min(i + 1, 4) for i, s in enumerate(heading_sizes)}
    for b in blocks:
        if b.size in level and len(" ".join(b.lines)) < 200:
            b.heading = level[b.size]


def _join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith("-") and line[:1].islower():
            out = out[:-1] + line  # de-hyphenate English
        else:
            out += " " + line
    return out


def _render_block(b: Block, spacing: bool) -> str:
    lines = [nz.fix_mirrored_brackets(l) for l in b.lines]
    if spacing:
        lines = [nz.fix_spacing(l) for l in lines]
    if b.heading:
        return "#" * b.heading + " " + _join_lines(lines)
    items: list[list[str]] = []
    plain: list[str] = []
    for line in lines:
        bullet = line[0] in nz.BULLETS or line[-1] in nz.BULLETS
        if bullet:
            items.append([line.strip(nz.BULLETS + " ")])
        elif items:
            items[-1].append(line)
        else:
            plain.append(line)
    parts = []
    if plain:
        text = _join_lines(plain)
        parts.append(f"**{text}**" if b.bold and len(text) < 120 else text)
    parts.extend("- " + _join_lines(i) for i in items)
    return "\n".join(parts)


def _render_table(t: Table, spacing: bool) -> str:
    width = max(len(r) for r in t.rows)

    def cell(text):
        text = nz.fix_mirrored_brackets(text)
        if spacing:
            text = nz.fix_spacing(text)
        return text.replace("|", r"\|")

    rows = [[cell(c) for c in r] + [""] * (width - len(r)) for r in t.rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _rtl_markdown(doc, ocr: str, lang: str, spacing: bool, page_markers: bool) -> str:
    blocks: list[Block] = []
    tables: list[Table] = []
    for page in doc:
        words_dict = _page_dict(page, ocr, lang)
        page_tables = _extract_tables(page, words_dict, page.number)
        tables += page_tables
        blocks += _extract_blocks(words_dict, page_tables, page.number)

    if nz.looks_reversed(" ".join(l for b in blocks for l in b.lines)):
        for b in blocks:
            b.lines = [nz.unreverse_line(l) if nz.is_rtl(l) else l for l in b.lines]
        for t in tables:
            t.rows = [[nz.unreverse_line(c) for c in r] for r in t.rows]

    blocks = _drop_running_heads(blocks, len(doc))
    _assign_headings(blocks)

    # Keep pymupdf's reading order; slot each table in before the first
    # block that starts below it on the same page.
    out: list[str] = []
    pending = sorted(tables, key=lambda t: (t.page, t.bbox[1]))
    page = -1
    for b in blocks:
        while pending and (pending[0].page, pending[0].bbox[1]) < (b.page, b.bbox[1]):
            out.append(_render_table(pending.pop(0), spacing))
        if page_markers and b.page != page:
            out.append(f"<!-- page {b.page + 1} -->")
        page = b.page
        out.append(_render_block(b, spacing))
    out += [_render_table(t, spacing) for t in pending]
    return "\n\n".join(out) + "\n"


def _layout_markdown(path, ocr: str, lang: str, page_markers: bool) -> str:
    import pymupdf4llm

    use_ocr = ocr != "never" and has_tesseract()
    return pymupdf4llm.to_markdown(
        str(path),
        use_ocr=use_ocr,
        force_ocr=use_ocr and ocr == "always",
        ocr_language=lang,
        page_separators=page_markers,
        show_progress=False,
    )


def detect_rtl(doc, sample_pages: int = 10) -> bool:
    text = "".join(doc[i].get_text("text") for i in range(min(len(doc), sample_pages)))
    return nz.rtl_ratio(text) > 0.3


def pdf_to_markdown(
    path,
    *,
    engine: str = "auto",
    ocr: str = "auto",
    lang: str = "fas+eng",
    spacing: bool = True,
    page_markers: bool = False,
) -> str:
    doc = pymupdf.open(path)
    if doc.needs_pass:
        raise ValueError("PDF is password-protected")
    if engine == "auto":
        # Scanned docs have no text to detect from; OCR them with our engine
        # when the requested language is Persian/Arabic.
        has_text = any(len(p.get_text("text").strip()) >= OCR_MIN_CHARS for p in doc)
        engine = "rtl" if (detect_rtl(doc) if has_text else re.search(r"fas|ara|urd", lang)) else "layout"
    if engine == "rtl":
        md = _rtl_markdown(doc, ocr, lang, spacing, page_markers)
    else:
        md = nz.normalize_chars(_layout_markdown(path, ocr, lang, page_markers))
    if not md.strip():
        hint = "" if has_tesseract() else "; if it is scanned, install tesseract-ocr tesseract-ocr-fas"
        raise ValueError(f"no text extracted{hint}")
    return md
