"""Stitch per-page Markdown into one document.

Pages converted independently (some by AI, some locally) need a little
glue: tables split by a page break, headers/footers the AI kept, and
heading levels that never start at `#`.
"""

import re
from collections import Counter

from .pdf import join_pages

_HEADING_RE = re.compile(r"^(#{1,6}) ", re.M)


def _is_table(block: str) -> bool:
    return all(line.startswith("|") for line in block.splitlines())


def _cells(row: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def _join_tables(pages: list[str]) -> list[str]:
    """Append a table that opens a page to one that closes the previous page
    when both have the same columns; drop the repeated header row."""
    pages = list(pages)
    prev = None  # index of the last non-empty page
    for i, md in enumerate(pages):
        if not md.strip():
            continue
        if prev is not None:
            head = pages[prev].rstrip().rsplit("\n\n", 1)
            tail = md.lstrip().split("\n\n", 1)
            if _is_table(head[-1]) and _is_table(tail[0]):
                a, b = head[-1].splitlines(), tail[0].splitlines()
                if len(a) >= 2 and len(b) >= 2 and len(_cells(a[0])) == len(_cells(b[0])):
                    # b[1] is its separator row: drop both when b repeats a's
                    # header, otherwise b's first row is data.
                    rows = b[2:] if _cells(a[0]) == _cells(b[0]) else b[:1] + b[2:]
                    head[-1] = "\n".join(a + rows)
                    pages[prev] = "\n\n".join(head)
                    md = tail[1] if len(tail) > 1 else ""
                    pages[i] = md
        if md.strip():
            prev = i
    return pages


def _edge_key(line: str) -> str:
    return re.sub(r"[0-9۰-۹]+", "#", line.strip())


def _drop_running_heads(pages: list[str]) -> list[str]:
    """Remove first/last lines that repeat on at least half the pages.

    Only pages with more than one line count, and a page is never emptied:
    a document of one-line pages has no header to strip. Table rows are
    exempt, because a continued table repeats its header row.
    """
    lines_of = [[l for l in p.splitlines() if l.strip()] for p in pages]
    counts = Counter()
    for lines in lines_of:
        if len(lines) > 1:
            counts.update({_edge_key(l) for l in (lines[0], lines[-1]) if not l.startswith("|")})
    filled = sum(bool(lines) for lines in lines_of)
    repeated = {k for k, n in counts.items() if n >= max(3, filled // 2)}
    if not repeated:
        return pages
    out = []
    for p, lines in zip(pages, lines_of):
        edges = [l for l in (lines[:1] + lines[-1:]) if _edge_key(l) in repeated and not l.startswith("|")]
        if len(lines) <= len(set(edges)):
            out.append(p)
            continue
        rows = p.splitlines()
        while rows and (not rows[0].strip() or (rows[0] in edges)):
            rows.pop(0)
        while rows and (not rows[-1].strip() or (rows[-1] in edges)):
            rows.pop()
        out.append("\n".join(rows))
    return out


def _lift_headings(md: str) -> str:
    """Shift headings up so the top level is `#` (e.g. only ## and ### used)."""
    levels = [len(m.group(1)) for m in _HEADING_RE.finditer(md)]
    if not levels or (shift := min(levels) - 1) <= 0:
        return md
    return _HEADING_RE.sub(lambda m: "#" * (len(m.group(1)) - shift) + " ", md)


def merge(pages: list[str], page_markers: bool = False) -> str:
    pages = [p.strip() for p in pages]
    pages = _drop_running_heads(pages)
    if not page_markers:  # markers keep page boundaries exact
        pages = _join_tables(pages)
    return _lift_headings(join_pages(pages, page_markers))
