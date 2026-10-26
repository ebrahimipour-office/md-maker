"""Local sanity checks of AI output, so weak pages get a stronger model.

When the page has a real text layer, the local draft's characters are
exact even if its order is not, so its words are a good checklist.
"""

import re
from collections import Counter

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PRESENTATION_FORMS_RE = re.compile(r"[ﭐ-﷿ﹰ-﻿]")
_PREAMBLE_RE = re.compile(r"^(here is|here's|sure|certainly|below is|the following|این صفحه|در ادامه)", re.I)
_FIGURE_LINE_RE = re.compile(r"^> \[.*\]$", re.M)
_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", re.S)


def clean_output(md: str) -> str:
    """Undo wrapping a model sometimes adds despite instructions."""
    md = md.strip()
    if m := _FENCE_RE.match(md):
        md = m.group(1).strip()
    return md


def _words(text: str) -> Counter:
    # \w excludes ZWNJ, so نرم‌افزار and "نرم افزار" give the same words
    return Counter(re.findall(r"\w+", text.translate(_DIGITS).lower()))


def _overlap(a: Counter, b: Counter) -> float:
    total = sum(a.values())
    return sum((a & b).values()) / total if total else 1.0


def _table_problems(md: str) -> int:
    bad = 0
    table: list[str] = []
    for line in md.splitlines() + [""]:
        if line.startswith("|"):
            table.append(line)
            continue
        if table:
            widths = {len(re.split(r"(?<!\\)\|", row.strip().strip("|"))) for row in table}
            bad += len(widths) > 1
            table = []
    return bad


def score(md: str, draft: str, trusted_draft: bool) -> tuple[float, list[str]]:
    """(0..1, reasons). trusted_draft: the draft comes from a real text layer."""
    reasons = []
    s = 1.0
    if not md.strip():
        return 0.0, ["empty output"]
    if trusted_draft:
        want, got = _words(draft), _words(_FIGURE_LINE_RE.sub("", md))
        if sum(want.values()) >= 5:
            recall = _overlap(want, got)
            precision = _overlap(got, want)
            numbers = Counter({w: n for w, n in want.items() if w.isdigit()})
            num_recall = _overlap(numbers, got)
            s = 0.5 * recall + 0.2 * precision + 0.3 * num_recall
            if recall < 0.9:
                reasons.append(f"{recall:.0%} of the text-layer words kept")
            if precision < 0.8:
                reasons.append(f"{1 - precision:.0%} of the words are not in the text layer")
            if num_recall < 1:
                reasons.append("numbers missing")
    if n := _table_problems(md):
        s -= 0.2 * n
        reasons.append(f"{n} table(s) with uneven rows")
    if _PRESENTATION_FORMS_RE.search(md) or "�" in md:
        s -= 0.2
        reasons.append("broken characters")
    if _PREAMBLE_RE.match(md.lstrip()):
        s -= 0.2
        reasons.append("commentary in output")
    return max(0.0, round(s, 3)), reasons
