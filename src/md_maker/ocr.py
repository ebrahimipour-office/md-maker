"""Locate (or download) Tesseract language data.

MuPDF has Tesseract built in, so OCR only needs the *.traineddata files, not
a Tesseract install. They are looked up, in order, in:
  1. $TESSDATA_PREFIX
  2. tessdata/ next to a frozen md-maker executable (Windows build)
  3. the per-user folder filled by `md-maker --install-ocr`
  4. an installed Tesseract (PATH, or its default Windows folders)
"""

import os
import sys
import urllib.request
from functools import cache
from pathlib import Path

import pymupdf

DATA_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/{lang}.traineddata"
DEFAULT_LANGS = ("fas", "eng")


def user_tessdata() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "md-maker" / "tessdata"


def _candidates():
    yield os.environ.get("TESSDATA_PREFIX")
    if getattr(sys, "frozen", False):
        yield Path(sys.executable).parent / "tessdata"
    yield user_tessdata()
    try:
        yield pymupdf.get_tessdata()
    except Exception:
        pass
    if sys.platform == "win32":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if base := os.environ.get(var):
                yield Path(base) / ("Programs" if var == "LOCALAPPDATA" else "") / "Tesseract-OCR" / "tessdata"


@cache
def find_tessdata() -> str | None:
    """First folder that holds any *.traineddata file, or None."""
    for folder in _candidates():
        if folder and any(Path(folder).glob("*.traineddata")):
            return str(folder)
    return None


def missing_langs(lang: str) -> list[str]:
    """Languages of a tesseract spec like "fas+eng" with no data file."""
    folder = find_tessdata()
    return [l for l in lang.split("+") if not folder or not (Path(folder) / f"{l}.traineddata").exists()]


def install_hint() -> str:
    return "run `md-maker --install-ocr` to download Persian + English OCR data"


def install(langs=DEFAULT_LANGS, dest: Path | None = None) -> Path:
    """Download traineddata files into dest (default: the per-user folder)."""
    dest = dest or user_tessdata()
    dest.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        target = dest / f"{lang}.traineddata"
        if target.exists():
            print(f"{target} already present")
            continue
        print(f"downloading {lang}.traineddata ...")
        tmp = target.with_suffix(".part")
        urllib.request.urlretrieve(DATA_URL.format(lang=lang), tmp)
        tmp.replace(target)
    find_tessdata.cache_clear()
    return dest
