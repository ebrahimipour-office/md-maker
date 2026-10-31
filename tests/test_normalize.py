import unicodedata

from md_maker import normalize as nz

ZWNJ = nz.ZWNJ


def test_presentation_forms_become_plain_letters():
    assert nz.clean_pdf_span("ﮔﺰﺍﺭﺵ\xa0ﻣﺎﻫﺎﻧﻪ") == "گزارش ماهانه"


def test_zwnj_restored_from_glyph_shapes():
    # فایلها written with final ل + initial ه: the writer had typed a ZWNJ.
    assert nz.clean_pdf_span("ﻓﺎﯾﻞﻫﺎ") == f"فایل{ZWNJ}ها"


def test_no_zwnj_after_non_joining_letter():
    # ر never joins forward, so the break in "بررسی" is natural.
    assert ZWNJ not in nz.clean_pdf_span("ﺑﺮﺭﺳﯽ")


def test_unshaped_text_left_alone():
    isolated = "".join(unicodedata.lookup(f"ARABIC LETTER {n} ISOLATED FORM") for n in ["BEH", "SEEN"])
    assert ZWNJ not in nz.restore_zwnj_from_forms(isolated)


def test_arabic_variants_and_digits():
    assert nz.normalize_chars("علي كتاب ٣") == "علی کتاب ۳"
    assert nz.normalize_chars("‏سلام‎") == "سلام"
    assert nz.normalize_chars("کـــتاب") == "کتاب"


def test_fix_spacing():
    assert nz.fix_spacing("می شود") == f"می{ZWNJ}شود"
    assert nz.fix_spacing("نمی خواهم") == f"نمی{ZWNJ}خواهم"
    assert nz.fix_spacing("کتاب ها و بزرگ ترین") == f"کتاب{ZWNJ}ها و بزرگ{ZWNJ}ترین"
    assert nz.fix_spacing("رفته اند") == f"رفته{ZWNJ}اند"
    # "است" stays a separate word
    assert nz.fix_spacing("شده است") == "شده است"


def test_mirrored_brackets_only_on_rtl_lines():
    assert nz.fix_mirrored_brackets("مبلغ )ریال(") == "مبلغ (ریال)"
    assert nz.fix_mirrored_brackets("f)x( is odd") == "f)x( is odd"


def test_reversed_line_detection_and_repair():
    logical = "این متن از PDF به شکل 2.1 (نسخه) در آن است که را با"
    # How a visual-order PDF stores it: Persian reversed, Latin/number runs
    # left-to-right, brackets as drawn.
    visual = "اب ار هک تسا نآ رد (هخسن) 2.1 لکش هب PDF زا نتم نیا"
    assert nz.looks_reversed(visual)
    assert not nz.looks_reversed(logical)
    assert nz.unreverse_line(visual) == logical


def test_rtl_ratio():
    assert nz.is_rtl("سلام دنیا hello")
    assert not nz.is_rtl("hello world سلام")


def test_fix_spacing_leaves_non_persian_alone():
    line = "جمعهها می روند: [پیوند](https://a.com/x?a=1) نسخه 2.1 و ۵۰۰٬۰۰۰ ریال ، خوب ؟"
    assert nz.fix_spacing(line) == "جمعه‌ها می‌روند: [پیوند](https://a.com/x?a=1) نسخه 2.1 و ۵۰۰٬۰۰۰ ریال، خوب؟"
