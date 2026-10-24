"""DOCX (and other pandoc-readable documents) -> Markdown."""

import re
from importlib.resources import files
from pathlib import Path

import pypandoc

from . import normalize as nz

# extension -> pandoc input format
FORMATS = {
    ".docx": "docx",
    ".odt": "odt",
    ".rtf": "rtf",
    ".epub": "epub",
    ".html": "html",
    ".htm": "html",
}


def office_to_markdown(path: Path, *, media_dir: Path | None = None) -> str:
    lua = files("md_maker") / "data" / "unwrap_dir.lua"
    args = ["--wrap=none", f"--lua-filter={lua}"]
    if media_dir:
        args.append(f"--extract-media={media_dir}")
    md = pypandoc.convert_file(
        str(path), "gfm", format=FORMATS[path.suffix.lower()], extra_args=args
    )
    # DOCX keeps real ZWNJs, so only unify character variants here.
    return compact_tables(nz.normalize_chars(md))


_ALIGN_ROW_RE = re.compile(r"^\|(\s*:?-+:?\s*\|)+$")


def compact_tables(md: str) -> str:
    """Strip pandoc's column padding from pipe tables; it is pure token cost."""
    out = []
    for line in md.split("\n"):
        if _ALIGN_ROW_RE.match(line):
            line = "|" + "---|" * (line.count("|") - 1)
        elif line.startswith("|"):
            line = re.sub(r" {2,}", " ", line)
        out.append(line)
    return "\n".join(out)
