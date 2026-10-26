---
name: md-maker
description: Convert PDF, DOCX, ODT, RTF or EPUB files (including Persian/Farsi documents) to Markdown locally with the md-maker CLI before reading them. Use whenever the user asks you to read, summarize, analyze, translate or extract from such a file, so the document is never loaded into context directly.
---

# md-maker

Never read a PDF/DOCX directly; that costs many more tokens than the Markdown version.

1. Convert to the scratchpad (or next to the file if the user wants to keep it):
   ```bash
   md-maker "<file>" -o "<scratchpad>/<name>.md"
   ```
   A folder works too: `md-maker "<dir>" -o "<scratchpad>/md/"`.
2. Read the resulting `.md`. For large files, check its size first and read
   only the sections you need (search for the `#` headings).

By default md-maker sends hard PDF pages (tables, scans, mixed
Persian/English, columns, figures) to Claude through the `claude` CLI,
picking the model per page; progress and cost go to stderr. Results are
cached, so converting the same file again is free.

Options worth knowing:
- `--plan` first for a big PDF: shows which pages would go to which model,
  without converting.
- `--ai off` for a quick, free, local-only look; `--ai max` when the smart
  result is still wrong on pages the triage judged clean.
- `--report` writes `<name>.report.json`; pages with `"source": "local"`
  and an `error`, or a low `score`, are the ones to double-check.
- `--budget USD` to cap AI spending for the run (default from settings, $2).
- `--page-markers` when you need to cite page numbers.
- `--engine layout` or `--engine rtl` to override the auto-detected local PDF
  engine if the output order looks wrong.
- Without AI, scans need local OCR data: `md-maker --install-ocr` once.

If `md-maker` is not installed, tell the user to run the installer in the
md-maker project: `scripts/install-linux.sh` or `scripts\install-windows.ps1`.
