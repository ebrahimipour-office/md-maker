# md-maker

Convert PDF and DOCX files (also ODT, RTF, EPUB, HTML) to clean Markdown on
Linux and Windows, with proper Persian support. The repetitive work runs
locally; PDF pages the local engines can't get right (tables, scans, mixed
Persian/English, columns, figures) are repaired by Claude through the
installed [Claude Code](https://claude.com/claude-code) CLI, each with the
cheapest model that can do the job. Without the CLI, or with `--ai off`,
everything stays local.

## Install

Each installer sets up the `md-maker` command, Persian + English OCR data,
and the Claude Code skill (`skill/md-maker`, copied to `~/.claude/skills`).
No admin rights, system pandoc or Tesseract needed: pandoc is bundled
(`pypandoc-binary`) and MuPDF has Tesseract built in, so OCR only needs the
language data that `md-maker --install-ocr` downloads.

**Linux**

```bash
scripts/install-linux.sh
```

**Windows** (PowerShell, from the project folder)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
```

### Standalone Windows app (no Python on the target PC)

On a Windows machine with this folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
```

This produces `dist\md-maker-windows-amd64.zip`, about 190 MB, mostly pandoc
and the PDF layout model. Unzip it anywhere and run `md-maker\md-maker.exe`
from a terminal, or drag files onto it in Explorer; the window stays open
to show the result. OCR data is bundled inside. PyInstaller can't
cross-compile, so the Windows build must run on Windows. The same
`scripts/build.py` builds a Linux bundle on Linux.

### AI requirement

AI repair needs Claude Code on the same machine, logged in once
(run `claude`, then `/login`). The installers say so if it's missing.

- **Windows:** both the native install (`claude.exe`) and the npm install
  (`claude.cmd`) work. md-maker passes the prompt text through a file and
  stdin, never the command line, so `cmd.exe` can't mangle Persian text or
  special characters. The standalone `md-maker.exe` uses the `claude` on
  `PATH` too, including when you drag files onto it. If `claude` isn't on
  `PATH`, set `ai.claude_path` in the settings file
  (`%APPDATA%\md-maker\config.toml`) to its full path.
- Without Claude Code, md-maker prints one notice and converts locally.

## Use

```bash
md-maker report.pdf                 # -> report.md next to it
md-maker contract.docx -o out.md
md-maker docs/ -o markdown/         # whole folder, keeps sub-folders
md-maker scan.pdf --ocr always      # force OCR
md-maker scan.pdf --ocr-dpi 150     # retry OCR at another resolution
md-maker file.pdf --stdout          # print instead of writing
md-maker file.pdf --rtl-wrap        # wrap in <div dir="rtl"> for viewers
```

Other options: `--engine rtl|layout`, `--lang fas+eng`, `--page-markers`,
`--no-fix-spacing`, `--media DIR` (extract DOCX images). See `md-maker -h`.

### AI options

```bash
md-maker report.pdf --plan          # how each page would be handled; no conversion, no cost
md-maker report.pdf --report        # also writes report.report.json (route, model, score, cost per page)
md-maker report.pdf --ai max        # every page through AI
md-maker report.pdf --ai off        # local only (also: MD_MAKER_AI=off)
md-maker docs/ --budget 5           # stop sending pages to AI after $5
```

## Settings

`md-maker --init-config` writes a commented settings file
(`~/.config/md-maker/config.toml`, on Windows `%APPDATA%\md-maker\config.toml`);
`md-maker --show-config` prints the effective settings and which files were
read. A `md-maker.toml` in the current folder and `--config FILE` are layered
on top, and command-line flags win over all files. The full list of keys with
their defaults is in [`src/md_maker/data/config.toml`](src/md_maker/data/config.toml).
The most useful ones:

```toml
[ai]
mode = "smart"        # smart | max | off
budget_usd = 2.0      # per run
concurrency = 4

[ai.models]           # which model does which job
polish = "haiku"
repair = "sonnet"
transcribe = "sonnet"
escalate = "opus"
```

## How it works

### AI pipeline (PDF)

1. **Triage** (local, free). Each page is checked for a text layer, broken
   characters, tables, figures, columns, reversed text and lines mixing
   Persian and Latin script, then given a route (`src/md_maker/triage.py`):

   | Route | When | Model | Input |
   |---|---|---|---|
   | `local` | clean text | none | |
   | `polish` | plain Persian text (half-spaces) | haiku | draft text |
   | `repair` | tables, mixed scripts, columns, figures, reversed text | sonnet | page image + draft |
   | `transcribe` | scans, unusable text layer | sonnet | page image |

2. **Draft** (local). The engines below convert every page, as before.
3. **AI**. Routed pages go to `claude -p` in parallel: one tool-less,
   single-turn call per page with a JSON schema for the answer
   (`src/md_maker/ai/`). The CLI uses your own Claude login, so md-maker
   never sees credentials.
4. **Verify** (local). The answer is checked against the text layer: words
   and numbers kept, even table rows, no broken characters, no commentary.
   A weak or unsure result is retried once with the `escalate` model, and
   the better of the two is kept (`src/md_maker/verify.py`).
5. **Merge** (local). Pages are joined, a table split by a page break
   becomes one table, repeated headers/footers are dropped
   (`src/md_maker/merge.py`).

AI never makes a page worse: on any failure (CLI missing, timeout, budget
reached) the local draft is kept and a warning printed. Results are cached
per file, page, model and prompt version (`~/.cache/md-maker`), so reruns
and interrupted runs don't pay twice. Costs are what the CLI reports; on a
Claude subscription they count against your usage limits instead of being
billed, but `budget_usd` still applies to them.

### Local engines

- **DOCX etc.** go through pandoc. A Lua filter drops the `<span dir="rtl">`
  wrappers pandoc adds around Persian text, and table padding is stripped;
  both are pure token cost.
- **PDF** is auto-routed by script:
  - Persian/Arabic documents use a custom extractor (`src/md_maker/pdf.py`).
    It merges line fragments right-to-left, so mixed Persian/English lines
    stay in reading order. It fills table cells character by character,
    detects headings by font size, turns bullets into lists, and drops
    running headers/footers and page numbers.
  - Other documents use `pymupdf4llm` (layout analysis, multi-column, tables).
  - Pages with no text layer are OCR'd (MuPDF's built-in Tesseract). OCR data
    is looked up in `$TESSDATA_PREFIX`, next to a standalone executable, in
    the per-user folder filled by `--install-ocr`, then in an installed
    Tesseract (`src/md_maker/ocr.py`).

