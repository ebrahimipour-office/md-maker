import subprocess
import sys
from pathlib import Path

import pytest

from md_maker import main, office_to_markdown, pdf_to_markdown
from md_maker.pdf import has_ocr

FIXTURES = Path(__file__).parent / "fixtures"
ZWNJ = "‌"
TABLE = "| ردیف | شرح | مبلغ (ریال) |\n|---|---|---|\n| ۱ | سرور | ۵۰۰٬۰۰۰ |\n| ۲ | پشتیبانی | ۲۵۰٬۰۰۰ |"


@pytest.fixture(scope="session", autouse=True)
def fixtures():
    subprocess.run([sys.executable, str(Path(__file__).parent / "make_fixtures.py")], check=True)


def test_docx():
    md = office_to_markdown(FIXTURES / "persian.docx")
    assert md.startswith("# گزارش ماهانه پروژه")
    assert f"نرم{ZWNJ}افزار PayStar بررسی می{ZWNJ}شود" in md
    assert TABLE in md
    assert "<span" not in md and "- مورد دوم با کلمه English" in md


def test_persian_pdf():
    md = pdf_to_markdown(FIXTURES / "persian.pdf")
    assert md.startswith("# گزارش ماهانه پروژه")
    assert "## جدول هزینه" in md
    # mixed-direction line kept in reading order, half-spaces restored
    assert f"در این گزارش، نسخه 2.1 از نرم افزار PayStar بررسی می{ZWNJ}شود و تاریخ آن ۱۳۹۹/۰۸/۰۲ است." in md
    # paragraph wrapped over two PDF lines is joined
    assert "در فایل PDF به دو خط شکسته شود تا اتصال خطوط را هم بسنجیم." in md
    assert f"فایل{ZWNJ}ها" in md
    assert TABLE in md
    assert "- مورد اول فهرست" in md and "- مورد دوم با کلمه English" in md
    assert "ﺍ" not in md  # no presentation forms left


def test_running_headers_and_page_numbers_dropped():
    md = pdf_to_markdown(FIXTURES / "persian_multipage.pdf")
    assert "گزارش داخلی" not in md
    assert md.split() == "متن اصلی صفحه 1 در اینجا است. متن اصلی صفحه 2 در اینجا است. متن اصلی صفحه 3 در اینجا است. متن اصلی صفحه 4 در اینجا است.".split()


def test_english_pdf_uses_layout_engine():
    md = pdf_to_markdown(FIXTURES / "english.pdf")
    assert "Quarterly Report" in md and "- First point" in md


@pytest.mark.skipif(not has_ocr(), reason="no OCR data (md-maker --install-ocr)")
def test_scanned_pdf_ocr():
    md = pdf_to_markdown(FIXTURES / "persian_scanned.pdf")
    # OCR is imperfect; check reading order on lines Tesseract gets right
    assert "گزارش ماهانه" in md
    assert "این یک متن آزمایشی به زبان فارسی است" in md
    assert "مورد اول فهرست" in md


@pytest.mark.skipif(has_ocr(), reason="OCR data installed")
def test_scanned_pdf_without_ocr_fails_clearly():
    with pytest.raises(ValueError, match="install-ocr"):
        pdf_to_markdown(FIXTURES / "persian_scanned.pdf")


def test_cli_batch(tmp_path, capsys):
    assert main([str(FIXTURES / "persian.pdf"), str(FIXTURES / "persian.docx"), "-o", str(tmp_path), "-q"]) == 0
    # same stem, different formats: neither output overwrites the other
    assert sorted(p.name for p in tmp_path.iterdir()) == ["persian.docx.md", "persian.pdf.md"]


def test_cli_single_file_output(tmp_path):
    out = tmp_path / "x.md"
    assert main([str(FIXTURES / "english.pdf"), "-o", str(out), "-q"]) == 0
    text = out.read_text()
    assert "# Quarterly Report" in text and " \n" not in text


def test_cli_stdout_has_only_markdown(capsys):
    assert main([str(FIXTURES / "english.pdf"), "--stdout"]) == 0
    assert capsys.readouterr().out.startswith("# Quarterly Report")


def test_cli_rtl_wrap(capsys):
    assert main([str(FIXTURES / "persian.docx"), "--stdout", "--rtl-wrap"]) == 0
    assert capsys.readouterr().out.startswith('<div dir="rtl">')
