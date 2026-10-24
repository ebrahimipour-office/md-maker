"""Persian text cleanup.

PDFs store Persian badly: letters as joined "presentation form" glyphs,
half-spaces (ZWNJ) dropped or turned into spaces, brackets mirrored and, in
some files, whole lines in visual (reversed) order. These helpers undo that.
"""

import re
import unicodedata

ZWNJ = "‌"

_ARABIC_LETTER = r"؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿"
_ARABIC_RE = re.compile(f"[{_ARABIC_LETTER}]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Letters that never join to the following letter, so a break after them is
# natural and does not imply a missing ZWNJ.
_NON_LEFT_JOINING = set("اآأإٱدذرزژوؤةۀء")

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ـ": None,  # kashida (tatweel)
        **{chr(0x0660 + i): chr(0x06F0 + i) for i in range(10)},  # Arabic -> Persian digits
        # bidi control characters: invisible, but cost tokens
        **{c: None for c in "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"},
    }
)

# Bullet glyphs seen in PDFs, including Symbol/Wingdings private-use code points.
BULLETS = "•●▪■◦○◆►➢✓"

_PREFIX_RE = re.compile(rf"(?<![{_ARABIC_LETTER}{ZWNJ}])(ن?می) +(?=[{_ARABIC_LETTER}])")
_SUFFIX_RE = re.compile(
    rf"(?<=[{_ARABIC_LETTER}]) +(ها|های|هایی|هایم|هایت|هایش|هایمان|هایتان|هایشان|ترین|تری|تر)"
    rf"(?![{_ARABIC_LETTER}{ZWNJ}])"
)
_VERB_SUFFIX_RE = re.compile(rf"(?<=ه) +(ام|ای|ایم|اید|اند)(?![{_ARABIC_LETTER}{ZWNJ}])")
_MIRRORED_RE = re.compile(r"\)([^()\n]*)\(")

_COMMON = ["از", "به", "در", "که", "این", "را", "با", "است", "برای", "آن", "یک", "تا", "شده", "می"]
_COMMON_REVERSED = {w[::-1] for w in _COMMON}
_LTR_RUN_RE = re.compile(r"[A-Za-z0-9۰-۹](?:[A-Za-z0-9۰-۹.,:/_%@+\-]*[A-Za-z0-9۰-۹])?")
MIRROR = str.maketrans("()[]{}<>", ")(][}{><")


def rtl_ratio(text: str) -> float:
    """Share of Arabic-script letters among Arabic + Latin letters."""
    arabic = len(_ARABIC_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    return arabic / (arabic + latin) if arabic + latin else 0.0


def is_rtl(text: str) -> bool:
    return rtl_ratio(text) > 0.5


def _form(ch: str) -> tuple[str, str] | None:
    """(form, left-side base letter) of a presentation-form glyph, else None."""
    decomp = unicodedata.decomposition(ch)
    if not decomp.startswith("<"):
        return None
    tag, *codes = decomp.split()
    if tag not in ("<initial>", "<medial>", "<final>", "<isolated>"):
        return None
    return tag, chr(int(codes[-1], 16))


def restore_zwnj_from_forms(text: str) -> str:
    """Re-insert ZWNJ where glyph shapes show a break inside a word.

    A final/isolated form of a letter that normally joins forward, directly
    followed by an initial/isolated form, means the writer typed a ZWNJ
    (e.g. فایل‌ها) that the PDF dropped. Must run before NFKC.
    """
    forms = [_form(ch) for ch in text]
    shaped = [f for f in forms if f]
    # Unshaped text (every glyph isolated) carries no signal.
    if not shaped or sum(f[0] == "<isolated>" for f in shaped) > 0.6 * len(shaped):
        return text
    out = []
    for i, ch in enumerate(text):
        out.append(ch)
        a, b = forms[i], forms[i + 1] if i + 1 < len(text) else None
        if (
            a
            and b
            and a[0] in ("<final>", "<isolated>")
            and b[0] in ("<initial>", "<isolated>")
            and a[1] not in _NON_LEFT_JOINING
            and b[1] != "ء"
        ):
            out.append(ZWNJ)
    return "".join(out)


def normalize_chars(text: str) -> str:
    """Unify Arabic/Persian character variants and drop invisible controls."""
    return text.translate(_CHAR_MAP)


def fix_spacing(text: str) -> str:
    """Turn spaces that replaced a ZWNJ back into ZWNJ (می‌شود, کتاب‌ها, شده‌اند)."""
    text = _PREFIX_RE.sub(rf"\1{ZWNJ}", text)
    text = _SUFFIX_RE.sub(rf"{ZWNJ}\1", text)
    return _VERB_SUFFIX_RE.sub(rf"{ZWNJ}\1", text)


def fix_mirrored_brackets(line: str) -> str:
    """`)ریال(` -> `(ریال)` on right-to-left lines."""
    return _MIRRORED_RE.sub(r"(\1)", line) if is_rtl(line) else line


def clean_pdf_span(text: str) -> str:
    """Full cleanup for one raw text span extracted from a PDF."""
    text = restore_zwnj_from_forms(text)
    text = unicodedata.normalize("NFKC", text)
    return normalize_chars(text)


def _common_counts(text: str) -> tuple[int, int]:
    words = re.findall(f"[{_ARABIC_LETTER}]+", text)
    return sum(w in _COMMON for w in words), sum(w in _COMMON_REVERSED for w in words)


def looks_reversed(text: str) -> bool:
    """True when common Persian words mostly appear spelled backwards."""
    normal, reversed_ = _common_counts(text)
    return reversed_ >= 3 and reversed_ > 2 * normal


def words_look_reversed(words: list[str]) -> bool:
    """Per-line variant for OCR output: any reversed evidence that wins."""
    normal, reversed_ = _common_counts(" ".join(words))
    return reversed_ > normal


def unreverse_line(line: str) -> str:
    """Convert a visual-order RTL line to logical order, keeping LTR runs intact."""
    flipped = line[::-1].translate(MIRROR)
    return _LTR_RUN_RE.sub(lambda m: m.group(0)[::-1], flipped)