### Persian fixes (`src/md_maker/normalize.py`)

| PDF problem | Fix |
|---|---|
| Joined glyph shapes (`ﮔﺰﺍﺭﺵ`) | NFKC → `گزارش` |
| Dropped half-space (`فایلها`) | ZWNJ re-inserted from glyph shapes, before NFKC |
| Half-space became a space (`می شود`, `کتاب ها`, `رفته اند`) | prefix/suffix rules → `می‌شود` |
| Mirrored brackets (`)ریال(`) | `(ریال)` on RTL lines |
| Whole text in visual order (reversed) | detected via common words, un-reversed |
| Arabic `ي ك`, Arabic digits, kashida, bidi control marks | unified / removed |

Known limits:
- A half-space that a PDF turned into a plain space inside a compound word
  (`نرم افزار`) can't be told apart from a real space, so it stays a space.
- OCR of Persian scans is usable but imperfect. Recognition quality swings
  with `--ocr-dpi` (in testing, 300 lost whole lines while 150 and 400 did
  not), Latin words inside Persian lines are often misread, and tables in
  scanned images are not reconstructed.

## Tests

```bash
uv run pytest
MD_MAKER_LIVE=1 uv run pytest -k live   # one real Claude call (about $0.01)
```

The other AI tests use a fake backend and a fake `claude` executable.

Test documents are generated by `tests/make_fixtures.py`.
