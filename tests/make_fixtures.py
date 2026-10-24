"""Generate Persian test documents (DOCX + PDF) under tests/fixtures/.

Run: uv run python tests/make_fixtures.py
"""

from pathlib import Path

import docx
import pymupdf
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

FIXTURES = Path(__file__).parent / "fixtures"
FONT = next(
    (
        f
        for f in [
            "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
            r"C:\Windows\Fonts\tahoma.ttf",  # ships with Windows, has Persian glyphs
        ]
        if Path(f).exists()
    ),
    None,
)
if FONT is None:
    raise SystemExit("no Persian-capable font found; install fonts-noto (Linux)")

TITLE = "گزارش ماهانه پروژه"
PARAGRAPHS = [
    "این یک متن آزمایشی به زبان فارسی است که برای بررسی تبدیل فایل‌ها نوشته شده است و باید به اندازه کافی بلند باشد که در فایل PDF به دو خط شکسته شود تا اتصال خطوط را هم بسنجیم.",
    "در این گزارش، نسخه 2.1 از نرم‌افزار PayStar بررسی می‌شود و تاریخ آن ۱۳۹۹/۰۸/۰۲ است.",
]
SUBTITLE = "جدول هزینه‌ها"
TABLE = [["ردیف", "شرح", "مبلغ (ریال)"], ["۱", "سرور", "۵۰۰٬۰۰۰"], ["۲", "پشتیبانی", "۲۵۰٬۰۰۰"]]
BULLETS = ["مورد اول فهرست", "مورد دوم با کلمه English"]


def _rtl(paragraph):
    """Mark a python-docx paragraph (and its runs) as right-to-left."""
    ppr = paragraph._p.get_or_add_pPr()
    ppr.append(ppr.makeelement(qn("w:bidi"), {}))
    for run in paragraph.runs:
        rpr = run._r.get_or_add_rPr()
        rpr.append(rpr.makeelement(qn("w:rtl"), {}))
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def make_docx(path: Path):
    d = docx.Document()
    _rtl(d.add_heading(TITLE, level=1))
    for text in PARAGRAPHS:
        _rtl(d.add_paragraph(text))
    _rtl(d.add_heading(SUBTITLE, level=2))
    table = d.add_table(rows=len(TABLE), cols=len(TABLE[0]))
    table.style = "Table Grid"
    for r, row in enumerate(TABLE):
        for c, cell in enumerate(row):
            table.cell(r, c).text = cell
            _rtl(table.cell(r, c).paragraphs[0])
    for text in BULLETS:
        _rtl(d.add_paragraph(text, style="List Bullet"))
    d.save(path)


def make_pdf(path: Path):
    """Lay the page out like a Word export: right-aligned, RTL ruled table."""
    css = (
        f"@font-face {{font-family: naskh; src: url({Path(FONT).name});}}"
        "* {font-family: naskh; text-align: right;}"
    )
    archive = pymupdf.Archive(str(Path(FONT).parent))
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    left, right, y = 50, 545, 50

    def box(html, height, x0=left, x1=right, size=12):
        page.insert_htmlbox(
            (x0, y, x1, y + height),
            f'<div dir="rtl" style="font-size:{size}px">{html}</div>',
            css=css,
            archive=archive,
        )

    box(TITLE, 40, size=24)
    y += 50
    for text in PARAGRAPHS:
        box(text, 45)
        y += 45
    box(SUBTITLE, 30, size=18)
    y += 35

    # Columns run right-to-left, so the first logical column is rightmost.
    widths = [60, 200, 120]
    row_h = 24
    for row in TABLE:
        x1 = right
        for cell, w in zip(row, widths):
            page.draw_rect((x1 - w, y, x1, y + row_h), color=(0, 0, 0), width=0.7)
            box(cell, row_h - 4, x0=x1 - w + 4, x1=x1 - 4)
            x1 -= w
        y += row_h
    y += 15
    for text in BULLETS:
        box(f"• {text}", 24)
        y += 24
    doc.save(path)


def make_multipage_pdf(path: Path, pages: int = 4):
    """Persian pages with a running header and page numbers to strip."""
    css = f"@font-face {{font-family: naskh; src: url({Path(FONT).name});}} * {{font-family: naskh;}}"
    archive = pymupdf.Archive(str(Path(FONT).parent))
    doc = pymupdf.open()
    for n in range(1, pages + 1):
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox((50, 20, 545, 40), '<div dir="rtl">شرکت نمونه - گزارش داخلی</div>',
                            css=css, archive=archive)
        page.insert_htmlbox((50, 100, 545, 140), f'<div dir="rtl">متن اصلی صفحه {n} در اینجا است.</div>',
                            css=css, archive=archive)
        page.insert_text((290, 810), str(n), fontsize=10)
    doc.save(path)


def make_english_pdf(path: Path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_htmlbox(
        (50, 50, 545, 400),
        "<h1>Quarterly Report</h1><p>This document is written in English and should go "
        "through the layout engine.</p><ul><li>First point</li><li>Second point</li></ul>",
    )
    doc.save(path)


def make_scanned_pdf(src: Path, path: Path):
    """Image-only copy of src, like a scanner would produce."""
    doc = pymupdf.open()
    for page in pymupdf.open(src):
        pix = page.get_pixmap(dpi=200)
        new = doc.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    doc.save(path)


if __name__ == "__main__":
    FIXTURES.mkdir(exist_ok=True)
    make_docx(FIXTURES / "persian.docx")
    make_pdf(FIXTURES / "persian.pdf")
    make_multipage_pdf(FIXTURES / "persian_multipage.pdf")
    make_english_pdf(FIXTURES / "english.pdf")
    make_scanned_pdf(FIXTURES / "persian.pdf", FIXTURES / "persian_scanned.pdf")
    print("fixtures written to", FIXTURES)
