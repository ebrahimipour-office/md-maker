"""Prompts for each AI task. Bump PROMPT_VERSION whenever a prompt changes,
so cached results made with the old wording are not reused."""

import json

PROMPT_VERSION = 2

SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "markdown": {"type": "string", "description": "the page as Markdown"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "notes": {"type": "string", "description": "short: anything illegible or uncertain"},
        },
        "required": ["markdown", "confidence", "notes"],
        "additionalProperties": False,
    }
)

_RULES = """\
You convert ONE page of a document into GitHub-flavored Markdown. You are a
precise transcriber, not an editor.

Rules:
- Keep every word, number and symbol exactly as on the page. Never summarize,
  translate, reword, complete or "fix" the content, and never add commentary.
- Reading order: Persian/Arabic text is right-to-left; keep embedded English
  words, numbers, dates, versions and URLs in their correct place within the
  sentence. Multi-column pages: read each column fully, in the page's column
  order (right column first for Persian).
- Persian spelling: use ی and ک (not Arabic ي ك); write half-spaces (ZWNJ,
  U+200C) where Persian requires them, e.g. می‌شود، نمی‌خواهم، کتاب‌ها،
  بزرگ‌ترین، رفته‌اند، نرم‌افزار. Keep digits in the script the page uses
  (۱۲۳ vs 123).
- Structure: `#` for the document title, `##`/`###` for section headings by
  visual size; `-` for bullet lists, `1.` for numbered lists; join lines of a
  paragraph that the layout wrapped; keep real paragraph breaks.
- Tables: GFM pipe tables, header row first, columns in logical order (for a
  Persian table the rightmost column is the first column). For a merged cell,
  repeat its text in each cell it spans. Escape `|` inside cells as `\\|`.
- Leave out page numbers and running headers/footers repeated on every page.
- {figures}
- If part of the page is illegible, write what you can and mention it in
  `notes`; set `confidence` to low when you had to guess.
- Return only the structured output: no code fences around the Markdown."""

_FIGURES_ON = (
    "Figures, charts, photos, diagrams and logos: one line in their place, "
    "`> [Figure: <short description>]` on English pages, `> [تصویر: <توضیح کوتاه>]` "
    "on Persian pages. Transcribe text inside a chart only if it carries data."
)
_FIGURES_OFF = "Ignore figures, photos and logos; transcribe only the text."


def system_prompt(figure_notes: bool) -> str:
    return _RULES.replace("{figures}", _FIGURES_ON if figure_notes else _FIGURES_OFF)


def _where(page: int, pages: int) -> str:
    return f"This is page {page + 1} of {pages}."


def polish(draft: str, page: int, pages: int) -> str:
    return f"""{_where(page, pages)} A local tool extracted this page's text from the PDF
text layer. The words are right, but the extraction may have:
- lost Persian half-spaces (می شود, نرم افزار, کتاب ها) or glued words together;
- missed headings, list items or paragraph joins.

Fix only those problems. Do not add, drop or reword anything. There is no
page image: judge from the text alone, and treat the draft as the complete
page, however short. If nothing needs fixing, return it unchanged with
confidence high.

<draft>
{draft}
</draft>"""


def repair(draft: str, page: int, pages: int) -> str:
    return f"""{_where(page, pages)} The attached image is the page. Below is a draft a
local tool made from the PDF text layer: its characters are usually exact,
but word order on mixed Persian/English lines, tables, columns, headings and
lists are often wrong, and figures are missing.

Produce the correct Markdown for the page. The image is the authority for
order and structure; prefer the draft's spelling and digits where they agree
with the image.

<draft>
{draft}
</draft>"""


def transcribe(page: int, pages: int) -> str:
    return f"""{_where(page, pages)} The attached image is a scanned page (or one whose
text layer is unusable). Transcribe it into Markdown following the rules."""
